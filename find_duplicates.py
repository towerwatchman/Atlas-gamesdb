#!/usr/bin/env python3
"""
READ-ONLY duplicate-game finder for atlas / f95_zone / lewdcorner.

    python find_duplicates.py                 # all duplicate groups, printed
    python find_duplicates.py --scope f95      # only groups touching f95_zone
    python find_duplicates.py --scope lc       # only groups touching lewdcorner
    python find_duplicates.py --scope cross    # only f95<->lc cross-source dups
    python find_duplicates.py --fuzzy-floor 0.85
    python find_duplicates.py --csv dupes.csv  # also dump every group to CSV

What it looks for
-----------------
A "duplicate game" = two or more DISTINCT atlas rows (different atlas_id)
that are almost certainly the same game. Two detectors run:

  1. EXACT  -- the same computed id_name (short_name + '_' + CREATOR) appears
     on more than one atlas row. These are the same title+creator entered
     twice under different atlas_ids (so different f95_id/lc_id).

  2. FUZZY  -- rows whose normalized title+creator similarity is >= the
     fuzzy floor (default 0.90) but whose id_name is NOT identical. These
     catch spelling variants ("Black Market" vs "Black-Market", trailing
     spaces, "SOULCOOM" vs "Soulcoom Team", ? in place of punctuation).
     Blocked by a short normalized-title prefix so it stays fast on a large
     atlas table instead of comparing every row to every other row.

For every group it prints each atlas row with the source id(s) attached
(f95_id / lc_id), so you can see exactly which threads collided.

This script NEVER writes, updates, or deletes anything. It only SELECTs.
Use reconcile_lc.py (or a dedicated merge pass) to actually resolve what
this surfaces.
"""
import argparse
import csv as csvmod
import difflib
import re
import sys
from collections import defaultdict

from scraper.config import config
from scraper.utils.db import _run

# ------------------------------------------------------------------ display


def _c(s, code):
    return f"\033[{code}m{s}\033[0m"


def bold(s):  return _c(s, "1")
def green(s): return _c(s, "32")
def yellow(s):return _c(s, "33")
def cyan(s):  return _c(s, "36")
def red(s):   return _c(s, "31")
def dim(s):   return _c(s, "2")


def _short(v, n=55):
    v = "" if v is None else str(v)
    v = " ".join(v.split())
    return v if len(v) <= n else v[: n - 1] + "\u2026"


# ------------------------------------------------------------- normalization


def _norm(s):
    return re.sub(r"[\W_]+", "", (s or "").lower())


