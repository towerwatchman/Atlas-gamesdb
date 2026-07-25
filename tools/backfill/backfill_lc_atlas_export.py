"""
One-time backfill for LewdCorner games that show as "LewdCorner #<lc_id>" in
the client.

Background
----------
The daily/base packager exports every table with
`WHERE last_record_update > start_time`. When a lewdcorner row is linked to an
existing atlas row WITHOUT that atlas row being rewritten, the lewdcorner row
exports (fresh timestamp) but the atlas row carrying the *title* does not (its
last_record_update is stale). The client then receives an LC record pointing at
an atlas_id it has no atlas_data row for, and falls back to displaying
"LewdCorner #<lc_id>".

The scraper/reconciler have been fixed to bump the atlas row on every LC link
(see touchAtlasRecord in scraper/utils/db.py), but that is forward-looking:
games that were ALREADY mis-synced still have a stale atlas timestamp and will
not self-heal on a normal daily run. This script fixes those existing rows by
bumping last_record_update on every atlas row that is currently linked from a
lewdcorner row, so the next package carries their titles down to clients.

It is safe to run repeatedly. It only touches atlas rows that are actually
referenced by a lewdcorner row.

Usage
-----
    python backfill_lc_atlas_export.py                 # dry run -- just counts
    python backfill_lc_atlas_export.py --apply         # bump timestamps
    python backfill_lc_atlas_export.py --apply --stale-only
        # only bump atlas rows whose last_record_update is OLDER than the
        # linked lewdcorner row's (the ones actually at risk of being missed),
        # rather than every linked atlas row.
"""

# --- run-from-anywhere bootstrap -------------------------------------------
# Allows `python tools/backfill/backfill_lc_atlas_export.py` as well as `python -m tools.backfill.backfill_lc_atlas_export`.
if __package__ in (None, ""):
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.abspath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
# ---------------------------------------------------------------------------
import sys
import time

from scraper.utils.db import _run


def _count_linked():
    row = _run(
        "SELECT COUNT(*) FROM atlas a "
        "JOIN lewdcorner l ON l.atlas_id = a.atlas_id",
        fetch="one",
    )
    return row[0] if row else 0


def _count_stale():
    """Atlas rows linked from LC whose atlas timestamp is behind the LC row --
    i.e. the ones a delta export would actually skip."""
    row = _run(
        "SELECT COUNT(*) FROM atlas a "
        "JOIN lewdcorner l ON l.atlas_id = a.atlas_id "
        "WHERE COALESCE(a.last_record_update, 0) < COALESCE(l.last_record_update, 0)",
        fetch="one",
    )
    return row[0] if row else 0


def _sample(stale_only, limit=10):
    where = (
        "WHERE COALESCE(a.last_record_update, 0) < COALESCE(l.last_record_update, 0)"
        if stale_only
        else ""
    )
    return _run(
        f"SELECT a.atlas_id, a.title, l.lc_id, "
        f"a.last_record_update AS atlas_ts, l.last_record_update AS lc_ts "
        f"FROM atlas a JOIN lewdcorner l ON l.atlas_id = a.atlas_id "
        f"{where} ORDER BY a.atlas_id LIMIT %s",
        (limit,), fetch="all", dict_cursor=True,
    )


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    apply = "--apply" in argv
    stale_only = "--stale-only" in argv

    linked = _count_linked()
    stale = _count_stale()
    target = stale if stale_only else linked

    print(f"atlas rows linked from lewdcorner : {linked}")
    print(f"  ...of which are stale (at risk) : {stale}")
    print(f"selected mode                     : "
          f"{'stale-only' if stale_only else 'all linked'} ({target} rows)")
    print()
    print("sample:")
    for r in _sample(stale_only):
        title = (r.get("title") or "")[:50]
        print(f"  atlas_id {r['atlas_id']:>7}  lc_id {r['lc_id']:>7}  "
              f"atlas_ts={r['atlas_ts']}  lc_ts={r['lc_ts']}  {title!r}")
    print()

    if not apply:
        print("DRY RUN -- nothing changed. Re-run with --apply to bump "
              "timestamps, then run the packager to publish a new update.")
        return

    now = int(time.time())
    if stale_only:
        result = _run(
            "UPDATE atlas a "
            "JOIN lewdcorner l ON l.atlas_id = a.atlas_id "
            "SET a.last_record_update = %s "
            "WHERE COALESCE(a.last_record_update, 0) < COALESCE(l.last_record_update, 0)",
            (now,), commit=True,
        )
    else:
        result = _run(
            "UPDATE atlas a "
            "JOIN lewdcorner l ON l.atlas_id = a.atlas_id "
            "SET a.last_record_update = %s",
            (now,), commit=True,
        )

    print(f"bumped last_record_update -> {now} on {target} atlas row(s).")
    print("Next step: run the packager (daily/base) so the touched atlas rows "
          "export and clients can resolve the titles.")


if __name__ == "__main__":
    main()
