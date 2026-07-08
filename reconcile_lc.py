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

  3. DEFER (batch, non-interactive):
       python reconcile_lc.py defer --threshold 0.8
       python reconcile_lc.py defer --threshold 0.8 --dry-run
     Fast bulk triage. For every LC-only atlas row whose best fuzzy match to
     an F95-backed game scores >= threshold, parks the LC game in
     `lc_review_queue` (match_kind='fuzzy', full payload preserved), deletes
     the lewdcorner row, and deletes the now-orphaned LC-only atlas row. Never
     prompts and never touches rows below the threshold; resolve the parked
     items later with `queue`.

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
import difflib
import json
import re
import sys

from scraper.config import config
from scraper.utils.db import (
    _run,
    findAtlasIdsByIdName, findFuzzyAtlasCandidates,
    getAtlasRowsByIds, getAtlasSourceOwners, getAtlasSourceIds,
    getLcOnlyAtlasRows, getF95BackedAtlasRows,
    deleteAtlasById, relinkLewdcornerAtlasId,
    getLcIdByAtlasId, deleteLewdcornerByLcId, getLewdcornerRowByLcId,
    getLcReviewQueue, dequeueLcReview, enqueueLcReview,
    insertAtlas, UpdatetableDynamic,
)
import time

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


# ---------------------------------------------------- fuzzy cleanup job

def _norm(s):
    """Lowercase, strip all non-alphanumerics -> comparable key."""
    return re.sub(r"[\W_]+", "", (s or "").lower())


