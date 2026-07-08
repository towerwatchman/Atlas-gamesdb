#!/usr/bin/env python3
"""
Import new F95 games from a CSV export straight into `f95_zone` (+ `atlas`).

    python import_f95_csv.py gamelist_not_in_f95_zone_data_v2.csv

Expected CSV columns (matches gamelist_not_in_f95_zone_data_v2.csv):
    IDF95, IDDistant, Name, Author, Version, DateModif, F95ZoneURL,
    Site, Tags, Prefix, Cover

Mostly automatic. For every row:

  1. ALREADY HAVE IT -- f95_id already exists in `f95_zone`
     -> skip (nothing to do, it's already imported).

  2. Otherwise, find the single best-matching existing atlas row by
     title+creator (exact id_name match scores 1.0; everything else is
     ranked by fuzzy title/creator similarity, same scoring reconcile_lc
     uses).

       - best score <= --threshold (default 0.70) -> CREATE a brand-new
         atlas + f95_zone row. A low score means nothing in atlas looks
         like this game, so it's genuinely new.
       - best score  > --threshold -> usually a duplicate, so SKIP...
         EXCEPT when the only real difference between this title and the
         matched one is a sequence number ('Witch' vs 'Witch 2'). Those
         score high but are almost certainly a NEW entry in a series, not
         a dup, so they're routed to MANUAL APPROVAL: for each one you're
         shown the CSV game and the existing game it matched, and choose
         [y]es create as new / [n]o skip as dup / [a]ll approve the rest /
         [q]uit. Control this with:
             (default)          prompt for each sequel-looking match
             --approve-sequels  auto-create them all as new (no prompt)
             --skip-sequels     treat them as dups and skip (old behavior)

Everything except the sequel prompts is automatic. Re-run with a
lower/higher --threshold and inspect the log lines if you want to tune it.

Design notes
------------
* Reuses the scraper's own DB layer (scraper.utils.db) -- same connection,
  same credentials from .env, no separate config.
* Never touches or deletes an existing atlas row -- this script only ever
  INSERTs new atlas/f95_zone rows, it never links to or modifies existing
  ones.
* Safe to interrupt and re-run: rows already in f95_zone are skipped.
"""
import argparse
import csv
import difflib
import html
import json
import re
import sys
import time

from scraper.config import config
from scraper.datatypes.data import data
from scraper.utils.epoch import epoch
from scraper.utils.db import (
    getAtlasIdByF95Id, findAtlasIdsByIdName, findFuzzyAtlasCandidates,
    getAtlasRowsByIds, getAtlasSourceIds, getAtlasSourceOwners,
    insertAtlas, UpdatetableDynamic,
)

# ------------------------------------------------------------------ display


def _c(s, code):
    return f"\033[{code}m{s}\033[0m"


def bold(s):  return _c(s, "1")
def green(s): return _c(s, "32")
def yellow(s):return _c(s, "33")
def dim(s):   return _c(s, "2")


def _short(v, n=60):
    v = "" if v is None else str(v)
    v = " ".join(v.split())
    return v if len(v) <= n else v[: n - 1] + "\u2026"


# ------------------------------------------------------------- CSV -> record


def _norm(s):
    return re.sub(r"[\W_]+", "", (s or "").lower())


