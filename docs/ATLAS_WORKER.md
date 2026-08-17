# The Atlas worker

The admin portal's **F95 refresh** page lets an admin ask for a game to be
re-scraped. Pressing that button does not scrape anything — it inserts a row into
`f95_refresh_queue` with `status='pending'`. `f95_refresh_worker.py` is the
consumer that actually does the work. It runs under PM2 as `atlas-worker`.

If the worker isn't running, the queue silently fills up and nothing refreshes.
The page will happily keep accepting requests.

# The Atlas worker

The admin portal's **Refresh queue** page (and the "Queue refresh" button on a
game's Mapped sources panel) let an admin ask for a game to be re-scraped.
Pressing that button does not scrape anything — it inserts a row into
`f95_refresh_queue` with `status='pending'`. `f95_refresh_worker.py` is the
consumer that actually does the work. It runs under PM2 as `atlas-worker`.

If the worker isn't running, the queue silently fills up and nothing refreshes.
The page will happily keep accepting requests.

## Scope: F95 and LewdCorner. Anything past that needs a new agent branch.

**Originally F95-only**; LewdCorner refresh was added by generalizing the
existing table rather than standing up a second queue (migration 009).

- The queue table is still `f95_refresh_queue`, and its numeric-id column is
  still named `f95_id` — neither was renamed, since doing so touches every
  Python/Node file that reads them, for a purely cosmetic win. A `source`
  column (`'f95'` or `'lc'`) now distinguishes which agent a row belongs to;
  for a `source='lc'` row, the `f95_id` column holds an `lc_id`.
- `enqueue()` in `lib/f95Refresh.js` and `enqueueRefresh()` in
  `scraper/utils/db.py` both scope their "already queued" dedup check by
  `(source, id)` together — an `lc_id` that happens to numerically match a
  pending `f95_id` must not be treated as the same request.
- The worker (`_process_one` in `f95_refresh_worker.py`) reads `source` off the
  claimed row and dispatches to `f95.refresh_one()` or `lewdcorner.refresh_one()`
  accordingly. Each agent gets its own session (F95Session / LCSession), built
  once at startup in `_build_agents()`.
- **An unmapped `lc_id` is handled, but never blind-inserted.** F95 can safely
  find-or-create a game for an unseen `f95_id`, because the thread id maps 1:1
  with no ambiguity. An `lc_id` doesn't: the same LC thread may or may not
  correspond to an atlas row that already exists under a different site's
  spelling. So `lewdcorner.refresh_one()` routes an unmapped id through
  `_refresh_unmapped()`, which reuses `run()`'s matching rules:

  | Outcome | Action | `RefreshOutcome.code` |
  | --- | --- | --- |
  | exactly 1 exact `id_name` match | link, write the `lewdcorner` row | `linked` |
  | more than 1 exact match | `lc_review_queue`, kind `multi` | `queued_multi` |
  | fuzzy best above `LC_REVIEW_FLOOR` | `lc_review_queue`, kind `fuzzy` | `queued_fuzzy` |
  | nothing resembling it | `lc_review_queue`, kind `new` | `queued_new` |

  Note the last row: unlike `run()`, this path **never inserts a brand-new
  atlas row**. `run()` may, because it is working from LC's own listing feed
  and has seen the game in context; a refresh request is just an id somebody
  typed, and minting an atlas row from that shouldn't happen unlooked-at. The
  `new` kind is one the scraper itself never produces — the admin queue treats
  any non-`fuzzy` kind as an exact-`id_name` lookup, which correctly returns no
  candidates, so the reviewer is offered "create as new".

- **URL resolution for a bare `lc_id`.** LC thread URLs carry a title slug
  (`.../threads/eternum.555/`) which the queue never stores. `_resolve_site_url`
  fetches the bare `/threads/<id>/` form and follows XenForo's redirect to the
  canonical URL, keeping whatever it lands on rather than constructing one — so
  if LC ever stops honouring the short form this fails loudly (`url_unresolved`)
  instead of scraping a 404 page. The **F95 quick-add box** on the Refresh queue
  page is therefore no longer blocked on this; the page also still lists and
  filters LC rows (`?source=lc`).

