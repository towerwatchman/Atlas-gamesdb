#!/usr/bin/env python3
"""
Interactive LewdCorner <-> atlas reconciler.

Two jobs, one tool:

  1. CLEANUP (fix the DB now):
       python reconcile_lc.py cleanup
     Scans EXISTING `lewdcorner` rows whose computed atlas id_name matches
     more than one atlas row -- i.e. the rows that the old LIMIT-1 linker may
     have attached to the wrong atlas game. For each, shows the LC game and
     every candidate atlas row (with which source owns it), lets you pick the
     correct one, repoints lewdcorner.atlas_id, and -- if you confirm --
     deletes an incorrect/orphaned atlas row (never one still owned by
     another source).

  2. QUEUE (ongoing):
       python reconcile_lc.py queue          # all pending
       python reconcile_lc.py queue --kind multi
       python reconcile_lc.py queue --kind fuzzy
     Resolves items the scraper parked in `lc_review_queue` because they were
     ambiguous at scrape time. Picking a candidate writes the real lewdcorner
     row (linked to your chosen atlas_id) and removes the queue entry. You can
     also mark an item as "new" (create a fresh atlas row from the LC data) or
     skip it.

Design notes
------------
* Reuses the scraper's own DB layer (scraper.utils.db) -- same connection,
  same credentials from .env, no separate config.
* Never deletes an atlas row that another source (f95_zone/dlsite/sxs) still
  references. Deletion is always an explicit y/N confirm.
* Idempotent: safe to run repeatedly. Re-running cleanup after fixing a row
  won't re-flag it (it'll no longer be a multi-match, or it'll already point
  at the surviving atlas_id).
"""
import argparse
import json
import sys

from scraper.config import config
from scraper.utils.db import (
    _run,
    findAtlasIdsByIdName, findFuzzyAtlasCandidates,
    getAtlasRowsByIds, getAtlasSourceOwners, getAtlasSourceIds,
    deleteAtlasById, relinkLewdcornerAtlasId,
    getLcReviewQueue, dequeueLcReview,
    insertAtlas, UpdatetableDynamic,
)

# ------------------------------------------------------------------ display

def _c(s, code):
    return f"\033[{code}m{s}\033[0m"

def bold(s):  return _c(s, "1")
def green(s): return _c(s, "32")
def yellow(s):return _c(s, "33")
def cyan(s):  return _c(s, "36")
def red(s):   return _c(s, "31")
def dim(s):   return _c(s, "2")


def _short(v, n=60):
    v = "" if v is None else str(v)
    v = " ".join(v.split())
    return v if len(v) <= n else v[: n - 1] + "\u2026"


def print_lc(title, creator, version, url, banner=""):
    print(bold("  LewdCorner game"))
    print(f"    title   : {cyan(title)}")
    print(f"    creator : {creator or dim('(none)')}")
    print(f"    version : {version or dim('(none)')}")
    print(f"    url     : {dim(_short(url, 80))}")
    if banner:
        print(f"    banner  : {dim(_short(banner, 80))}")


def print_candidate(idx, arow, owners, src_ids=None):
    aid = arow.get("atlas_id")
    owner_str = ", ".join(owners) if owners else red("ORPHAN (no source)")
    print(f"  {bold('[' + str(idx) + ']')} atlas_id "
          f"{yellow(str(aid))}  owned by: {owner_str}")
    src_ids = src_ids or {}
    f95v = src_ids.get("f95_id")
    lcv = src_ids.get("lc_id")
    print(f"        f95_id  : "
          f"{cyan(str(f95v)) if f95v is not None else dim('(none)')}"
          f"   lc_id : "
          f"{cyan(str(lcv)) if lcv is not None else dim('(none)')}")
    print(f"        title   : {_short(arow.get('title'))}")
    print(f"        creator : {_short(arow.get('creator'))}  "
          f"dev: {_short(arow.get('developer'), 30)}")
    print(f"        version : {_short(arow.get('version'), 20)}  "
          f"engine: {_short(arow.get('engine'), 20)}  "
          f"status: {_short(arow.get('status'), 20)}")
    print(f"        id_name : {dim(_short(arow.get('id_name')))}")


def _prompt(valid_letters, n_candidates):
    """Return one of: int index (0-based), or a letter command."""
    while True:
        raw = input(bold("  choose > ")).strip().lower()
        if raw in valid_letters:
            return raw
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= n_candidates:
                return i - 1
        print(red(f"    enter 1-{n_candidates} or one of "
                  f"{'/'.join(sorted(valid_letters))}"))


# ------------------------------------------------------------- shared action