def _sim(a, b):
    """0..1 similarity between two strings (order-insensitive ratio)."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _score(lc_row, f95_row):
    """Combined title+creator similarity between an LC-only row and an F95
    candidate. Title weighted more heavily than creator (creators are often
    aliased/blank on one site). Returns 0..1."""
    t = _sim(lc_row.get("title"), f95_row.get("title"))
    c = _sim(lc_row.get("creator") or lc_row.get("developer"),
             f95_row.get("creator") or f95_row.get("developer"))
    # If either side has no creator, fall back to pure title similarity.
    if not _norm(lc_row.get("creator") or lc_row.get("developer")) or \
       not _norm(f95_row.get("creator") or f95_row.get("developer")):
        return t
    return 0.7 * t + 0.3 * c


def _rank_f95_candidates(lc_row, f95_pool, top=6, floor=0.55):
    """Return the best F95 candidates for one LC-only row as a list of
    (score, f95_row), highest first, above the floor."""
    scored = []
    lc_title_key = _norm(lc_row.get("title"))
    for fr in f95_pool:
        # cheap prefilter: require some title overlap before scoring
        ft = _norm(fr.get("title"))
        if not ft or not lc_title_key:
            continue
        if lc_title_key[:3] != ft[:3] and lc_title_key not in ft \
           and ft not in lc_title_key:
            # skip obviously-unrelated titles to keep it fast on big pools
            if _sim(lc_row.get("title"), fr.get("title")) < floor:
                continue
        s = _score(lc_row, fr)
        if s >= floor:
            scored.append((s, fr))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top]


def print_f95_candidate(idx, score, fr):
    print(f"  {bold('[' + str(idx) + ']')} "
          f"match {yellow(f'{score:.0%}')}  "
          f"atlas_id {yellow(str(fr.get('atlas_id')))}  "
          f"f95_id {cyan(str(fr.get('f95_id')))}")
    print(f"        title   : {_short(fr.get('title'))}")
    print(f"        creator : {_short(fr.get('creator'))}  "
          f"dev: {_short(fr.get('developer'), 30)}")
    print(f"        id_name : {dim(_short(fr.get('id_name')))}")


def _status_tag(status):
    """Short colored tag for the apply result, shown inline in auto lines."""
    if status == "dup_dropped":
        return yellow("[dup dropped]")
    return green("[linked]")


def run_fuzzy_cleanup(floor=0.55, auto=None):
    """Find every LC-only atlas row (no F95/dlsite/sxs backing) and fuzzy-
    match it against the F95-backed pool by title+creator. For each with
    plausible candidates, let the reviewer pick the correct F95 game; on
    selection, repoint the lewdcorner row to the F95-backed atlas_id and
    delete the now-orphaned LC-only atlas row.

    auto: if set (e.g. 0.9), any single candidate scoring >= auto with no
    close runner-up is applied automatically without prompting.
    """
    print(dim("  loading LC-only atlas rows..."), flush=True)
    lc_rows = getLcOnlyAtlasRows()
    print(dim(f"  {len(lc_rows)} LC-only atlas row(s)"), flush=True)
    print(dim("  loading F95-backed candidate pool..."), flush=True)
    f95_pool = getF95BackedAtlasRows()
    print(dim(f"  {len(f95_pool)} F95-backed atlas row(s)\n"), flush=True)

    if not lc_rows:
        print(green("No LC-only atlas rows. Nothing to do."))
        return

    fixed = auto_fixed = skipped = nomatch = dropped = 0
    for n, lc in enumerate(lc_rows, 1):
        cands = _rank_f95_candidates(lc, f95_pool, floor=floor)
        if not cands:
            nomatch += 1
            continue

        top_score, top_fr = cands[0]

        # ALWAYS auto-apply an exact, unambiguous match without prompting:
        # normalized title matches exactly and there is exactly one such
        # perfect candidate (no other candidate also at 100%). This is the
        # "obviously correct" case -- with ~1700 rows you don't want to
        # confirm each certainty by hand. A tie at 100% (two identical-title
        # F95 games) is NOT auto-applied; it falls through to manual review.
        perfect = [c for c in cands if c[0] >= 0.999]
        if len(perfect) == 1 and top_score >= 0.999:
            status = _apply_fuzzy_fix(lc, top_fr)
            print(green(f"[{n}/{len(lc_rows)}] EXACT 100% {_status_tag(status)} "
                        f"lc_id {lc['lc_id']}: {_short(lc['title'], 40)} "
                        f"-> atlas_id {top_fr['atlas_id']} "
                        f"(f95 {top_fr['f95_id']})"))
            if status == "dup_dropped":
                dropped += 1
            else:
                auto_fixed += 1
            continue

        # Optional softer auto-apply: confident top match, clear of runner-up.
        if auto is not None and top_score >= auto and (
                len(cands) == 1 or top_score - cands[1][0] >= 0.15):
            status = _apply_fuzzy_fix(lc, top_fr)
            print(green(f"[{n}/{len(lc_rows)}] AUTO {top_score:.0%} "
                        f"{_status_tag(status)} "
                        f"lc_id {lc['lc_id']}: {_short(lc['title'], 40)} "
                        f"-> atlas_id {top_fr['atlas_id']} "
                        f"(f95 {top_fr['f95_id']})"))
            if status == "dup_dropped":
                dropped += 1
            else:
                auto_fixed += 1
            continue

        print("=" * 72)
        print(bold(f"[{n}/{len(lc_rows)}]  LC-only atlas_id {lc['atlas_id']}  "
                   f"(lc_id {lc['lc_id']})"))
        print_lc(lc.get("title", ""), lc.get("creator", ""),
                 lc.get("version", ""), "", "")
        print(dim("  F95 candidates:"))
        for i, (score, fr) in enumerate(cands, 1):
            print_f95_candidate(i, score, fr)
        print(dim("  [s]kip   [q]uit"))
        choice = _prompt({"s", "q"}, len(cands))
        if choice == "q":
            print("Stopping.")
            break
        if choice == "s":
            skipped += 1
            print(dim("  skipped\n"))
            continue
        score, fr = cands[choice]
        status = _apply_fuzzy_fix(lc, fr)
        if status == "dup_dropped":
            print(green(f"  lc_id {lc['lc_id']} is a DUPLICATE of a game "
                        f"already linked to atlas_id {fr['atlas_id']} "
                        f"(f95 {fr['f95_id']}); dropped the duplicate LC row "
                        f"and orphaned atlas_id {lc['atlas_id']}\n"))
            dropped += 1
        else:
            print(green(f"  linked lc_id {lc['lc_id']} -> atlas_id "
                        f"{fr['atlas_id']} (f95 {fr['f95_id']}); "
                        f"deleted LC-only atlas_id {lc['atlas_id']}\n"))
            fixed += 1

    print(green(
        f"\nFuzzy cleanup: {auto_fixed} auto-applied (exact/confident), "
        f"{fixed} manually fixed, {dropped} duplicate LC rows dropped, "
        f"{skipped} skipped, "
        f"{nomatch} with no candidate above {floor:.0%}."))


def _apply_fuzzy_fix(lc, fr):
    """Attach this LewdCorner thread to the correct F95-backed atlas game.

    Two cases:
      A) The target F95 atlas row has NO lewdcorner row yet -> repoint this
         LC row onto it, then delete the orphaned LC-only atlas row.
      B) The target F95 atlas row ALREADY has a lewdcorner row (a different
         lc_id) -> lewdcorner.atlas_id is UNIQUE, so we can't point a second
         LC row at it. That means THIS thread is a duplicate LewdCorner entry
         for a game that's already correctly linked. We drop this duplicate
         lewdcorner row and its now-orphaned LC-only atlas row, leaving the
         existing correct link untouched.

    Returns a short status string for the caller's log/summary:
      'relinked'  -> case A
      'dup_dropped' -> case B
    """
    old_atlas_id = lc["atlas_id"]
    target_atlas_id = fr["atlas_id"]

    if old_atlas_id == target_atlas_id:
        return "noop"

    occupant = getLcIdByAtlasId(target_atlas_id)
    if occupant is not None and occupant != lc["lc_id"]:
        # Case B: target already linked by another LC thread -> this is a dup.
        deleteLewdcornerByLcId(lc["lc_id"])
        if not getAtlasSourceOwners(old_atlas_id):
            deleteAtlasById(old_atlas_id)
        return "dup_dropped"

    # Case A: safe to repoint.
    relinkLewdcornerAtlasId(lc["lc_id"], target_atlas_id)
    if not getAtlasSourceOwners(old_atlas_id):
        deleteAtlasById(old_atlas_id)
    return "relinked"


# ---------------------------------------------------- defer job (batch)

def _clean_payload(d):
    """Serialise-safe copy of a row dict: drop Nones, stringify anything the
    JSON encoder can't handle (e.g. Decimal). Mirrors the scraper's own
    _clean so the stored lc_payload matches what queue's [n]ew path expects."""
    out = {}
    for k, v in (d or {}).items():
        if v is None:
            continue
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = str(v)
    return out


