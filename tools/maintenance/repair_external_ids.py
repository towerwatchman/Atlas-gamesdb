"""
Find atlas rows whose external_ids hold a URL ROUTE instead of an account id,
and (optionally) queue them to be re-scraped.

Why this exists
---------------
`_classify_external` captures the first path segment of a social/support URL as
the account id. When a platform introduces a new route prefix, that prefix gets
stored as the id for every thread using the new format. Patreon did exactly this
in 2024 by moving creator pages to `patreon.com/c/<creator>`, which wrote a
patreon id of "c" onto roughly 725 games.

The parser is fixed, but the already-stored values are still wrong, and the
correct slug cannot be recovered from the database -- only the parsed value was
kept, not the source URL. So the fix is to re-scrape the affected threads. This
tool finds them and puts them on `f95_refresh_queue`, which the existing
`f95_refresh_worker.py` drains at its normal pace with its normal retry
handling.

Usage
-----
    # report only (READ-ONLY, the default)
    python tools/maintenance/repair_external_ids.py

    # just patreon, and dump the list
    python tools/maintenance/repair_external_ids.py --platform patreon --csv bad.csv

    # queue every affected game for refresh
    python tools/maintenance/repair_external_ids.py --enqueue

    # queue the first 50, to sanity-check the worker before doing all of them
    python tools/maintenance/repair_external_ids.py --enqueue --limit 50

Notes
-----
  * Reporting never writes. `--enqueue` only inserts into f95_refresh_queue --
    it does not touch atlas or f95_zone. The worker does the actual fixing.
  * Rows with no f95_zone link (LewdCorner-only, DLsite-only) cannot be refreshed
    this way; they are reported separately.
  * Re-running is safe. enqueueF95Refresh() ignores an f95_id that already has a
    pending or processing request.
"""

# --- run-from-anywhere bootstrap -------------------------------------------
# Allows `python tools/maintenance/repair_external_ids.py` as well as
# `python -m tools.maintenance.repair_external_ids`.
if __package__ in (None, ""):
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.abspath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
# ---------------------------------------------------------------------------
import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict

from scraper.config import config
from scraper.agents.f95_detail import BAD_EXTERNAL_VALUES
from scraper.utils.db import _run, enqueueF95Refresh


def _c(code, s):
    return f"\033[{code}m{s}\033[0m"


def bold(s):
    return _c("1", s)


def red(s):
    return _c("31", s)


def yellow(s):
    return _c("33", s)


def dim(s):
    return _c("2", s)


def find_bad_rows(platforms=None):
    """Return rows whose external_ids contain a route name instead of an id.

    The JSON lives in a LONGTEXT column, so it's parsed in Python rather than
    with MySQL JSON functions -- the stored formatting has varied over time and
    a LIKE prefilter would miss rows.
    """
    wanted = {k: v for k, v in BAD_EXTERNAL_VALUES.items()
              if not platforms or k in platforms}

    rows = _run(
        """
        SELECT a.atlas_id, a.title, a.external_ids, f.f95_id
        FROM atlas a
        LEFT JOIN f95_zone f ON f.atlas_id = a.atlas_id
        WHERE a.external_ids IS NOT NULL AND a.external_ids <> ''
        ORDER BY a.atlas_id
        """,
        fetch="all", dict_cursor=True,
    ) or []

    bad = []
    unparseable = 0
    for row in rows:
        raw = row.get("external_ids")
        try:
            ext = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (ValueError, TypeError):
            unparseable += 1
            continue
        if not isinstance(ext, dict):
            continue

        hits = {}
        for kind, routes in wanted.items():
            value = ext.get(kind)
            if isinstance(value, str) and value.strip().lower() in routes:
                hits[kind] = value
        if hits:
            bad.append({
                "atlas_id": row["atlas_id"],
                "title": row.get("title") or "",
                "f95_id": row.get("f95_id"),
                "hits": hits,
                "external_ids": ext,
            })

    return bad, len(rows), unparseable