def _safe_delete_candidates(chosen_atlas_id, candidate_ids):
    """Offer to delete the NON-chosen candidate atlas rows, but only those
    that are truly orphaned (no source references them anymore)."""
    for aid in candidate_ids:
        if aid == chosen_atlas_id:
            continue
        owners = getAtlasSourceOwners(aid)
        if owners:
            print(dim(f"    keeping atlas_id {aid} (still owned by "
                      f"{', '.join(owners)})"))
            continue
        ans = input(red(f"    delete orphaned atlas_id {aid}? [y/N] ")).strip().lower()
        if ans == "y":
            deleteAtlasById(aid)
            print(green(f"    deleted atlas_id {aid}"))
        else:
            print(dim(f"    left atlas_id {aid} in place"))


# --------------------------------------------------------------- cleanup job

def _existing_multimatch_lc_rows():
    """LC rows currently in `lewdcorner` whose atlas id_name matches >1 atlas
    row. Returns list of (lc_id, current_atlas_id, id_name, candidate_ids).

    Done in a handful of queries total (not one-per-row): first find every
    id_name that is duplicated in atlas, then find LC rows whose atlas row
    carries one of those id_names, then map each duplicated id_name to its
    full candidate list.
    """
    print(dim("  scanning atlas for duplicate id_names..."), flush=True)
    dup_rows = _run(
        """
        SELECT id_name FROM atlas
        GROUP BY id_name HAVING COUNT(*) > 1
        """,
        fetch="all",
    ) or []
    dup_names = [r[0] for r in dup_rows]
    print(dim(f"  {len(dup_names)} duplicated id_name(s) in atlas"), flush=True)
    if not dup_names:
        return []

    # Map each duplicated id_name -> [atlas_id, ...] in one query.
    placeholders = ", ".join(["%s"] * len(dup_names))
    cand_rows = _run(
        f"SELECT atlas_id, id_name FROM atlas "
        f"WHERE id_name IN ({placeholders}) ORDER BY atlas_id",
        dup_names, fetch="all",
    ) or []
    cand_map = {}
    for aid, name in cand_rows:
        cand_map.setdefault(name, []).append(aid)

    # Of all the candidate atlas rows, find which ones are backed by F95
    # (source of truth). A valid match points at an F95-backed atlas row, so
    # those are NOT the problem and we don't want to review them. The suspect
    # rows are LC threads whose CURRENT atlas row has ONLY an lc_id and no
    # f95_id -- i.e. an LC-only duplicate that should have linked to the real
    # F95-backed sibling instead. One query over just the candidate ids.
    all_cand_ids = sorted({aid for ids in cand_map.values() for aid in ids})
    f95_backed = set()
    if all_cand_ids:
        ph2 = ", ".join(["%s"] * len(all_cand_ids))
        f95_rows = _run(
            f"SELECT atlas_id FROM f95_zone WHERE atlas_id IN ({ph2})",
            all_cand_ids, fetch="all",
        ) or []
        f95_backed = {r[0] for r in f95_rows}

    # LC rows whose current atlas row has one of those duplicated id_names.
    print(dim("  finding affected lewdcorner rows..."), flush=True)
    lc_rows = _run(
        f"""
        SELECT l.lc_id, l.atlas_id, a.id_name
        FROM lewdcorner l
        JOIN atlas a ON a.atlas_id = l.atlas_id
        WHERE a.id_name IN ({placeholders})
        """,
        dup_names, fetch="all", dict_cursor=True,
    ) or []

    out = []
    for r in lc_rows:
        ids = cand_map.get(r["id_name"], [])
        if len(ids) <= 1:
            continue
        # Only flag if this LC row's CURRENT atlas row is LC-only (not F95-
        # backed) AND at least one sibling candidate IS F95-backed -- meaning
        # there's a correct F95 target to move it to. If the current row is
        # already F95-backed, the match is valid; skip it.
        if r["atlas_id"] in f95_backed:
            continue
        if not any(aid in f95_backed for aid in ids):
            # No F95-backed candidate exists at all -- nothing authoritative
            # to relink to, so this isn't the case we're cleaning up here.
            continue
        out.append((r["lc_id"], r["atlas_id"], r["id_name"], ids))
    return out


def run_cleanup():
    flagged = _existing_multimatch_lc_rows()
    if not flagged:
        print(green("No existing lewdcorner rows have multi-match ambiguity. "
                    "Nothing to clean up."))
        return
    print(bold(f"Found {len(flagged)} lewdcorner row(s) with >1 atlas match.\n"))
    for n, (lc_id, cur_aid, id_name, cand_ids) in enumerate(flagged, 1):
        print("=" * 72)
        print(bold(f"[{n}/{len(flagged)}]  lc_id {lc_id}  "
                   f"(currently -> atlas_id {cur_aid})"))
        # Pull LC display info from the lewdcorner row.
        lc_row = _run(
            "SELECT site_url, banner_url FROM lewdcorner WHERE lc_id = %s LIMIT 1",
            (lc_id,), fetch="one",
        )
        cur = next((c for c in getAtlasRowsByIds([cur_aid])), {})
        print_lc(cur.get("title", ""), cur.get("creator", ""),
                 cur.get("version", ""),
                 (lc_row[0] if lc_row else ""),
                 (lc_row[1] if lc_row else ""))
        print()
        arows = {a["atlas_id"]: a for a in getAtlasRowsByIds(cand_ids)}
        for i, aid in enumerate(cand_ids, 1):
            marker = green("  <- current") if aid == cur_aid else ""
            print_candidate(i, arows.get(aid, {"atlas_id": aid}),
                            getAtlasSourceOwners(aid),
                            getAtlasSourceIds(aid))
            if marker:
                print(marker)
        print(dim("  [s]kip   [q]uit"))
        choice = _prompt({"s", "q"}, len(cand_ids))
        if choice == "q":
            print("Stopping.")
            return
        if choice == "s":
            print(dim("  skipped\n"))
            continue
        chosen = cand_ids[choice]
        if chosen != cur_aid:
            relinkLewdcornerAtlasId(lc_id, chosen)
            print(green(f"  repointed lc_id {lc_id} -> atlas_id {chosen}"))
        else:
            print(dim("  already pointing at the chosen atlas_id"))
        _safe_delete_candidates(chosen, cand_ids)
        print()
    print(green("Cleanup pass complete."))


