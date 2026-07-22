"""
F95 refresh-queue worker (requirement 4).

The Node admin server enqueues an f95_id into the `f95_refresh_queue` table
(status='pending') whenever an admin asks for a game to be refreshed. THIS
worker is the consumer: it claims one pending row at a time (oldest / lowest
priority first), refreshes that game via the same single-game path as the
manual rescan (f95.refresh_one), and marks the row done or error.

Rate limit: at most ONE game every REFRESH_INTERVAL seconds (default 10),
measured between the START of consecutive jobs, so the queue drains at a
steady, polite ~6 games/minute regardless of how fast any one refresh runs.
(The F95 per-request jitter still applies on top, inside refresh_one.)

Run modes:
    python f95_refresh_worker.py           # long-running daemon (recommended:
                                           #   start once, leave running)
    python f95_refresh_worker.py --once    # process a single item then exit
                                           #   (for an external cron that ticks
                                           #    every 10s instead of a daemon)
    python f95_refresh_worker.py --drain   # process everything pending, then
                                           #   exit (still paced at 1/10s)

Env:
    REFRESH_INTERVAL   seconds between job starts (default 10)
    REFRESH_IDLE_SLEEP seconds to wait when the queue is empty, daemon mode
                       (default 5)
"""
import os
import sys
import time

from scraper.config import config
from scraper.utils.db import (
    CreateDatabase,
    getNextPendingF95Refresh,
    markF95RefreshProcessing,
    markF95RefreshResult,
)
from scraper.auth import F95Session
from scraper.agents.f95 import f95


def _interval():
    try:
        return float(os.environ.get("REFRESH_INTERVAL", "10"))
    except ValueError:
        return 10.0


def _idle_sleep():
    try:
        return float(os.environ.get("REFRESH_IDLE_SLEEP", "5"))
    except ValueError:
        return 5.0


def _process_one(agent, db_type):
    """Claim and process a single pending item. Returns:
        True  -> an item was processed (ok or error)
        False -> queue was empty (nothing to do)
    """
    item = getNextPendingF95Refresh(db_type)
    if not item:
        return False

    queue_id = item["queue_id"]
    f95_id = item["f95_id"]

    # Claim it (pending -> processing). If we didn't win the claim (another
    # worker, or it was cancelled), just move on.
    if not markF95RefreshProcessing(queue_id, db_type):
        print(f"queue_id {queue_id} was not claimable (status changed); skip")
        return True

    print(f"-> processing queue_id={queue_id} f95_id={f95_id} "
          f"(requested_by={item.get('requested_by')}, "
          f"attempt {item.get('attempts', 0) + 1})")
    try:
        ok = agent.refresh_one(f95_id, db_type)
        if ok:
            markF95RefreshResult(queue_id, True, db_type=db_type)
            print(f"   done queue_id={queue_id} f95_id={f95_id}")
        else:
            markF95RefreshResult(queue_id, False,
                                 error="refresh_one returned False "
                                       "(detail fetch failed)",
                                 db_type=db_type)
            print(f"   ERROR queue_id={queue_id} f95_id={f95_id} "
                  f"(detail fetch failed)")
    except Exception as ex:
        markF95RefreshResult(queue_id, False, error=str(ex), db_type=db_type)
        print(f"   ERROR queue_id={queue_id} f95_id={f95_id}: {ex}")
    return True


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    once = "--once" in argv
    drain = "--drain" in argv
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    db_type = config.resolve_db_type()
    print(f"Running -> MySQL @ {config.host()}")
    print("  env:", config.env_status())
    CreateDatabase(db_type)

    interval = _interval()
    idle = _idle_sleep()
    agent = f95(F95Session())

    mode = "once" if once else ("drain" if drain else "daemon")
    print(f"F95 refresh worker started (mode={mode}, "
          f"interval={interval}s/job)")

    if once:
        did = _process_one(agent, db_type)
        if not did:
            print("queue empty; nothing to do")
        return 0

    # daemon / drain: pace by job START time so total throughput is exactly
    # one job per `interval`, no matter how long a refresh itself takes.
    while True:
        started = time.monotonic()
        did = _process_one(agent, db_type)

        if not did:
            if drain:
                print("queue drained; exiting")
                return 0
            time.sleep(idle)
            continue

        # Pace to one job per interval, subtracting time already spent.
        elapsed = time.monotonic() - started
        remaining = interval - elapsed
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted; exiting")
