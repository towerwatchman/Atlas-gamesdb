"""
Manually re-scan a SINGLE F95 game by its thread id and refresh ALL of its
DB data (requirement 3).

This is a thin wrapper around f95.refresh_one -- the same code path the
server refresh queue worker uses -- so a manual rescan and a queued rescan
behave identically. It fetches the game's actual F95 thread/games page fresh
and rewrites every field (tags, downloads, screens, overview, prefixes,
external ids, etc.), retrying the page fetch a couple of times so a transient
failure never wipes a good row down to listing-only data.

Usage:
    python refresh_game.py <f95_id> [<f95_id> ...]

Examples:
    python refresh_game.py 12345
    python refresh_game.py 12345 67890 24680
"""

# --- run-from-anywhere bootstrap -------------------------------------------
# Allows `python tools/refresh/refresh_game.py` as well as `python -m tools.refresh.refresh_game`.
if __package__ in (None, ""):
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.abspath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
# ---------------------------------------------------------------------------
import sys

from scraper.config import config
from scraper.utils.db import CreateDatabase
from scraper.auth import F95Session
from scraper.agents.f95 import f95


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2

    db_type = config.resolve_db_type()
    print(f"Running -> MySQL @ {config.host()}")
    print("  env:", config.env_status())
    CreateDatabase(db_type)

    agent = f95(F95Session())

    ok_count = 0
    fail = []
    for raw in argv:
        f95_id = str(raw).strip()
        if not f95_id.isdigit():
            print(f"skipping non-numeric id: {raw!r}")
            fail.append(raw)
            continue
        try:
            if agent.refresh_one(f95_id, db_type):
                ok_count += 1
            else:
                fail.append(f95_id)
        except Exception as ex:
            print(f"error refreshing {f95_id}:", ex)
            fail.append(f95_id)

    print(f"\nDone. refreshed={ok_count} failed={len(fail)}"
          + (f" ({', '.join(map(str, fail))})" if fail else ""))
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