- **Every `refresh_one` returns a `RefreshOutcome`, not a bool.** It carries
  `ok`, a stable `code`, and a human `message`, and is truthy on `ok` so
  existing `if agent.refresh_one(...)` callers in `tools/refresh/` are
  unaffected. The worker writes `[code] message` into
  `f95_refresh_queue.last_error`. Previously every failure — a transient 403, a
  mapped row with no stored URL, a deliberate refusal — was recorded as the one
  string `"refresh_one returned False (detail fetch failed, or not yet
  mapped)"`, so the queue row explained nothing and the only real diagnosis was
  a stdout line that had usually rotated away.

So a game with **no F95 thread and no LewdCorner thread** — DLsite-only,
SxS-only, or an atlas row created by hand — still cannot be queued for
refresh. There's no `dlsite`/`sxs` agent branch yet.

Adding a third source means: give it a `refresh_one(id, db_type)` method on its
agent (mirroring `lewdcorner.refresh_one` — decide up front whether an unseen
id can safely find-or-create, like F95, or has to be matched first, like LC;
return a `RefreshOutcome` either way),
add it to `_build_agents()` in the worker, add it to `REFRESH_SOURCES` in
`lib/f95Refresh.js`, and decide whether it gets its own quick-add box or relies
on SourcePanel like LC does. The process name won't need to change.


## How it's run

PM2, in daemon mode, on the scraper host.

| | |
| --- | --- |
| Script | `/home/atlas/svr/f95_refresh_worker.py` |
| Working dir | `/home/atlas/svr` |
| PM2 process | `atlas-worker` |
| Mode | daemon (default — no flags) |
| Pace | one game per 10s, measured job-start to job-start |
| Idle | sleeps 5s when the queue is empty, then re-checks |