# ----------------------------------------------------------------- queue job

def _resolve_queue_row(q):
    lc_id = q["lc_id"]
    cand_ids = [int(x) for x in (q.get("candidate_ids") or "").split(",") if x.strip()]
    # Re-derive candidates live so the queue survives atlas changes since it
    # was enqueued (rows may have been added/removed/fixed in the meantime).
    kind = q.get("match_kind") or "multi"
    if kind == "fuzzy":
        live = findFuzzyAtlasCandidates(q.get("short_name"), q.get("creator"))
    else:
        live = findAtlasIdsByIdName(q.get("id_name"))
    # Prefer live candidates; fall back to the stored snapshot.
    cand_ids = live or cand_ids

    print("=" * 72)
    print(bold(f"queue  lc_id {lc_id}   kind={kind}"))
    print_lc(q.get("title", ""), q.get("creator", ""), q.get("version", ""),
             q.get("site_url", ""), q.get("banner_url", ""))
    print()
    if not cand_ids:
        print(yellow("  No candidates remain (atlas may have changed). "
                     "You can create it as new."))
    else:
        arows = {a["atlas_id"]: a for a in getAtlasRowsByIds(cand_ids)}
        for i, aid in enumerate(cand_ids, 1):
            print_candidate(i, arows.get(aid, {"atlas_id": aid}),
                            getAtlasSourceOwners(aid),
                            getAtlasSourceIds(aid))
    print(dim("  [n]ew (create fresh atlas)   [s]kip   [d]ismiss   [q]uit"))
    choice = _prompt({"n", "s", "d", "q"}, len(cand_ids))

    if choice == "q":
        return "quit"
    if choice == "s":
        print(dim("  skipped (stays in queue)\n"))
        return "skip"
    if choice == "d":
        dequeueLcReview(lc_id)
        print(dim("  dismissed (removed from queue, no link made)\n"))
        return "dismiss"

    lc_payload = json.loads(q.get("lc_payload") or "{}")

    if choice == "n":
        atlas_payload = json.loads(q.get("atlas_payload") or "{}")
        atlas_payload.pop("atlas_id", None)
        new_aid = insertAtlas(atlas_payload)
        lc_payload["atlas_id"] = new_aid
        UpdatetableDynamic("lewdcorner", lc_payload)
        dequeueLcReview(lc_id)
        print(green(f"  created atlas_id {new_aid} and linked lc_id {lc_id}\n"))
        return "new"

    # Numeric: link to chosen candidate.
    chosen = cand_ids[choice]
    lc_payload["atlas_id"] = chosen
    UpdatetableDynamic("lewdcorner", lc_payload)
    dequeueLcReview(lc_id)
    print(green(f"  linked lc_id {lc_id} -> atlas_id {chosen}"))
    # For multi-match, optionally clean up orphaned duplicate atlas rows.
    if kind == "multi":
        _safe_delete_candidates(chosen, cand_ids)
    print()
    return "linked"


def run_queue(kind=None):
    rows = getLcReviewQueue(match_kind=kind)
    if not rows:
        print(green("Review queue is empty."
                    + (f" (kind={kind})" if kind else "")))
        return
    print(bold(f"{len(rows)} item(s) in review queue"
               + (f" (kind={kind})" if kind else "") + "\n"))
    for q in rows:
        if _resolve_queue_row(q) == "quit":
            print("Stopping.")
            return
    print(green("Queue pass complete."))


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="LewdCorner <-> atlas reconciler")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cleanup", help="fix existing mis-linked lewdcorner rows")
    qp = sub.add_parser("queue", help="resolve the ongoing review queue")
    qp.add_argument("--kind", choices=["multi", "fuzzy"], default=None)
    args = ap.parse_args()

    print(dim(f"DB: {config.env_status()}"))
    try:
        if args.cmd == "cleanup":
            run_cleanup()
        elif args.cmd == "queue":
            run_queue(kind=args.kind)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