def run_defer(threshold=0.8, floor=0.55, dry_run=False):
    """Batch, non-interactive triage.

    For every LC-only atlas row (linked to a lewdcorner row but backed by no
    authoritative source) whose BEST fuzzy match against the F95-backed pool
    scores >= threshold, we assume the LC-only atlas row is a duplicate of a
    real F95 game but we don't trust the match enough to auto-link it. So we:

      1. Park the LC game in lc_review_queue (match_kind='fuzzy') with its full
         lc_payload + atlas_payload + candidate atlas_ids, so it can be
         relinked or recreated later via `queue`.
      2. Delete the lewdcorner row (FK child) FIRST, then
      3. Delete the now-orphaned LC-only atlas row (only if no source owns it).

    Rows whose top match is below `threshold` are left completely untouched.
    This pass never prompts; use `cleanup`/`fuzzy` for interactive review.
    """
    print(dim("  loading LC-only atlas rows..."), flush=True)
    lc_rows = getLcOnlyAtlasRows()
    print(dim(f"  {len(lc_rows)} LC-only atlas row(s)"), flush=True)
    print(dim("  loading F95-backed candidate pool..."), flush=True)
    f95_pool = getF95BackedAtlasRows()
    print(dim(f"  {len(f95_pool)} F95-backed atlas row(s)\n"), flush=True)

    if not lc_rows:
        print(green("No LC-only atlas rows. Nothing to do."))
        return

    if dry_run:
        print(yellow(bold("  DRY RUN -- no changes will be written\n")))

    deferred = below = nocand = skipped_owned = 0
    for n, lc in enumerate(lc_rows, 1):
        cands = _rank_f95_candidates(lc, f95_pool, floor=floor)
        if not cands:
            nocand += 1
            continue
        top_score, top_fr = cands[0]
        if top_score < threshold:
            below += 1
            continue

        lc_id = lc["lc_id"]
        old_atlas_id = lc["atlas_id"]
        cand_ids = [c[1]["atlas_id"] for c in cands]

        line = (f"[{n}/{len(lc_rows)}] {yellow(f'{top_score:.0%}')} "
                f"lc_id {lc_id}: {_short(lc.get('title'), 40)} "
                f"~ atlas_id {top_fr['atlas_id']} (f95 {top_fr['f95_id']}) "
                f"{_short(top_fr.get('title'), 40)}")

        if dry_run:
            print(dim("[would defer] ") + line)
            deferred += 1
            continue

        # Build the queue row from the FULL lewdcorner record so `queue` can
        # recreate/relink later without re-scraping.
        lc_full = getLewdcornerRowByLcId(lc_id) or {"lc_id": lc_id,
                                                    "atlas_id": old_atlas_id}
        atlas_payload = _clean_payload(lc)
        atlas_payload.pop("atlas_id", None)
        atlas_payload.pop("lc_id", None)
        lc_payload = _clean_payload(lc_full)

        now = int(time.time())
        qrow = {
            "lc_id": lc_id,
            "title": lc.get("title") or "",
            "creator": lc.get("creator") or "",
            "version": lc.get("version") or "",
            "id_name": lc.get("id_name") or "",
            "short_name": lc.get("short_name") or "",
            "site_url": lc_full.get("site_url") or "",
            "banner_url": lc_full.get("banner_url") or "",
            "match_kind": "fuzzy",
            "candidate_ids": ",".join(str(c) for c in cand_ids),
            "lc_payload": json.dumps(lc_payload),
            "atlas_payload": json.dumps(atlas_payload),
            "last_seen": now,
            "first_seen": now,
        }
        enqueueLcReview(qrow)

        # FK child first, then the orphaned atlas parent.
        deleteLewdcornerByLcId(lc_id)
        owners = getAtlasSourceOwners(old_atlas_id)
        if owners:
            # Shouldn't happen for an LC-only row, but never delete a row an
            # authoritative source still references.
            skipped_owned += 1
            print(dim("[queued, kept atlas] ") + line
                  + dim(f"  (still owned by {', '.join(owners)})"))
        else:
            deleteAtlasById(old_atlas_id)
            print(green("[deferred] ") + line)
        deferred += 1

    verb = "would defer" if dry_run else "deferred"
    print(green(
        f"\nDefer pass: {deferred} {verb} (>= {threshold:.0%}), "
        f"{below} below threshold left in place, "
        f"{nocand} with no candidate above {floor:.0%}"
        + (f", {skipped_owned} queued but atlas kept (owned)"
           if skipped_owned else "")
        + "."))


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
    fp = sub.add_parser(
        "fuzzy",
        help="find LC-only atlas rows and fuzzy-match them to F95 games")
    fp.add_argument("--floor", type=float, default=0.55,
                    help="minimum title/creator similarity to show a "
                         "candidate (0-1, default 0.55)")
    fp.add_argument("--auto", type=float, default=None,
                    help="auto-apply a confident unambiguous match at/above "
                         "this score (e.g. 0.9); off by default")
    qp = sub.add_parser("queue", help="resolve the ongoing review queue")
    qp.add_argument("--kind", choices=["multi", "fuzzy"], default=None)
    dp = sub.add_parser(
        "defer",
        help="batch: park high-confidence LC-only rows in the review queue "
             "and delete their orphaned atlas rows (non-interactive)")
    dp.add_argument("--threshold", type=float, default=0.8,
                    help="minimum top-match score to defer a row "
                         "(0-1, default 0.8)")
    dp.add_argument("--floor", type=float, default=0.55,
                    help="minimum similarity to consider a candidate at all "
                         "(0-1, default 0.55)")
    dp.add_argument("--dry-run", action="store_true",
                    help="show what would be deferred without changing the DB")
    args = ap.parse_args()

    print(dim(f"DB: {config.env_status()}"))
    try:
        if args.cmd == "cleanup":
            run_cleanup()
        elif args.cmd == "fuzzy":
            run_fuzzy_cleanup(floor=args.floor, auto=args.auto)
        elif args.cmd == "queue":
            run_queue(kind=args.kind)
        elif args.cmd == "defer":
            run_defer(threshold=args.threshold, floor=args.floor,
                      dry_run=args.dry_run)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