def report(bad, scanned, unparseable):
    print()
    print(bold(f"Scanned {scanned} atlas rows with external_ids."))
    if unparseable:
        print(yellow(f"  {unparseable} row(s) had unparseable external_ids JSON "
                     f"(skipped)."))
    if not bad:
        print(bold("No rows hold a route name instead of an account id."))
        return

    print(red(f"  {len(bad)} row(s) hold a URL route instead of an account id."))
    print()

    per_platform = defaultdict(Counter)
    for row in bad:
        for kind, value in row["hits"].items():
            per_platform[kind][value] += 1

    print(bold("By platform and stored value:"))
    for kind in sorted(per_platform):
        total = sum(per_platform[kind].values())
        print(f"  {kind:<14} {total:>5}")
        for value, count in per_platform[kind].most_common():
            print(f"      {value!r:<24} {count:>5}")
    print()

    refreshable = [r for r in bad if r["f95_id"]]
    orphans = [r for r in bad if not r["f95_id"]]
    print(f"{len(refreshable)} can be fixed by re-scraping F95.")
    if orphans:
        print(yellow(f"{len(orphans)} have no f95_zone row and cannot be "
                     f"refreshed this way:"))
        for row in orphans[:10]:
            print(dim(f"      atlas #{row['atlas_id']}  {row['title'][:52]}"))
        if len(orphans) > 10:
            print(dim(f"      ... and {len(orphans) - 10} more"))
    print()

    print(bold("Sample:"))
    for row in refreshable[:15]:
        hits = ", ".join(f"{k}={v!r}" for k, v in sorted(row["hits"].items()))
        print(f"  atlas #{row['atlas_id']:<7} f95 {row['f95_id']:<8} "
              f"{row['title'][:40]:<42} {hits}")
    if len(refreshable) > 15:
        print(dim(f"  ... and {len(refreshable) - 15} more"))
    print()


def write_csv(bad, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["atlas_id", "f95_id", "title", "platform",
                         "stored_value", "external_ids"])
        for row in bad:
            for kind, value in sorted(row["hits"].items()):
                writer.writerow([
                    row["atlas_id"], row["f95_id"] or "", row["title"],
                    kind, value,
                    json.dumps(row["external_ids"], ensure_ascii=False),
                ])
    print(f"Wrote {path}")


def enqueue(bad, limit=None, priority=50):
    refreshable = [r for r in bad if r["f95_id"]]
    if limit:
        refreshable = refreshable[:limit]
    if not refreshable:
        print("Nothing to enqueue.")
        return 0

    print(bold(f"Enqueuing {len(refreshable)} game(s) for refresh "
               f"(priority {priority})..."))
    queued = failed = 0
    for row in refreshable:
        try:
            enqueueF95Refresh(row["f95_id"], requested_by="repair_external_ids",
                              priority=priority)
            queued += 1
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(red(f"  f95 {row['f95_id']}: {exc}"))
        if queued % 50 == 0 and queued:
            print(dim(f"  ... {queued} queued"))

    print()
    print(bold(f"Queued {queued} game(s)."))
    if failed:
        print(red(f"{failed} failed to queue."))
    print("Start the refresh worker to process them:")
    print(dim("    python f95_refresh_worker.py --drain"))
    print(dim("  (or leave the daemon running; it picks them up on its own)"))
    return queued