Daemon mode is the intended way to run this. It paces itself, so it does **not**
want a cron schedule wrapped around it — see [Why not cron](#why-not-cron).

### First-time setup

```bash
cd /home/atlas/svr
pm2 start f95_refresh_worker.py --name atlas-worker --interpreter /home/atlas/svr/.venv/bin/python
pm2 save
```

Must match whatever `api.py`/`backup.py` use in cron, or the dependencies
installed for the scraper (`mysql-connector-python` etc.) won't be visible and
the process errors out immediately with `ModuleNotFoundError: No module named
'mysql'`. Confirm the venv path from the crontab if unsure:

```bash
crontab -l | grep -o '[^ ]*\.venv[^ ]*python'
```

`--interpreter python3` (bare, no path) only works if the scraper's
dependencies are installed system-wide, which is not the case on this host.
Check with `pm2 show atlas-worker | grep -i interpreter` if you're unsure what
it's currently running. `pm2 save` is what makes it come back after a reboot —
without it the process is lost on restart.

### Renaming an existing process

PM2 can't rename in place. Delete and re-add — the queue lives in MySQL, so
nothing is lost and any in-flight job just needs a Retry afterwards:

```bash
pm2 delete atlas-f95-worker
cd /home/atlas/svr
pm2 start f95_refresh_worker.py --name atlas-worker --interpreter /home/atlas/svr/.venv/bin/python
pm2 save
pm2 status atlas-worker
```

If a job was mid-flight when you deleted the old process, its row is stranded in
`processing` — see [rows stuck in `processing`](#known-gap-rows-stuck-in-processing).

### Day-to-day

```bash
pm2 status atlas-worker
pm2 logs atlas-worker            # live
pm2 logs atlas-worker --lines 200
pm2 restart atlas-worker
pm2 stop atlas-worker
```

Healthy startup looks like this:

```
Running -> MySQL @ <host>
  env: <env status>
Refresh worker started (mode=daemon, interval=10s/job, sources=f95, lc)
```

and then, per job:

```
-> processing queue_id=41 source=f95 id=93340 (requested_by=braden, attempt 1)
   done queue_id=41 source=f95 id=93340
```

### Tuning

Both are read from the environment at startup, so set them via PM2 and restart:

| Variable | Default | Meaning |
| --- | --- | --- |
| `REFRESH_INTERVAL` | `10` | seconds between job *starts* |
| `REFRESH_IDLE_SLEEP` | `5` | seconds to wait when the queue is empty |
| `REFRESH_ERROR_SLEEP` | `30` | backoff after an unexpected loop error |
| `REFRESH_HEARTBEAT` | `300` | seconds between idle heartbeat lines (`0` = off) |
| `REFRESH_STALE_CLAIM` | `900` | age at which a stranded `processing` row is reclaimed at startup (`0` = off) |
| `DB_CONNECT_TIMEOUT` | `15` | seconds before a MySQL connect/socket wait gives up |
| `XF_AUTH_TTL` | `1800` | seconds before a live forum session is re-verified (`0` = off) |
| `XF_REAUTH_COOLDOWN` | `300` | minimum gap between forced re-logins after a 401/403 |

```bash
pm2 restart atlas-worker --update-env
```

Don't lower `REFRESH_INTERVAL` much. F95 request jitter applies *inside*
`refresh_one` on top of this, and the 10s figure is deliberately polite.

## Deploys do not restart it

This is the one that will bite you. The worker is a long-running process holding
imported `scraper/` code in memory. Deploying new scraper code drops new `.py`
files on disk and the running worker **keeps executing the old ones** until it is
restarted.

The `python` deploy target now carries the restart in `post_commands`:

```json
"post_commands": [
  "pm2 restart atlas-worker"
]
```

`deploy/deploy.json` is gitignored, so this has to be applied to the real file
on whichever machine runs the deploy tool — `deploy.example.json` in the repo
only documents it. Until the real file has it, `pm2 restart atlas-worker` is a
manual step after any deploy touching `scraper/**` or `f95_refresh_worker.py`.
Skipping it does not just delay new code; it is what caused
[the snapshot stall](#the-snapshot-stall).

## LewdCorner support needs migration 009

If this deploy is updating an existing install rather than starting fresh, run
the migration that adds the `source` column before restarting the worker —
without it, every write to `f95_refresh_queue` (Node's enqueue, the worker's
claim/result updates) will fail with `Unknown column 'source'`:

```bash
mysql -u root -p games < server/admin/sql/009_refresh_queue_source.sql
```

It's idempotent, like 001–008 — safe to run again if unsure whether it already
applied. A fresh install via `scraper.tables.base` already includes the column.

## Files it needs on the host

Both resolve against the repo root (`config.app_root()`, derived from
`__file__`), **not** the working directory — so PM2's cwd doesn't matter:

- `/home/atlas/svr/.env` — DB credentials and F95 login. Never uploaded by the
  deploy tool; it lives only on the server.
- `/home/atlas/svr/f95_cookies.json` — cached F95 session. Written by the worker,
  so the PM2 user needs write permission on the repo root. If this isn't
  writable the worker logs in on every start instead of reusing the cookie.

## Verifying end to end

Queue something and watch it move — an F95 thread:

```bash
mysql -u root -p games -e \
  "INSERT INTO f95_refresh_queue (f95_id, source, status, priority, requested_by, requested_at)
   VALUES ('93340','f95','pending',100,'manual-test',UNIX_TIMESTAMP());"
```

...or any LewdCorner thread. An `lc_id` already mapped to an atlas row is
refreshed in place; an unmapped one is matched and either linked or parked in
`lc_review_queue` (see the scope section above), so check `last_error` for the
`[code]` prefix to see which happened:

```bash
mysql -u root -p games -e \
  "INSERT INTO f95_refresh_queue (f95_id, source, status, priority, requested_by, requested_at)
   VALUES ('555','lc','pending',100,'manual-test',UNIX_TIMESTAMP());"
```

```bash
mysql -u root -p games -e \
  "SELECT queue_id, f95_id, source, status, attempts, started_at, finished_at, last_error
     FROM f95_refresh_queue ORDER BY queue_id DESC LIMIT 5;"
```

`pending` → `processing` → `done` within ~10 seconds. The Refresh queue page's
summary cards read the same table, so it should show there too (filter by
source if it's not obvious which row is which).

## Rows stuck in `processing`

`getNextPendingRefresh` only selects `status='pending'` (regardless of
source), so a row left in `processing` by a worker that died mid-job — a
deploy, an OOM, a `pm2 restart` at the wrong moment — is not picked up again
by the normal claim path.

The worker now sweeps these at **startup**: anything still `processing` and
older than `REFRESH_STALE_CLAIM` (default 900s) is reset to `pending` and
logged. Since the process has claimed nothing at that point, any such row is
by definition dead. Set `REFRESH_STALE_CLAIM=0` to disable.

Rows stranded *while* the worker stays up are still manual: the **Retry**
button on the Refresh queue page resets the row to `pending`. To find strays:

```sql
SELECT queue_id, f95_id, source, attempts, FROM_UNIXTIME(started_at) AS started
  FROM f95_refresh_queue
 WHERE status = 'processing'
   AND started_at < UNIX_TIMESTAMP() - 900;
```


There is also no attempts cap, so a permanently broken thread can be retried
forever. Both are worth fixing properly (a stale-claim sweep at worker startup
plus a `MAX_ATTEMPTS` check) if this becomes a nuisance.

## Troubleshooting: queue has items but nothing is happening

Work through in order — each step isolates one failure mode.

**1. Is the process actually up?**

```bash
pm2 status atlas-worker
```
`errored` with a climbing restart count (↺) means it's crash-looping on
startup, before it ever gets to claim a row. Go straight to the logs.

**2. What do the logs say?**

```bash
pm2 logs atlas-worker --lines 100 --nostream
```

A healthy startup prints once:
```
Running -> MySQL @ <host>
  env: <status>
F95 refresh worker started (mode=daemon, interval=10s/job)
```
then one two-line block per job. If instead you see a traceback repeating on a
loop, the process is crashing on import, before touching the queue at all.

The one this has actually happened with:
```
ModuleNotFoundError: No module named 'mysql'
```
This means PM2's `--interpreter` doesn't have the scraper's dependencies
installed — almost always because it was started with a bare `python3` while
the scraper actually runs from a venv (check the crontab: if `api.py` /
`backup.py` are invoked via `.venv/bin/python`, the worker needs the same
interpreter). Fix:
```bash
pm2 delete atlas-worker
cd /home/atlas/svr
pm2 start f95_refresh_worker.py --name atlas-worker --interpreter /home/atlas/svr/.venv/bin/python
pm2 save
```
Rows already sitting `pending` need no manual requeue — they get picked up as
soon as the process starts cleanly.

**3. Logs are clean but nothing is processing — is it pointed at the right DB?**

The worker resolves `.env` from its own file location, independent of PM2's
working directory:
```bash
pm2 show atlas-worker | grep -i 'exec cwd\|script path'
cat /home/atlas/svr/.env | grep -E "DB_HOST|DB_NAME"
```
Confirm that matches what the admin server's `.env` uses. A worker quietly
polling the wrong database looks identical to an idle one — banner fine, no
job lines, no errors.

**4. Check what the queue rows actually say:**

```bash
mysql -u root -p games -e \
  "SELECT queue_id, f95_id, status, attempts, started_at, last_error FROM f95_refresh_queue ORDER BY queue_id;"
```
- `pending`, worker logs clean → give it one `REFRESH_INTERVAL` cycle, then
  re-check step 1.
- `processing` with a stale `started_at` → stranded by a crash/restart; see
  [known gap](#known-gap-rows-stuck-in-processing) below.
- `error` with something in `last_error` → that column says why, per row.

**5. Everything above checks out and it's still stuck:**

`pm2 status` showing long uptime with zero restarts and no new log lines is
the tell. Two distinct causes, and the queue rows tell them apart:

- A row in `processing` with a stale `started_at` → wedged inside a hung
  network call. `py-spy dump --pid $(pm2 pid atlas-worker)` shows the frame.
- Rows in `pending` with `attempts = 0` and nothing in `processing` → the
  worker never even tried to claim them. It is polling and being told the
  queue is empty. See [the snapshot stall](#the-snapshot-stall) below.

The idle heartbeat exists for exactly this. A healthy idle worker prints, every
`REFRESH_HEARTBEAT` seconds (default 300):

```
queue empty; idle 610s (visible: pending=0, max_queue_id=2246)
```

If `max_queue_id` stays frozen while the Refresh queue page shows higher ids,
the worker is not idle — it is reading a stale snapshot.

`pm2 restart atlas-worker` clears either; any in-flight row is reclaimed by the
startup sweep.

## The snapshot stall

Recorded because it cost 12 days of silently-dropped refreshes and looks like
nothing at all from the outside.

MySQL defaults to `REPEATABLE READ`. A transaction's read view is pinned at its
first read and does not advance until something commits. With `autocommit` off,
`getNextPendingRefresh`'s bare `SELECT` opens such a transaction. If the queue
happens to be empty at that instant it returns `None`, the worker goes to
`time.sleep(idle)`, and **nothing ever commits** — because commits only happen
inside `markRefreshProcessing` / `markRefreshResult`, neither of which is
reached without a claimed row. Every subsequent poll answers from the same
frozen view, so rows enqueued afterwards are permanently invisible. It is
self-locking: only dropping the connection clears it.

Symptoms: `pm2 status` online, long uptime, 0% CPU, no errors, no new log lines;
queue rows `pending` with `attempts = 0`; and one long-running transaction:

```sql
SELECT trx_id, trx_state, trx_started, trx_query, trx_mysql_thread_id
  FROM information_schema.INNODB_TRX;
```

`trx_state = RUNNING` with `trx_query = NULL` and a `trx_started` matching the
process start time is the signature.

Three things now prevent it, any one of which is sufficient:

- `autocommit=True` on the connection (each statement is its own transaction).
- `SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED` on connect — the
  correct level for a queue consumer, which has no use for a stable
  cross-statement snapshot.
- An explicit `rollback()` after every read-only `_run()`, releasing the read
  view even if the other two are somehow lost.

The original trigger was a deploy: `scraper/utils/db.py` gained `autocommit=True`
but the running worker kept the old module in memory for 12 days. See
[Deploys do not restart it](#deploys-do-not-restart-it) — now automated via the
`python` target's `post_commands`.

## Why not cron

Recorded so the decision isn't relitigated:

- **`--once` per minute is too slow.** Cron's floor is one minute; the worker
  paces at one game per 10 seconds. You'd get 1 game/min instead of 6, plus a
  full DB-connect and session-check cycle for each single game.
- **`--drain` on a schedule needs a lock.** Without `flock -n`, a drain that
  outlives its interval overlaps the next run. The DB claim
  (`markF95RefreshProcessing`) stops two workers taking the *same* row, but not
  both hammering F95 — which defeats the rate limit.
- **Crash recovery is worse.** Cron re-runs on the next tick and leaves the
  in-flight row stranded in `processing`. PM2 restarts immediately and, with
  `pm2 save`, survives reboots.

For reference, the cron form would have been:

```cron
*/5 * * * * cd /home/atlas/svr && /usr/bin/flock -n /tmp/atlas-worker.lock /usr/bin/python3 f95_refresh_worker.py --drain >> /var/log/atlas/f95-worker.log 2>&1
```

`--once` and `--drain` remain useful by hand — `--drain` is a good way to clear a
backlog after the worker has been down.