def _sim(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _score(a_row, b_row):
    t = _sim(a_row.get("title"), b_row.get("title"))
    c = _sim(a_row.get("creator") or a_row.get("developer"),
             b_row.get("creator") or b_row.get("developer"))
    if not _norm(a_row.get("creator") or a_row.get("developer")) or \
       not _norm(b_row.get("creator") or b_row.get("developer")):
        return t
    return 0.7 * t + 0.3 * c


def _best_match(atlas):
    """Return (score, atlas_row_or_None) -- the single best-matching
    existing atlas row for this CSV game, by title+creator. Checks an
    exact id_name match first (score 1.0, no need to rank anything else),
    then falls back to the same prefix-search fuzzy candidates
    reconcile_lc uses."""
    exact_ids = findAtlasIdsByIdName(atlas["id_name"])
    if exact_ids:
        rows = getAtlasRowsByIds(exact_ids[:1])
        return 1.0, (rows[0] if rows else None)

    fuzzy_ids = findFuzzyAtlasCandidates(atlas["short_name"], atlas["creator"])
    if not fuzzy_ids:
        return 0.0, None

    pool = getAtlasRowsByIds(fuzzy_ids)
    best_score, best_row = 0.0, None
    for cand in pool:
        s = _score(atlas, cand)
        if s > best_score:
            best_score, best_row = s, cand
    return best_score, best_row


# ------------------------------------------------------------- sequel detect

_ROMAN = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii", "xiii"}


def _seq_tokens(title):
    """Sequence markers in a title: arabic digit-runs plus standalone
    multi-character roman numerals. Lets us tell a SEQUEL apart from a true
    duplicate -- 'Witch' and 'Witch 2' are highly similar but are different
    games. Single-letter romans (i/v/x) are excluded (too easily 'v' for
    version, 'x' as an adult tag, etc.)."""
    low = (title or "").lower()
    nums = set(re.findall(r"\d+", low))
    romans = {w for w in re.findall(r"[a-z]+", low) if w in _ROMAN}
    return nums | romans


def _is_sequel_pair(a_title, b_title):
    """True if two titles look like different entries in a numbered series:
    their sequence markers differ (one has '2', the other none or '3').
    A high-scoring match that is ALSO a sequel pair is probably a NEW game,
    not a duplicate -- so it gets routed to manual approval instead of an
    automatic skip."""
    sa, sb = _seq_tokens(a_title), _seq_tokens(b_title)
    if sa == sb:
        return False
    if not sa and not sb:
        return False
    return True


_PREFIX_CACHE = {
    "category": {p.upper() for p in data.Tcategory()},
    "engine": {p.upper() for p in data.Tengine()},
    "status": {p.upper() for p in data.Tstaus()},
}


def _clean_prefix_label(label):
    # A literal backslash-escaped quote (Ren\'Py) shows up on some export
    # passes -- normalize it down to a plain apostrophe. HTML entities are
    # handled earlier, on the whole raw string (see _parse_prefixes) since
    # an entity like &#039; contains its own ';' and would otherwise get
    # split apart before it's decoded.
    label = (label or "").replace("\\'", "'").strip()
    return label


def _parse_prefixes(raw):
    """Split the CSV's ';'-joined Prefix field and classify each label into
    category/engine/status, same rule the live f95 agent uses on the detail
    page's prefix labels. Unrecognized labels (Mod, CG, Collection, ...) are
    simply dropped, matching existing behavior."""
    out = {"category": "", "engine": "", "status": ""}
    # Unescape entities on the WHOLE string first -- e.g. "Ren&#039;Py" has
    # its own ';' inside the entity, which would get chopped in half if we
    # split before decoding.
    decoded = html.unescape(raw or "")
    for raw_label in decoded.split(";"):
        label = _clean_prefix_label(raw_label)
        if not label:
            continue
        up = label.upper()
        if up in _PREFIX_CACHE["category"]:
            out["category"] = label
        elif up in _PREFIX_CACHE["engine"]:
            out["engine"] = label
        elif up in _PREFIX_CACHE["status"]:
            out["status"] = label
    return out


def _clean(d):
    return {k: v for k, v in d.items() if v}


def build_records(row):
    """CSV row -> (atlas dict, f95 dict), same shape insertAtlas/f95_zone
    expect (mirrors scraper.agents.f95._process_listing_item)."""
    title = (row.get("Name") or "").strip()
    creator = (row.get("Author") or "").strip()
    version = (row.get("Version") or "").strip()
    short_name = re.sub(r"[\W_]+", "", title.replace(" ", "")).upper()
    id_name = short_name + "_" + creator.upper()

    prefixes = _parse_prefixes(row.get("Prefix"))

    atlas = {
        "title": title,
        "creator": creator,
        "version": version,
        "short_name": short_name,
        "id_name": id_name,
        "category": prefixes["category"],
        "engine": prefixes["engine"],
        "status": prefixes["status"],
    }

    extra = {}
    if (row.get("IDDistant") or "").strip():
        extra["distant_id"] = row["IDDistant"].strip()
    if (row.get("Site") or "").strip():
        extra["external_site"] = row["Site"].strip()
    if extra:
        atlas["external_ids"] = json.dumps(extra, ensure_ascii=False)

    thread_updated = epoch.ConvertToUnixTime((row.get("DateModif") or "").strip())

    f95rec = {
        "f95_id": (row.get("IDF95") or "").strip(),
        "site_url": (row.get("F95ZoneURL") or "").strip(),
        "banner_url": (row.get("Cover") or "").strip(),
        "tags": (row.get("Tags") or "").strip().replace(";", ","),
        "thread_updated": thread_updated or "",
    }

    return atlas, f95rec


# ---------------------------------------------------------------- persistence


def _create_new(atlas, f95rec):
    now = int(time.time())
    atlas = dict(atlas)
    f95rec = dict(f95rec)
    atlas["last_record_update"] = now
    f95rec["last_record_update"] = now
    new_atlas_id = insertAtlas(_clean(atlas))
    f95rec["atlas_id"] = new_atlas_id
    UpdatetableDynamic("f95_zone", _clean(f95rec))
    return new_atlas_id


# ------------------------------------------------------------ sequel review


def cyan(s):  return _c(s, "36")
def red(s):   return _c(s, "31")


def _match_context(match_row):
    """A short 'this matched f95_id X / lc_id Y (Title)' line for the row the
    CSV game scored highest against, so the reviewer can see WHAT it collided
    with before deciding."""
    if not match_row:
        return dim("(no matching row)")
    aid = match_row.get("atlas_id")
    src = getAtlasSourceIds(aid) or {}
    owners = getAtlasSourceOwners(aid) or []
    bits = []
    if src.get("f95_id") is not None:
        bits.append(cyan(f"f95_id {src['f95_id']}"))
    if src.get("lc_id") is not None:
        bits.append(yellow(f"lc_id {src['lc_id']}"))
    src_str = "  ".join(bits) if bits else (", ".join(owners) or red("no source"))
    return (f"atlas_id {aid}  {src_str}\n"
            f"        existing title  : {_short(match_row.get('title'))}\n"
            f"        existing creator: {_short(match_row.get('creator'), 40)}")


def _ask_sequel(n, total, atlas, f95_id, score, match_row):
    """Prompt the reviewer about a high-scoring SEQUEL-looking match. Returns
    one of: 'create', 'skip', 'all' (approve this and all remaining), 'quit'."""
    print("=" * 72)
    print(bold(f"[{n}/{total}]  possible NEW sequel/entry "
               f"(scored {score:.0%} vs an existing game)"))
    print(bold("  CSV game"))
    print(f"    title   : {cyan(atlas['title'])}")
    print(f"    creator : {atlas['creator'] or dim('(none)')}")
    print(f"    version : {atlas['version'] or dim('(none)')}")
    print(f"    f95_id  : {f95_id}")
    print(dim("  best existing match:"))
    print(f"    {_match_context(match_row)}")
    print(dim("  create this as a NEW game?  "
              "[y]es  [n]o (skip as dup)  [a]ll (yes to all remaining)  [q]uit"))
    while True:
        raw = input(bold("  choose > ")).strip().lower()
        if raw in ("y", "yes"):
            return "create"
        if raw in ("n", "no", ""):
            return "skip"
        if raw in ("a", "all"):
            return "all"
        if raw in ("q", "quit"):
            return "quit"
        print(red("    enter y / n / a / q"))


# --------------------------------------------------------------------- main


def run_import(csv_path, threshold=0.70, dry_run=False, limit=None,
               sequel_mode="ask"):
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]
    print(bold(f"{len(rows)} row(s) in {csv_path}  "
               f"(auto-create at <= {threshold:.0%} match, skip above)\n"))

    if dry_run:
        print(yellow(bold("  DRY RUN -- no changes will be written\n")))

    already = created = skipped_match = no_title = 0
    created_sequel = skipped_sequel = 0
    approve_all = (sequel_mode == "approve")   # [a] latches this on mid-run

    for n, row in enumerate(rows, 1):
        f95_id = (row.get("IDF95") or "").strip()
        if not f95_id:
            print(dim(f"[{n}/{len(rows)}] no IDF95 -- skipping row"))
            continue

        if getAtlasIdByF95Id(f95_id):
            already += 1
            continue

        atlas, f95rec = build_records(row)

        # atlas.title, .short_name and .id_name are all NOT NULL with no
        # default. A blank title, or a title with no alphanumeric chars at
        # all (e.g. "??????"), leaves one of these empty -- _clean() then
        # drops the empty value and the INSERT blows up. Skip those rows.
        if not atlas["title"] or not atlas["short_name"] or not atlas["id_name"].strip("_"):
            no_title += 1
            print(dim(f"[{n}/{len(rows)}] unusable title/name "
                      f"(f95_id {f95_id}) -- skipping row"))
            continue

        score, match_row = _best_match(atlas)

        if score > threshold:
            # High match -> normally a duplicate, so skip. BUT if the only
            # real difference between this title and the matched one is a
            # sequence number ('Witch' vs 'Witch 2'), it's probably a NEW
            # game in a series, not a dup -- route it to review.
            is_sequel = match_row and _is_sequel_pair(
                atlas["title"], match_row.get("title"))

            if not is_sequel:
                skipped_match += 1
                print(dim(f"[{n}/{len(rows)}] skip {score:.0%} match "
                          f"(atlas_id {match_row['atlas_id'] if match_row else '?'}) "
                          f"{_short(atlas['title'], 40)}"))
                continue

            # It's a sequel-looking high match. Decide per sequel_mode.
            if sequel_mode == "skip":
                skipped_sequel += 1
                print(dim(f"[{n}/{len(rows)}] skip sequel-match {score:.0%} "
                          f"{_short(atlas['title'], 40)}"))
                continue

            if dry_run:
                print(yellow(f"[{n}/{len(rows)}] [sequel? would ask] "
                             f"{_short(atlas['title'], 40)} ({atlas['creator']}) "
                             f"~{score:.0%} vs "
                             f"{_short(match_row.get('title'), 30)}"))
                created_sequel += 1
                continue

            if approve_all:
                decision = "create"
            else:
                decision = _ask_sequel(n, len(rows), atlas, f95_id,
                                       score, match_row)
                if decision == "all":
                    approve_all = True
                    decision = "create"

            if decision == "quit":
                print("Stopping.")
                break
            if decision == "skip":
                skipped_sequel += 1
                print(dim("  skipped as duplicate\n"))
                continue

            new_id = _create_new(atlas, f95rec)
            print(green(f"  created atlas_id {new_id} -> f95_id {f95_id}: "
                        f"{_short(atlas['title'], 40)} (approved sequel)\n"))
            created_sequel += 1
            continue

        if dry_run:
            print(green(f"[{n}/{len(rows)}] [would create] "
                        f"{_short(atlas['title'], 40)} ({atlas['creator']}) "
                        f"best match {score:.0%}"))
            created += 1
            continue

        new_id = _create_new(atlas, f95rec)
        print(green(f"[{n}/{len(rows)}] created atlas_id {new_id} "
                    f"-> f95_id {f95_id}: {_short(atlas['title'], 40)} "
                    f"(best match was {score:.0%})"))
        created += 1

    verb = "would create" if dry_run else "created"
    extra = f", {no_title} skipped (unusable title/name)" if no_title else ""
    seq_verb = "would create" if dry_run else "created"
    seq = ""
    if created_sequel or skipped_sequel:
        seq = (f"\n  sequels: {created_sequel} {seq_verb} as new, "
               f"{skipped_sequel} skipped as dup")
    print(green(
        f"\nImport pass: {created} {verb}, {already} already in f95_zone, "
        f"{skipped_match} skipped (match > {threshold:.0%}){extra}.{seq}"))


