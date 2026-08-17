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
    REFRESH_INTERVAL      seconds between job starts (default 10)
    REFRESH_IDLE_SLEEP    seconds to wait when the queue is empty, daemon mode
                          (default 5)
    REFRESH_ERROR_SLEEP   seconds to back off after an unexpected loop error
                          (default 30)
    REFRESH_HEARTBEAT     seconds between "still idle" log lines (default 300,
                          0 disables)
    REFRESH_STALE_CLAIM   seconds after which a row left in 'processing' is
                          reclaimed at startup (default 900, 0 disables)
"""
import os
import sys
import time
import traceback

from scraper.agents import as_outcome
from scraper.config import config
from scraper.utils.db import (
    CreateDatabase,
    countPendingRefresh,
    getNextPendingRefresh,
    markRefreshProcessing,
    markRefreshResult,
    maxRefreshQueueId,
    reclaimStaleRefreshProcessing,
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


def _error_sleep():
    try:
        return float(os.environ.get("REFRESH_ERROR_SLEEP", "30"))
    except ValueError:
        return 30.0


def _heartbeat():
    try:
        return float(os.environ.get("REFRESH_HEARTBEAT", "300"))
    except ValueError:
        return 300.0


def _stale_claim_age():
    try:
        return float(os.environ.get("REFRESH_STALE_CLAIM", "900"))
    except ValueError:
        return 900.0


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
        result = as_outcome(agent.refresh_one(item_id, db_type))
        if result.ok:
            markRefreshResult(queue_id, True, db_type=db_type)
            print(f"   done queue_id={queue_id} source={source} id={item_id}"
                  f" ({result.code})")
        else:
            # Record the agent's OWN reason. Previously every failure -- a
            # transient 403, a mapped row with no stored URL, a deliberate
            # refusal to guess at a mapping -- was written as one hardcoded
            # string, so last_error told you nothing and the only real
            # explanation was a stdout line that had usually rotated away.
            markRefreshResult(queue_id, False,
                               error=f"[{result.code}] {result.message}",
                               db_type=db_type)
            print(f"   ERROR queue_id={queue_id} source={source} "
                  f"id={item_id}: {result.code}")
    except Exception as ex:
        markRefreshResult(queue_id, False, error=str(ex), db_type=db_type)
        print(f"   ERROR queue_id={queue_id} source={source} id={item_id}: {ex}")
    return True


def _log_idle(db_type, idle_seconds):
    """One line describing what the worker can currently SEE in the queue."""
    try:
        pending = countPendingRefresh(db_type)
        max_id = maxRefreshQueueId(db_type)
    except Exception as ex:
        print(f"queue empty; idle {idle_seconds}s (queue read failed: {ex})")
        return
    print(f"queue empty; idle {idle_seconds}s "
          f"(visible: pending={pending}, max_queue_id={max_id})")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    once = "--once" in argv
    drain = "--drain" in argv
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    # Line-buffer stdout. Under PM2 stdout is a pipe, so Python block-buffers
    # at ~8KB by default and the log lags reality by minutes -- which makes a
    # healthy worker and a wedged one look identical in `pm2 logs`. Set in code
    # rather than relying on PYTHONUNBUFFERED being present in the PM2 env.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    db_type = config.resolve_db_type()
    print(f"Running -> MySQL @ {config.host()}")
    print("  env:", config.env_status())
    CreateDatabase(db_type)

    interval = _interval()
    idle = _idle_sleep()
    error_sleep = _error_sleep()
    heartbeat = _heartbeat()
    agents = _build_agents()

    # Reclaim anything stranded in 'processing' by a previous crash/restart.
    # getNextPendingRefresh only selects 'pending', so without this those rows
    # are never retried. Safe here: this process has claimed nothing yet, so
    # any row still 'processing' past the age threshold is by definition dead.
    stale_age = _stale_claim_age()
    if stale_age > 0:
        try:
            reclaimed = reclaimStaleRefreshProcessing(stale_age, db_type)
            if reclaimed:
                print(f"reclaimed {len(reclaimed)} stale processing row(s) "
                      f"-> pending: {reclaimed}")
        except Exception as ex:
            print(f"warning: stale-claim sweep failed: {ex}")

    mode = "once" if once else ("drain" if drain else "daemon")
    print(f"Refresh worker started (mode={mode}, interval={interval}s/job, "
          f"idle={idle}s, sources={', '.join(sorted(agents))})")

    if once:
        did = _process_one(agents, db_type)
        if not did:
            print("queue empty; nothing to do")
        return 0

    # daemon / drain: pace by job START time so total throughput is exactly
    # one job per `interval`, no matter how long a refresh itself takes.
    idle_since = None
    last_beat = 0.0
    while True:
        started = time.monotonic()

        # A transient DB or agent failure must not take the process down. The
        # loop previously had no handler at all, so one raised exception
        # exited main() and left PM2 to restart from scratch -- stranding the
        # in-flight row in 'processing' every time.
        try:
            did = _process_one(agents, db_type)
        except Exception as ex:
            print(f"!! loop error: {type(ex).__name__}: {ex}")
            traceback.print_exc()
            time.sleep(error_sleep)
            continue

        if not did:
            if drain:
                print("queue drained; exiting")
                return 0
            # Idle heartbeat. An idle worker and a wedged one are otherwise
            # indistinguishable in the log -- both are silent. Reporting the
            # counts THIS CONNECTION can see also exposes a snapshot-pinned
            # read view: if max_queue_id stays frozen while the admin UI keeps
            # climbing, the worker is not idle, it is reading a stale view.
            now = time.monotonic()
            if idle_since is None:
                idle_since = now
                last_beat = now
                _log_idle(db_type, 0)
            elif heartbeat > 0 and (now - last_beat) >= heartbeat:
                last_beat = now
                _log_idle(db_type, int(now - idle_since))
            time.sleep(idle)
            continue

        idle_since = None

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