def _sim(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _score(a, b):
    """title+creator similarity, title weighted 0.7. Falls back to pure
    title similarity if either creator is blank."""
    t = _sim(a.get("title"), b.get("title"))
    ca = a.get("creator") or a.get("developer")
    cb = b.get("creator") or b.get("developer")
    if not _norm(ca) or not _norm(cb):
        return t
    return 0.7 * t + 0.3 * _sim(ca, cb)


_ROMAN = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii", "xiii"}


def _seq_tokens(title):
    """Sequence markers in a title: arabic digit-runs plus standalone
    multi-character roman numerals. Used to tell a SEQUEL apart from a
    duplicate -- 'Haydee 2' and 'Haydee 3' are highly similar but are
    different games. Single-letter romans (i/v/x) are deliberately excluded
    (too easily 'v' for version, 'x' as an 'adult' tag, etc.)."""
    low = (title or "").lower()
    nums = set(re.findall(r"\d+", low))
    romans = {w for w in re.findall(r"[a-z]+", low) if w in _ROMAN}
    return nums | romans


def _is_sequel_pair(a, b):
    """True if two titles look like different entries in a series: their
    sequence markers differ (one has '2', the other '3'; or one is numbered
    and the other isn't). Those must NOT be reported as duplicates."""
    sa, sb = _seq_tokens(a.get("title")), _seq_tokens(b.get("title"))
    if sa == sb:
        return False
    # If neither side carries any marker, it's not a sequence distinction.
    if not sa and not sb:
        return False
    return True


# ---------------------------------------------------------------- data load


def load_atlas_with_sources():
    """One read-only pass: every atlas row, with the f95_id and lc_id (if
    any) attached via LEFT JOIN. Returns a list of dicts. atlas_id is the
    primary key; f95_id/lc_id are None when that source doesn't own the row.
    """
    return _run(
        """
        SELECT a.atlas_id, a.title, a.creator, a.developer,
               a.short_name, a.id_name, a.version, a.engine, a.status,
               f.f95_id, l.lc_id
        FROM atlas a
        LEFT JOIN f95_zone   f ON f.atlas_id = a.atlas_id
        LEFT JOIN lewdcorner l ON l.atlas_id = a.atlas_id
        ORDER BY a.atlas_id
        """,
        fetch="all", dict_cursor=True,
    ) or []


def _sources(row):
    """Which source tables reference this atlas row, as a set."""
    s = set()
    if row.get("f95_id") is not None:
        s.add("f95")
    if row.get("lc_id") is not None:
        s.add("lc")
    return s


def _group_sources(group):
    s = set()
    for r in group:
        s |= _sources(r)
    return s


# ---------------------------------------------------------------- detectors


def find_exact_groups(rows):
    """Groups of >1 DISTINCT atlas rows sharing the same id_name."""
    by = defaultdict(list)
    for r in rows:
        key = (r.get("id_name") or "").strip()
        if key and key != "_":
            by[key].append(r)
    groups = []
    for key, members in by.items():
        ids = {m["atlas_id"] for m in members}
        if len(ids) > 1:
            groups.append((key, members))
    return groups


def find_fuzzy_groups(rows, floor=0.90, already_grouped=None):
    """Near-duplicate rows: high title+creator similarity but NOT an exact
    id_name match. Blocked by normalized-title prefix so we never do a full
    O(n^2) comparison across the whole atlas table.

    already_grouped: set of atlas_ids already reported as exact dups, so we
    don't re-flag those pairs here.
    """
    already_grouped = already_grouped or set()

    # Block by the first 4 chars of the normalized title. Same-game spelling
    # variants virtually always share a title prefix; this shrinks the
    # comparison set from "whole table" to "handful per bucket".
    buckets = defaultdict(list)
    for r in rows:
        key = _norm(r.get("title"))[:4]
        if key:
            buckets[key].append(r)

    seen_pairs = set()
    # union-find so a bucket with A~B and B~C reports one {A,B,C} group
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    row_by_id = {r["atlas_id"]: r for r in rows}

    for members in buckets.values():
        n = len(members)
        if n < 2:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                a, b = members[i], members[j]
                if a["atlas_id"] == b["atlas_id"]:
                    continue
                # skip if identical id_name (that's the exact detector's job)
                if (a.get("id_name") or "").strip() == (b.get("id_name") or "").strip():
                    continue
                pair = tuple(sorted((a["atlas_id"], b["atlas_id"])))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                # different entries in a numbered series are not duplicates
                if _is_sequel_pair(a, b):
                    continue
                if _score(a, b) >= floor:
                    union(a["atlas_id"], b["atlas_id"])

    clusters = defaultdict(list)
    for aid in list(parent.keys()):
        clusters[find(aid)].append(aid)

    groups = []
    for members_ids in clusters.values():
        ids = set(members_ids)
        if len(ids) > 1:
            groups.append(("(fuzzy)", [row_by_id[i] for i in sorted(ids)]))
    return groups


# ---------------------------------------------------------------- reporting


def _fmt_row(r):
    f95 = r.get("f95_id")
    lc = r.get("lc_id")
    src = []
    if f95 is not None:
        src.append(cyan(f"f95_id {f95}"))
    if lc is not None:
        src.append(yellow(f"lc_id {lc}"))
    src = "  ".join(src) if src else red("(no source!)")
    return (f"    atlas_id {bold(str(r['atlas_id'])):>8}  {src}\n"
            f"        title  : {_short(r.get('title'))}\n"
            f"        creator: {_short(r.get('creator'), 40)}   "
            f"ver: {_short(r.get('version'), 18)}")


def _scope_ok(group, scope):
    srcs = _group_sources(group)
    if scope == "all":
        return True
    if scope == "f95":
        return "f95" in srcs
    if scope == "lc":
        return "lc" in srcs
    if scope == "cross":
        return "f95" in srcs and "lc" in srcs
    return True


def report(exact_groups, fuzzy_groups, scope, csv_path=None):
    exact_groups = [g for g in exact_groups if _scope_ok(g[1], scope)]
    fuzzy_groups = [g for g in fuzzy_groups if _scope_ok(g[1], scope)]

    def _print_section(title, groups):
        print(bold(f"\n{'='*72}\n{title}: {len(groups)} group(s)\n{'='*72}"))
        for key, members in sorted(groups, key=lambda g: -len(g[1])):
            srcs = "+".join(sorted(_group_sources(members))) or "none"
            print(f"\n{bold(key)}  ({len(members)} rows, sources: {srcs})")
            for r in sorted(members, key=lambda x: x["atlas_id"]):
                print(_fmt_row(r))

    _print_section("EXACT id_name duplicates", exact_groups)
    _print_section("FUZZY near-duplicates", fuzzy_groups)

    # counts
    exact_rows = sum(len(m) for _, m in exact_groups)
    fuzzy_rows = sum(len(m) for _, m in fuzzy_groups)
    # rows that could be collapsed away = rows - one-kept-per-group
    exact_removable = exact_rows - len(exact_groups)
    fuzzy_removable = fuzzy_rows - len(fuzzy_groups)

    print(green(bold(
        f"\n\nSummary (scope={scope}):\n"
        f"  exact id_name duplicate groups : {len(exact_groups):>5}  "
        f"({exact_rows} rows, ~{exact_removable} redundant)\n"
        f"  fuzzy near-duplicate groups    : {len(fuzzy_groups):>5}  "
        f"({fuzzy_rows} rows, ~{fuzzy_removable} redundant)")))

    if csv_path:
        _dump_csv(csv_path, exact_groups, fuzzy_groups)
        print(green(f"\nWrote every flagged row to {csv_path}"))


def _dump_csv(path, exact_groups, fuzzy_groups):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csvmod.writer(f)
        w.writerow(["kind", "group_key", "group_size", "sources",
                    "atlas_id", "f95_id", "lc_id",
                    "title", "creator", "version", "id_name"])
        for kind, groups in (("exact", exact_groups), ("fuzzy", fuzzy_groups)):
            for key, members in groups:
                srcs = "+".join(sorted(_group_sources(members)))
                for r in sorted(members, key=lambda x: x["atlas_id"]):
                    w.writerow([kind, key, len(members), srcs,
                                r["atlas_id"], r.get("f95_id"), r.get("lc_id"),
                                r.get("title"), r.get("creator"),
                                r.get("version"), r.get("id_name")])


# --------------------------------------------------------------------- main


def run(scope="all", fuzzy_floor=0.90, csv_path=None, no_fuzzy=False):
    print(dim("  loading atlas + sources (read-only)..."), flush=True)
    rows = load_atlas_with_sources()
    print(dim(f"  {len(rows)} atlas rows loaded"), flush=True)

    exact = find_exact_groups(rows)
    exact_ids = {m["atlas_id"] for _, members in exact for m in members}

    if no_fuzzy:
        fuzzy = []
    else:
        print(dim("  scanning for fuzzy near-duplicates..."), flush=True)
        fuzzy = find_fuzzy_groups(rows, floor=fuzzy_floor,
                                  already_grouped=exact_ids)

    report(exact, fuzzy, scope, csv_path=csv_path)


def main():
    ap = argparse.ArgumentParser(
        description="READ-ONLY duplicate-game finder for atlas/f95_zone/lewdcorner")
    ap.add_argument("--scope", choices=["all", "f95", "lc", "cross"],
                    default="all",
                    help="all groups, or only those touching f95 / lc / both")
    ap.add_argument("--fuzzy-floor", type=float, default=0.90,
                    help="min title+creator similarity for a fuzzy dup "
                         "(0-1, default 0.90; lower = more, noisier hits)")
    ap.add_argument("--no-fuzzy", action="store_true",
                    help="only report exact id_name duplicates (fast)")
    ap.add_argument("--csv", dest="csv_path", default=None,
                    help="also write every flagged row to this CSV file")
    args = ap.parse_args()

    print(dim(f"DB: {config.env_status()}"))
    try:
        run(scope=args.scope, fuzzy_floor=args.fuzzy_floor,
            csv_path=args.csv_path, no_fuzzy=args.no_fuzzy)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