def main():
    ap = argparse.ArgumentParser(description="Import F95 games from CSV into atlas/f95_zone")
    ap.add_argument("csv_path", help="path to the CSV file")
    ap.add_argument("--threshold", type=float, default=0.70,
                     help="best-match score above which a row is skipped "
                          "as a likely duplicate; at/below it, create "
                          "(0-1, default 0.70)")
    ap.add_argument("--dry-run", action="store_true",
                     help="show what would happen without changing the DB")
    ap.add_argument("--limit", type=int, default=None,
                     help="only process the first N rows (for testing)")
    seq = ap.add_mutually_exclusive_group()
    seq.add_argument("--approve-sequels", dest="sequel_mode",
                     action="store_const", const="approve",
                     help="auto-create every sequel-looking high match as a "
                          "new game (no prompt)")
    seq.add_argument("--skip-sequels", dest="sequel_mode",
                     action="store_const", const="skip",
                     help="treat sequel-looking high matches as duplicates "
                          "and skip them (no prompt, old behavior)")
    ap.set_defaults(sequel_mode="ask")
    args = ap.parse_args()

    print(dim(f"DB: {config.env_status()}"))
    try:
        run_import(args.csv_path, threshold=args.threshold,
                   dry_run=args.dry_run, limit=args.limit,
                   sequel_mode=args.sequel_mode)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()