def refetch_and_apply(bad, limit=None, apply=False, clear_all=False):
    """Re-read each affected game's page and write what it actually says.

    This is the one place allowed to CLEAR external_ids. The normal scraper
    deliberately won't: f95.py does

        ext = d.get("external_ids", {})
        if ext:
            atlas["external_ids"] = json.dumps(ext)

    and an empty dict is falsy, so a page carrying no external ids leaves the
    stored value untouched. That's right for a crawl -- a partial or rate-limited
    fetch must never blank good data -- but it also means a row flagged as a false
    positive can never be repaired by a refresh, because there is nothing on the
    page to overwrite it with.

    The safety rule that makes clearing acceptable here: the page must have been
    fetched AND parsed successfully. A failed fetch leaves the row alone. Without
    that distinction a transient 403 would wipe external ids across the library.
    """
    from scraper.agents.f95 import f95
    from scraper.auth import F95Session

    targets = [r for r in bad if r["f95_id"]]
    if limit:
        targets = targets[:limit]
    if not targets:
        print("Nothing to refetch (no rows with an f95_zone link).")
        return {}

    print(bold(f"{'Refetching' if apply else 'DRY RUN: refetching'} "
               f"{len(targets)} page(s)..."))
    if apply:
        print(yellow("  writes are ENABLED: a page with no external ids will "
                     "CLEAR the stored value."))
    print()

    agent = f95(F95Session())
    stats = Counter()

    for row in targets:
        atlas_id = row["atlas_id"]
        f95_id = row["f95_id"]
        stored = row["external_ids"]
        hits = ", ".join(f"{k}={v!r}" for k, v in sorted(row["hits"].items()))
        print(f"  atlas #{atlas_id} (f95 {f95_id}) {row['title'][:44]}")
        print(dim(f"      flagged: {hits}"))

        site_url = _site_url_for(f95_id)
        if not site_url:
            print(red("      no site_url on the f95_zone row; skipped"))
            stats["no_url"] += 1
            continue

        scratch_atlas, scratch_f95 = {}, {}
        try:
            ok = agent._fetch_detail(site_url, scratch_atlas, scratch_f95,
                                     retries=2)
        except Exception as exc:                       # noqa: BLE001
            print(red(f"      fetch raised: {exc}"))
            stats["failed"] += 1
            continue

        if not ok:
            # Deliberately no write. A failed fetch is indistinguishable from
            # "the page has nothing", and guessing wrong here destroys data.
            print(red("      fetch failed; leaving the row untouched"))
            stats["failed"] += 1
            continue

        raw = scratch_atlas.get("external_ids")
        found = {}
        if raw:
            try:
                found = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (ValueError, TypeError):
                found = {}

        if found:
            new_value = json.dumps(found, ensure_ascii=False)
            print(f"      page has: {', '.join(f'{k}={v}' for k, v in sorted(found.items()))}")
            action = "replace"
        elif clear_all:
            new_value = None
            print(yellow("      page has no external ids -> CLEARING the column"))
            action = "clear"
        else:
            # Default: drop only the flagged keys, keep anything else that was
            # already stored. A game can legitimately have a good discord id and
            # a bad patreon one.
            kept = {k: v for k, v in (stored or {}).items() if k not in row["hits"]}
            new_value = json.dumps(kept, ensure_ascii=False) if kept else None
            if kept:
                print(yellow(f"      page has no external ids -> dropping "
                             f"{', '.join(sorted(row['hits']))}, keeping "
                             f"{', '.join(sorted(kept))}"))
            else:
                print(yellow("      page has no external ids -> CLEARING "
                             "(nothing else was stored)"))
            action = "prune"

        if not apply:
            print(dim(f"      would {action} (dry run)"))
            stats[f"would_{action}"] += 1
            continue

        _run("UPDATE atlas SET external_ids = %s, last_record_update = %s "
             "WHERE atlas_id = %s",
             (new_value, int(time.time()), atlas_id), commit=True)
        # Bumping last_record_update is required, not cosmetic: without it the
        # corrected row never enters a delta package and clients keep the old
        # value indefinitely.
        print(f"      {action}d")
        stats[action] += 1

    print()
    print(bold("Summary: ") + ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    if not apply:
        print(dim("Dry run. Add --apply to write."))
    return stats


def _site_url_for(f95_id):
    row = _run("SELECT site_url FROM f95_zone WHERE f95_id = %s LIMIT 1",
               (f95_id,), fetch="one")
    if not row:
        return None
    return row[0] if isinstance(row, (list, tuple)) else row.get("site_url")

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Find external_ids holding a URL route instead of an id.")
    ap.add_argument("--platform", action="append", dest="platforms",
                    choices=sorted(BAD_EXTERNAL_VALUES),
                    help="Only this platform. Repeatable. Default: all.")
    ap.add_argument("--enqueue", action="store_true",
                    help="Queue affected games for refresh (writes to "
                         "f95_refresh_queue only).")
    ap.add_argument("--limit", type=int, default=None,
                    help="With --enqueue, only queue the first N.")
    ap.add_argument("--priority", type=int, default=50,
                    help="Queue priority; lower runs sooner (default 50).")
    ap.add_argument("--csv", dest="csv_path", default=None,
                    help="Also write every affected row to this CSV.")
    ap.add_argument("--refetch", action="store_true",
                    help="Re-read each affected game's page NOW and write what it "
                         "actually says. Unlike a normal refresh this may CLEAR "
                         "external_ids when the page carries none -- which is how "
                         "a false positive gets repaired. Dry run unless --apply.")
    ap.add_argument("--apply", action="store_true",
                    help="With --refetch, actually write.")
    ap.add_argument("--clear-all", action="store_true",
                    help="With --refetch, wipe the whole external_ids column when "
                         "the page has none, instead of dropping only the flagged "
                         "keys.")
    ap.add_argument("--atlas-id", type=int, action="append", dest="atlas_ids",
                    help="Only this atlas_id. Repeatable. Handy for fixing a "
                         "known handful.")
    args = ap.parse_args(argv)

    print(dim(f"DB: {config.env_status()}"))
    try:
        bad, scanned, unparseable = find_bad_rows(args.platforms)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
        return 1

    report(bad, scanned, unparseable)

    if args.csv_path and bad:
        write_csv(bad, args.csv_path)

    if not bad:
        return 0

    if args.atlas_ids:
        wanted = set(args.atlas_ids)
        bad = [r for r in bad if r["atlas_id"] in wanted]
        print(dim(f"Filtered to {len(bad)} row(s) by --atlas-id."))
        if not bad:
            print("None of those atlas ids are flagged.")
            return 0

    if args.refetch:
        try:
            refetch_and_apply(bad, limit=args.limit, apply=args.apply,
                              clear_all=args.clear_all)
        except (KeyboardInterrupt, EOFError):
            print("\nInterrupted.")
            return 1
        return 0

    if args.enqueue:
        try:
            enqueue(bad, limit=args.limit, priority=args.priority)
        except (KeyboardInterrupt, EOFError):
            print("\nInterrupted.")
            return 1
    else:
        print(dim("Read-only run. Re-run with --enqueue to queue these for "
                  "re-scraping."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
