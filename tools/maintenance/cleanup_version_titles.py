"""
Bulk-delete every atlas row (and its linked lewdcorner row) whose title was
corrupted by the old LewdCorner title-parsing bug -- a literal " - Version:"
baked into the title itself, e.g. "Lust for Life - Version:".

This is the fast version: a handful of set-based SQL statements instead of
one-or-two round trips PER affected row (which is what made the earlier
merge-aware script slow on a large table). It does NOT try to detect/merge
F95 duplicates -- it just deletes. Since the F95-side parser is already
correct, a fresh F95 crawl will simply re-insert the correct atlas/f95_zone
row for any of these games that genuinely exist on F95 too, with a clean
title this time.

Safety:
  * Only touches atlas rows that are actually linked from `lewdcorner`.
  * Before deleting an atlas row, double-checks it isn't ALSO referenced by
    f95_zone / dlsite / sxs -- if it is, only the lewdcorner link is
    removed and the atlas row (and those other sources' data) is left
    alone, rather than deleting a row another source still needs.
  * Defaults to dry-run (just counts/prints); pass --apply to actually
    delete.

Usage:
    python cleanup_version_titles.py            # dry run -- just counts
    python cleanup_version_titles.py --apply     # actually deletes
"""

# --- run-from-anywhere bootstrap -------------------------------------------
# Allows `python tools/maintenance/cleanup_version_titles.py` as well as `python -m tools.maintenance.cleanup_version_titles`.
if __package__ in (None, ""):
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.abspath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
# ---------------------------------------------------------------------------
import sys

from scraper.utils.db import _run

# MySQL LIKE pattern for the corruption -- "- Version:" anywhere in the
# title, case-insensitive (MySQL's default collation is case-insensitive
# already for LIKE on most setups, but this is explicit just in case).
_BAD_TITLE_PATTERN = "%- Version:%"


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    apply = "--apply" in argv

    print("Finding affected rows...", flush=True)
    rows = _run(
        """
        SELECT a.atlas_id, a.title
        FROM atlas a
        JOIN lewdcorner l ON l.atlas_id = a.atlas_id
        WHERE a.title LIKE %s
        """,
        (_BAD_TITLE_PATTERN,), fetch="all",
    ) or []

    print(f"found {len(rows)} affected rows", flush=True)
    if not rows:
        print("Nothing to do.")
        return

    for atlas_id, title in rows[:20]:
        print(f"  atlas_id {atlas_id}: {title!r}")
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")
    print()

    if not apply:
        print(f"Dry run only -- re-run with --apply to delete these "
              f"{len(rows)} rows.")
        return

    atlas_ids = [r[0] for r in rows]

    # Split out the (hopefully rare) rows also referenced by another source
    # table -- those keep their atlas row, just lose the lewdcorner link.
    placeholders = ", ".join(["%s"] * len(atlas_ids))
    shared_ids = set()
    for tbl in ("f95_zone", "dlsite", "sxs"):
        try:
            found = _run(
                f"SELECT atlas_id FROM {tbl} WHERE atlas_id IN ({placeholders})",
                atlas_ids, fetch="all",
            ) or []
            shared_ids.update(r[0] for r in found)
        except Exception:
            pass  # table may not exist on a partial dev DB

    pure_lc_ids = [a for a in atlas_ids if a not in shared_ids]

    print(f"deleting lewdcorner links for all {len(atlas_ids)} rows...", flush=True)
    _run(f"DELETE FROM lewdcorner WHERE atlas_id IN ({placeholders})",
         atlas_ids, commit=True)

    if pure_lc_ids:
        ph2 = ", ".join(["%s"] * len(pure_lc_ids))
        print(f"deleting {len(pure_lc_ids)} now-orphaned atlas rows...", flush=True)
        _run(f"DELETE FROM atlas WHERE atlas_id IN ({ph2})",
             pure_lc_ids, commit=True)

    if shared_ids:
        print(f"left {len(shared_ids)} atlas rows in place (still referenced "
              f"by f95_zone/dlsite/sxs) -- only their lewdcorner link was removed")

    print(f"\nDone. Deleted {len(pure_lc_ids)} atlas rows and "
          f"{len(atlas_ids)} lewdcorner rows.")


if __name__ == "__main__":
    main()