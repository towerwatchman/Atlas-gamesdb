"""
Refresh-queue worker (requirement 4).

The Node admin server enqueues an item into the `f95_refresh_queue` table
(status='pending') whenever an admin asks for a game to be refreshed. THIS
worker is the consumer: it claims one pending row at a time (oldest / lowest
priority first), dispatches it to the agent matching that row's `source`
('f95' -> f95.refresh_one, 'lc' -> lewdcorner.refresh_one), and marks the row
done or error.

Runs under PM2 as `atlas-worker` (see docs/ATLAS_WORKER.md) -- the process
name is source-agnostic on purpose: adding a third source later means adding
an entry to _build_agents() below, not renaming anything.

Rate limit: at most ONE item every REFRESH_INTERVAL seconds (default 10),
measured between the START of consecutive jobs, so the queue drains at a
steady, polite ~6 items/minute regardless of how fast any one refresh runs,
regardless of source. (Each agent's own per-request jitter still applies on
top, inside refresh_one.)

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
    getNextPendingRefresh,
    markRefreshProcessing,
    markRefreshResult,
)
from scraper.auth import F95Session, LCSession
from scraper.agents.f95 import f95
from scraper.agents.lewdcorner import lewdcorner


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


def _build_agents():
    """One agent instance per source, each with its own session (so F95 and
    LewdCorner logins/cookies stay independent). Add a new source by adding
    a line here -- _process_one below needs no further changes."""
    return {
        "f95": f95(F95Session()),
        "lc": lewdcorner(LCSession()),
    }


def _process_one(agents, db_type):
    """Claim and process a single pending item. Returns:
        True  -> an item was processed (ok or error)
        False -> queue was empty (nothing to do)
    """
    item = getNextPendingRefresh(db_type)
    if not item:
        return False

    queue_id = item["queue_id"]
    item_id = item["f95_id"]
    source = item.get("source") or "f95"

    # Claim it (pending -> processing). If we didn't win the claim (another
    # worker, or it was cancelled), just move on.
    if not markRefreshProcessing(queue_id, db_type):
        print(f"queue_id {queue_id} was not claimable (status changed); skip")
        return True

    print(f"-> processing queue_id={queue_id} source={source} id={item_id} "
          f"(requested_by={item.get('requested_by')}, "
          f"attempt {item.get('attempts', 0) + 1})")

    agent = agents.get(source)
    if agent is None:
        # A row with a source no build of this worker recognises (typo, or an
        # admin server ahead of this deploy). Fail it loudly rather than
        # silently sitting on it forever or guessing an agent.
        markRefreshResult(queue_id, False,
                           error=f"unknown refresh source {source!r}",
                           db_type=db_type)
        print(f"   ERROR queue_id={queue_id}: unknown source {source!r}")
        return True

    try:
        ok = agent.refresh_one(item_id, db_type)
        if ok:
            markRefreshResult(queue_id, True, db_type=db_type)
            print(f"   done queue_id={queue_id} source={source} id={item_id}")
        else:
            markRefreshResult(queue_id, False,
                               error="refresh_one returned False "
                                     "(detail fetch failed, or not yet mapped)",
                               db_type=db_type)
            print(f"   ERROR queue_id={queue_id} source={source} id={item_id} "
                  f"(see log above for the reason)")
    except Exception as ex:
        markRefreshResult(queue_id, False, error=str(ex), db_type=db_type)
        print(f"   ERROR queue_id={queue_id} source={source} id={item_id}: {ex}")
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
    agents = _build_agents()

    mode = "once" if once else ("drain" if drain else "daemon")
    print(f"Refresh worker started (mode={mode}, interval={interval}s/job, "
          f"sources={', '.join(sorted(agents))})")

    if once:
        did = _process_one(agents, db_type)
        if not did:
            print("queue empty; nothing to do")
        return 0

    # daemon / drain: pace by job START time so total throughput is exactly
    # one job per `interval`, no matter how long a refresh itself takes.
    while True:
        started = time.monotonic()
        did = _process_one(agents, db_type)

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
