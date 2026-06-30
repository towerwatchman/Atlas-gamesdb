"""
Diagnostic: how many f95_zone rows still have thread_updated unset (NULL or
0)? If this is a large fraction of the table, that explains an incremental
run that never early-stops -- every one of those rows compares as "older"
than any real feed `ts`, so it looks changed every single time.

Usage:
    python check_thread_updated.py
"""
from scraper.utils.db import _run


def main():
    try:
        import sys
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    total = _run("SELECT COUNT(*) FROM f95_zone", fetch="one")[0]
    unset = _run(
        "SELECT COUNT(*) FROM f95_zone WHERE thread_updated IS NULL OR thread_updated = 0",
        fetch="one",
    )[0]

    print(f"f95_zone rows total:           {total}")
    print(f"thread_updated unset (0/NULL): {unset}")
    if total:
        print(f"percentage unset:               {unset / total * 100:.1f}%")

    print()
    print("Sample of 10 unset rows:")
    sample = _run(
        """
        SELECT f95_id, last_thread_comment, thread_updated, last_record_update
        FROM f95_zone
        WHERE thread_updated IS NULL OR thread_updated = 0
        LIMIT 10
        """,
        fetch="all",
    ) or []
    for f95_id, ltc, tu, lru in sample:
        print(f"  f95_id={f95_id}  last_thread_comment={ltc}  "
              f"thread_updated={tu}  last_record_update={lru}")

    print()
    print("Sample of 10 SET rows (for comparison):")
    sample2 = _run(
        """
        SELECT f95_id, last_thread_comment, thread_updated, last_record_update
        FROM f95_zone
        WHERE thread_updated IS NOT NULL AND thread_updated != 0
        LIMIT 10
        """,
        fetch="all",
    ) or []
    for f95_id, ltc, tu, lru in sample2:
        print(f"  f95_id={f95_id}  last_thread_comment={ltc}  "
              f"thread_updated={tu}  last_record_update={lru}")


if __name__ == "__main__":
    main()