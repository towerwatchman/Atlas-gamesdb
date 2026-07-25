"""
One-time backfill for atlas rows that were written/linked WITHOUT bumping
atlas.last_record_update, so they fell out of the client's incremental export.

Background
----------
The daily/base packager exports every table with
`WHERE last_record_update > start_time`. Several source paths historically wrote
or linked an atlas row without stamping that timestamp:

  * dlsite agent   -> upserted the atlas row via UpdatetableDynamic("atlas", ...)
                      with no last_record_update.
  * cross-source   -> a new F95/Steam/dlsite id attached to an EXISTING atlas
                      row without the atlas row itself re-exporting.

The db layer has since been hardened: insertAtlas / updateAtlasById /
UpdatetableDynamic("atlas", ...) now auto-stamp last_record_update, so all
FUTURE writes export. This script fixes rows already left stale, which will not
self-heal until something touches them again.

What it does
------------
Bumps atlas.last_record_update on atlas rows that are "behind" a linked source
row that tracks its own timestamp (f95_zone, lewdcorner), i.e. rows a delta
export would skip even though newer source data exists. Optionally (--all-linked)
also bumps every atlas row referenced by dlsite/sxs, which never tracked a
timestamp at all and so can't be compared -- use that if dlsite/sxs games are
missing on clients.

Safe to run repeatedly. Read-only unless --apply is given.

Usage
-----
    python backfill_atlas_export.py                 # dry run -- counts only
    python backfill_atlas_export.py --apply         # bump stale (f95/lc) rows
    python backfill_atlas_export.py --apply --all-linked
        # also bump every dlsite/sxs-linked atlas row (no timestamp to compare)
"""

# --- run-from-anywhere bootstrap -------------------------------------------
# Allows `python tools/backfill/backfill_atlas_export.py` as well as `python -m tools.backfill.backfill_atlas_export`.
if __package__ in (None, ""):
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.abspath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
# ---------------------------------------------------------------------------
import sys
import time

from scraper.utils.db import _run


def _count_stale():
    """Atlas rows behind a timestamped source row (f95_zone or lewdcorner)."""
    row = _run(
        """
        SELECT COUNT(*) FROM atlas a
        WHERE EXISTS (
            SELECT 1 FROM f95_zone f
             WHERE f.atlas_id = a.atlas_id
               AND COALESCE(f.last_record_update, 0) > COALESCE(a.last_record_update, 0)
        )
        OR EXISTS (
            SELECT 1 FROM lewdcorner l
             WHERE l.atlas_id = a.atlas_id
               AND COALESCE(l.last_record_update, 0) > COALESCE(a.last_record_update, 0)
        )
        """,
        fetch="one",
    )
    return row[0] if row else 0


def _count_untimestamped_linked():
    """Atlas rows linked from dlsite/sxs (no source-side timestamp to compare)."""
    row = _run(
        """
        SELECT COUNT(*) FROM atlas a
        WHERE EXISTS (SELECT 1 FROM dlsite d WHERE d.atlas_id = a.atlas_id)
           OR EXISTS (SELECT 1 FROM sxs s WHERE s.atlas_id = a.atlas_id)
        """,
        fetch="one",
    )
    return row[0] if row else 0


def _sample():
    return _run(
        """
        SELECT a.atlas_id, a.title,
               a.last_record_update AS atlas_ts,
               (SELECT MAX(f.last_record_update) FROM f95_zone f WHERE f.atlas_id = a.atlas_id) AS f95_ts,
               (SELECT MAX(l.last_record_update) FROM lewdcorner l WHERE l.atlas_id = a.atlas_id) AS lc_ts
          FROM atlas a
         WHERE EXISTS (
                 SELECT 1 FROM f95_zone f
                  WHERE f.atlas_id = a.atlas_id
                    AND COALESCE(f.last_record_update, 0) > COALESCE(a.last_record_update, 0))
            OR EXISTS (
                 SELECT 1 FROM lewdcorner l
                  WHERE l.atlas_id = a.atlas_id
                    AND COALESCE(l.last_record_update, 0) > COALESCE(a.last_record_update, 0))
         ORDER BY a.atlas_id
         LIMIT 10
        """,
        fetch="all", dict_cursor=True,
    )


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    apply = "--apply" in argv
    all_linked = "--all-linked" in argv

    stale = _count_stale()
    linked = _count_untimestamped_linked()

    print(f"atlas rows behind a timestamped source (f95/lc) : {stale}")
    print(f"atlas rows linked from dlsite/sxs (no source ts) : {linked}")
    print(f"mode                                             : "
          f"{'stale + all-linked' if all_linked else 'stale only'}")
    print()
    print("sample of stale rows:")
    for r in _sample():
        title = (r.get("title") or "")[:50]
        print(f"  atlas_id {r['atlas_id']:>7}  atlas_ts={r['atlas_ts']}  "
              f"f95_ts={r['f95_ts']}  lc_ts={r['lc_ts']}  {title!r}")
    print()

    if not apply:
        print("DRY RUN -- nothing changed. Re-run with --apply to bump "
              "timestamps, then run the packager to publish a new update.")
        return

    now = int(time.time())

    # 1. Rows behind a timestamped source.
    _run(
        """
        UPDATE atlas a
           SET a.last_record_update = %s
         WHERE EXISTS (
                 SELECT 1 FROM f95_zone f
                  WHERE f.atlas_id = a.atlas_id
                    AND COALESCE(f.last_record_update, 0) > COALESCE(a.last_record_update, 0))
            OR EXISTS (
                 SELECT 1 FROM lewdcorner l
                  WHERE l.atlas_id = a.atlas_id
                    AND COALESCE(l.last_record_update, 0) > COALESCE(a.last_record_update, 0))
        """,
        (now,), commit=True,
    )
    print(f"bumped {stale} stale (f95/lc) atlas row(s) -> {now}.")

    # 2. Optionally, every dlsite/sxs-linked atlas row.
    if all_linked:
        _run(
            """
            UPDATE atlas a
               SET a.last_record_update = %s
             WHERE EXISTS (SELECT 1 FROM dlsite d WHERE d.atlas_id = a.atlas_id)
                OR EXISTS (SELECT 1 FROM sxs s WHERE s.atlas_id = a.atlas_id)
            """,
            (now,), commit=True,
        )
        print(f"bumped {linked} dlsite/sxs-linked atlas row(s) -> {now}.")

    print("Next: run the packager (daily/base) so the touched atlas rows export.")


if __name__ == "__main__":
    main()
