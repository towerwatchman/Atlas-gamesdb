# The Atlas worker

The admin portal's **F95 refresh** page lets an admin ask for a game to be
re-scraped. Pressing that button does not scrape anything — it inserts a row into
`f95_refresh_queue` with `status='pending'`. `f95_refresh_worker.py` is the
consumer that actually does the work. It runs under PM2 as `atlas-worker`.

If the worker isn't running, the queue silently fills up and nothing refreshes.
The page will happily keep accepting requests.

## Scope: F95 threads only

The process name is deliberately generic, because this is the intended home for
any future on-demand refresh work. **Today it handles F95 only.** The whole path
is F95-specific:

- `enqueue()` in `lib/f95Refresh.js` rejects any non-numeric id and stores it as
  `f95_id`
- the queue table is `f95_refresh_queue`, keyed on `f95_id`
- the worker calls `refresh_one()` on `scraper.agents.f95`

So a game with **no F95 thread** — LewdCorner-only, DLsite-only, SxS-only, or an
atlas row created by hand in the admin tool — cannot be queued at all. There is no
`atlas_id` entry point and no LC/DLsite/SxS equivalent. In practice that covers
most of the library, since `f95_zone` is the dominant source, but it is not "any
game".

Adding another source later means a second queue table (or an added `source`
column on this one), a matching enqueue path in the admin server, and a branch in
`_process_one` to pick the right agent. The process name won't need to change
again when that happens.

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
F95 refresh worker started (mode=daemon, interval=10s/job)
```

and then, per job:

```
-> processing queue_id=41 f95_id=93340 (requested_by=braden, attempt 1)
   done queue_id=41 f95_id=93340
```

### Tuning

Both are read from the environment at startup, so set them via PM2 and restart:

| Variable | Default | Meaning |
| --- | --- | --- |
| `REFRESH_INTERVAL` | `10` | seconds between job *starts* |
| `REFRESH_IDLE_SLEEP` | `5` | seconds to wait when the queue is empty |

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

The `python` deploy target has an empty `post_commands`. Add the restart:

```json
"post_commands": [
  "pm2 restart atlas-worker"
]
```

Until that's in place, treat `pm2 restart atlas-worker` as a manual step after
any deploy that touches `scraper/**` or `f95_refresh_worker.py`.

## Files it needs on the host

Both resolve against the repo root (`config.app_root()`, derived from
`__file__`), **not** the working directory — so PM2's cwd doesn't matter:

- `/home/atlas/svr/.env` — DB credentials and F95 login. Never uploaded by the
  deploy tool; it lives only on the server.
- `/home/atlas/svr/f95_cookies.json` — cached F95 session. Written by the worker,
  so the PM2 user needs write permission on the repo root. If this isn't
  writable the worker logs in on every start instead of reusing the cookie.

## Verifying end to end

Queue something and watch it move:

```bash
mysql -u root -p games -e \
  "INSERT INTO f95_refresh_queue (f95_id, status, priority, requested_by, requested_at)
   VALUES ('93340','pending',100,'manual-test',UNIX_TIMESTAMP());"

mysql -u root -p games -e \
  "SELECT queue_id, f95_id, status, attempts, started_at, finished_at, last_error
     FROM f95_refresh_queue ORDER BY queue_id DESC LIMIT 5;"
```

`pending` → `processing` → `done` within ~10 seconds. The F95 refresh page's
summary cards read the same table, so it should show there too.

## Known gap: rows stuck in `processing`

`getNextPendingF95Refresh` only selects `status='pending'`. Nothing reclaims a
row left in `processing`, so if the worker dies mid-job — a deploy, an OOM, a
`pm2 restart` at the wrong moment — that row is stranded and will never be
retried.

It's recoverable by hand: the **Retry** button on the F95 refresh page resets the
row to `pending`. To find strays:

```sql
SELECT queue_id, f95_id, attempts, FROM_UNIXTIME(started_at) AS started
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

Possibly wedged inside a hung network call rather than crashed. `pm2 status`
showing long uptime with zero restarts and no new log lines is the tell.
`pm2 restart atlas-worker` is safe to try; any in-flight row will need a Retry
afterward.

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
