"""
One-time backfill: re-export every atlas row that has admin manual links.

Why
---
Manual links live in atlas_manual_links and are overlaid into external_ids at
export time (see _merge_manual_links_into_external_ids). But the delta export
only includes atlas rows with last_record_update > start_time. Links added
before the "touch atlas on manual-link add" fix left their atlas row's timestamp
stale, so those rows are NOT in the delta -> the overlay never runs on them ->
the client never receives the linked ids (e.g. a browse game with 4 Steam ids
showing none).

This bumps last_record_update on every atlas row that has at least one manual
link, so the next delta package includes them (with the overlay applied). A full
`python backup.py` also fixes it (start_time=0 ignores timestamps), but this is
the surgical option that keeps the daily delta small.

Usage
-----
    python backfill_manual_links_export.py            # dry run -- count only
    python backfill_manual_links_export.py --apply    # bump the rows
"""

# --- run-from-anywhere bootstrap -------------------------------------------
# Allows `python tools/backfill/backfill_manual_links_export.py` as well as `python -m tools.backfill.backfill_manual_links_export`.
if __package__ in (None, ""):
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.abspath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
# ---------------------------------------------------------------------------
import sys
import time

from scraper.utils.db import _run


def _count():
    row = _run(
        """
        SELECT COUNT(DISTINCT a.atlas_id)
          FROM atlas a
          JOIN atlas_manual_links m ON m.atlas_id = a.atlas_id
        """,
        fetch="one",
    )
    return row[0] if row else 0


def _sample():
    return _run(
        """
        SELECT a.atlas_id, a.title, a.last_record_update AS ts,
               COUNT(m.link_id) AS links,
               SUM(m.kind = 'steam') AS steam_links
          FROM atlas a
          JOIN atlas_manual_links m ON m.atlas_id = a.atlas_id
         GROUP BY a.atlas_id, a.title, a.last_record_update
         ORDER BY links DESC, a.atlas_id
         LIMIT 15
        """,
        fetch="all", dict_cursor=True,
    )


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    apply = "--apply" in argv
    total = _count()
    print(f"atlas rows with manual links: {total}")
    print()
    print("sample (most links first):")
    for r in _sample():
        title = (r.get("title") or "")[:45]
        print(f"  atlas_id {r['atlas_id']:>7}  ts={r['ts']}  "
              f"links={r['links']}  steam={r['steam_links']}  {title!r}")
    print()

    if not apply:
        print("DRY RUN -- nothing changed. Re-run with --apply, then run the "
              "packager (or python backup.py for a full re-export).")
        return

    now = int(time.time())
    _run(
        """
        UPDATE atlas a
           JOIN (SELECT DISTINCT atlas_id FROM atlas_manual_links) ml
             ON ml.atlas_id = a.atlas_id
           SET a.last_record_update = %s
        """,
        (now,), commit=True,
    )
    print(f"bumped {total} atlas row(s) with manual links -> {now}.")
    print("Next: run the packager so these rows export with their links overlaid.")


if __name__ == "__main__":
    main()
