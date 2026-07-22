"""
Scan the database for F95 games that are missing tags and refresh them from
their actual F95 game/thread page (requirement 2).

These are typically games that landed with only listing-level data (title,
version, etc. from latest_data.php) but never had their game page crawled --
so tags/downloads/screens are empty. This finds every f95_zone row with a
blank tags column and does a FULL refresh of each (all fields, not just
tags), using the same single-game path as refresh_game.py and the server
refresh queue.

Pacing matches a normal scrape: the F95 per-request jitter (F95_DELAY_MIN/
MAX, default 2-4s) applies before each page fetch, so this is intentionally
slow and polite -- run it in the background.

Usage:
    python refresh_missing_tags.py [--limit N] [--dry-run]

    --limit N   only process the first N games missing tags (default: all)
    --dry-run   just list the games that WOULD be refreshed, fetch nothing
"""
import sys

from scraper.config import config
from scraper.utils.db import CreateDatabase, getF95IdsMissingTags
from scraper.auth import F95Session
from scraper.agents.f95 import f95


def _parse_args(argv):
    limit = None
    dry_run = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--dry-run":
            dry_run = True
        elif a == "--limit":
            i += 1
            if i >= len(argv) or not argv[i].isdigit():
                print("--limit requires a number")
                raise SystemExit(2)
            limit = int(argv[i])
        elif a in ("-h", "--help"):
            print(__doc__)
            raise SystemExit(0)
        else:
            print(f"unknown argument: {a!r}")
            print(__doc__)
            raise SystemExit(2)
        i += 1
    return limit, dry_run


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    limit, dry_run = _parse_args(argv)

    db_type = config.resolve_db_type()
    print(f"Running -> MySQL @ {config.host()}")
    print("  env:", config.env_status())
    CreateDatabase(db_type)

    ids = getF95IdsMissingTags(db_type)
    if limit is not None:
        ids = ids[:limit]

    print(f"Found {len(ids)} F95 game(s) missing tags"
          + (f" (limited to {limit})" if limit is not None else ""))
    if not ids:
        return 0

    if dry_run:
        for f95_id in ids:
            print("  would refresh f95_id", f95_id)
        print("\nDry run: nothing fetched.")
        return 0

    agent = f95(F95Session())
    ok_count = 0
    fail = []
    for n, f95_id in enumerate(ids, 1):
        print(f"[{n}/{len(ids)}] ", end="")
        try:
            if agent.refresh_one(f95_id, db_type):
                ok_count += 1
            else:
                fail.append(f95_id)
        except Exception as ex:
            print("error refreshing", f95_id, ":", ex)
            fail.append(f95_id)

    print(f"\nDone. refreshed={ok_count} failed={len(fail)}"
          + (f" ({', '.join(map(str, fail))})" if fail else ""))
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
