# Atlas game-scraper

Scrapes game metadata from F95zone (and DLsite) into the Atlas database and
produces a downloadable update package.

## Layout

```
api.py                  scrape + package        <- run by the server
backup.py               rebuild master package  <- run by the server
f95_refresh_worker.py   refresh-queue daemon    <- run by the server
scraper/                the scraper package
tools/
  backfill/             repair export timestamps (dry run unless --apply)
  diagnostics/          read-only inspection
  maintenance/          interactive / destructive fixes
  refresh/              single-game and bulk refresh
atlas_tools/            Windows desktop app (see docs/DESKTOP_APP.md)
build/                  PyInstaller spec + build_exe.bat
deploy/                 deploy.example.json
docs/                   DESKTOP_APP.md, DEPLOY.md, LEWDCORNER_CHANGES.md
scripts/                create_package.bat
server/admin/           Node admin app (its own README)
tests/
```

The three entry points the server runs stay at the root on purpose, so existing
cron/systemd/pm2 entries need no changes. Everything under `tools/` moved into
folders but **kept its filename**, so the only difference is the path:

```bash
python tools/diagnostics/find_duplicates.py --scope f95   # by path
python -m tools.diagnostics.find_duplicates --scope f95    # or as a module
```

Both work from the project root.

## Desktop app (Windows)

Rather than remembering each script's flags, there's a single window that runs
all of them, relays their interactive prompts, and pushes updates to the server:

```bash
python -m atlas_tools        # from a checkout
build\build_exe.bat          # build AtlasTools.exe
```

See **docs/DESKTOP_APP.md** to build it and **docs/DEPLOY.md** for deployment.

## Setup

```bash
pip install -r requirements.txt            # server / scraper
pip install -r requirements-desktop.txt    # plus the Windows app + deploy
cp .env.example .env                       # then fill in real values
```

> `pandas` was removed from `requirements.txt` -- nothing in the codebase
> imports it. It pulled in numpy and added ~50MB to the Windows build.

`.env` holds all secrets and is git-ignored. Required keys:

| key | purpose |
| --- | --- |
| `DB_USER`, `DB_PASSWORD` | database login |
| `DB_HOST` | MySQL host. **Set this explicitly** -- the old `DB_HOST_REMOTE`/`DB_HOST_LOCAL` split is gone (there's only one database now, so there's no "remote vs local" choice to make) |
| `DB_NAME` | database name |
| `F95_USER`, `F95_PASSWORD` | the **dummy** F95 account used to get a session cookie |
| `F95_COOKIE_FILE` | where the reusable cookie is cached (also git-ignored) |
| `PACKAGE_DIR` | where packages are written |

> The DB password that used to be hard-coded in `config.py` should be
> rotated — it was committed in plaintext in the old version.

> **There is no SQLite/local-DB mode anymore.** Every run -- dev box or
> server -- talks to the same MySQL database over `DB_HOST`. This used to
> be controlled by `DB_MODE`/`DB_HOST_LOCAL`/`DB_HOST_REMOTE`/`PACKAGE_DIR_LOCAL`;
> those are gone. If you have old values for `DB_HOST_REMOTE` or
> `DB_HOST_LOCAL` still set, `config.py` will fall back to them with a
> warning in the source, but you should set `DB_HOST` directly. (This also
> fixes a real bug: the old code always connected with `DB_HOST_REMOTE`
> regardless of `DB_MODE`, so a SQLite/local run silently never touched the
> value in `DB_HOST_LOCAL` at all -- and the SQLite path itself meant a
> `data.db` in whatever directory you ran from, which is **not** the same
> database as production. If atlas IDs look wrong/reset, that's almost
> certainly what happened on an earlier run.)

## Running

```bash
python api.py                          # scrape new/updated F95 threads, then package
python api.py true true                # re-fetch detail for EVERY thread (full)
python api.py true false false true false false true   # API-only sweep: new/missing games only
python api.py true false false true false false false true   # ts-only sweep: ts/listing fields, no detail pages ever
python api.py false false false true   # skip sources, just rebuild the package
python backup.py                       # rebuild a full master package
```

Or pick the same run modes from the desktop app's Run tab, which shows the
equivalent command line before it runs anything.

Positional flags to `api.py` (all `true`/`false`):

| # | flag | default | meaning |
| - | --- | --- | --- |
| 1 | `f95_enable` | `true` | scrape F95 |
| 2 | `f95_full` | `false` | re-fetch the detail page for every thread in the feed |
| 3 | `dlsite_enable` | `false` | scrape DLsite |
| 4 | `create_package` | `true` | build the downloadable package after scraping |
| 5 | `lc_enable` | `false` | scrape LewdCorner |
| 6 | `lc_full` | `false` | walk every LewdCorner feed page |
| 7 | `f95_new_only` | `false` | API-only sweep, missing games only (see below) |
| 8 | `f95_ts_only` | `false` | pure API sweep, never opens a detail page (see below) |

When the scrape finishes it builds the downloadable package (`base`/`daily`
`.update` files plus dated backups) in `PACKAGE_DIR`.

### F95 listing source

The F95 agent gets its listing from F95's own "latest updates" JSON feed
(`/sam/latest_alpha/latest_data.php`) instead of scraping the forum listing
HTML -- one fast request per page instead of parsing a full page of markup,
and it gives an accurate `ts` (last-activity timestamp) per thread that
replaces the unreliable "Thread Updated" label some devs forget to bump.
Detail pages (downloads, overview, external IDs, full tag list, etc.) are
still fetched per-thread through the authenticated session — the feed only
gives prefix/tag IDs, not names, so it can't replace that.

**Pacing**: the jitter delay (`F95_DELAY_MIN`/`F95_DELAY_MAX`) only ever
happens immediately before an actual detail-page fetch. Listing-page (API)
requests and any thread we skip because it's unchanged/already-known never
sleep — a pure-API pass runs back-to-back at API speed, and walking past
already-up-to-date games costs nothing but the DB lookup.

Four run modes (`scraper/agents/f95.py`):

- **Incremental** (default): walks the feed page by page; a thread gets a
  detail fetch if it's new OR its `ts` is newer than what we have stored.
  Stops early once a page has nothing to do, since the feed is
  newest-activity-first.
- **Full** (`f95_full=true`): re-fetches the detail page for every thread,
  no early stop.
- **New-only / API-only sweep** (`f95_new_only=true`): walks the *entire*
  feed (no early stop -- a brand-new thread can land anywhere in the
  activity-sorted order) but only triggers a detail fetch for threads we
  don't have a row for at all. Existing threads are left alone even if
  their `ts` shows newer activity. Use this to backfill games the
  incremental crawl missed without re-touching anything you already have.
- **Ts-only sweep** (`f95_ts_only=true`): the lightest mode -- walks the
  entire feed and, for any new-or-changed thread, stores only what the
  feed itself gives us (title, creator, version, views, likes, rating,
  cover, preview screenshots, and `ts`/`thread_updated`). **Never opens a
  detail page, for new games either** -- so it never sleeps at all. Use
  this to keep the whole catalog's listing-level metadata fresh quickly;
  follow it with an incremental or new-only run later to backfill full
  detail (downloads, overview, etc.) on whatever it found.

```bash
python api.py true false false true false false true    # new-only sweep
python api.py true false false true false false false true  # ts-only sweep
```

The Atlas client polls `https://<host>/api/updates`, compares the list to its
local update history, and downloads any newer `.update` files from
`/packages/`. That endpoint is a small PHP script on the web server that
selects the `updates` table live (see `server/` and the web-server note
below) — no database reader on the client.

## How login / cookie reuse works

F95 hides the data we need (download links, external store/ID links, and the
Genre/Changelog/Installation/Developer-Notes spoiler sections) from guests.
So thread **detail** pages are fetched through an authenticated session
(`scraper/auth.py`):

1. On first run it logs in with the dummy account and saves the cookie to
   `F95_COOKIE_FILE`.
2. Every later run reuses that cookie and only logs in again once it has
   expired — verified by the `data-logged-in` flag on each page.
3. If the session dies mid-run, it re-logs-in once and retries the request.

The forum **listing** is public and is fetched without auth.

## What the parser extracts

`scraper/agents/f95_detail.py` is a pure function over a thread's HTML, so it
is unit-tested against saved fixtures (`scraper/fixtures/`, exercised by
`tests/test_f95_detail.py`). From a logged-in page it pulls: title/prefixes,
overview, release date, version, OS, language, censored, rating/votes, the
full tag list, screenshots, cover, the spoiler sections, and external IDs.
The external IDs are stored as a single JSON column `external_ids` on the
`atlas` table — a flexible map rather than one column per platform — e.g.
`{"steam_appid": "1126320", "patreon": "DrPinkCake", "twitter": "DrPinkCake"}`.
Known keys: `steam_appid`, `steam_community`, `itch_url`, `vndb_id`,
`patreon`, `subscribestar`, `discord`, `gamejolt`, `twitter`. Whatever the
thread links is captured; absent platforms are simply omitted.

It also captures **downloads, patches, extras and translations** into four
separate JSON columns on `f95_zone` (each item in exactly one of them):

- `downloads` — game files. Everything in the download area defaults here; a
  link counts when its host is a file host, so it's captured whether or not
  the thread has a "DOWNLOAD" header.
- `patches` — update/incest/etc. patches. Detected by a "Patch" label or a
  group containing "patch" (they're often interleaved with game files), and
  captured even when they're F95 *thread* links rather than file hosts.
- `extras` — the `Extras` section: walkthroughs, mods, gallery unlocker,
  guides, banner/wallpaper packs. The `type` comes from the link text.
- `translations` — the `Translations` section.

Each entry is `{group, label, type, host, url, masked}`. `type` is a
normalised category (`game`, `patch`, `walkthrough`, `mod`, `translation`,
`save`, `gallery_unlock`, `cheat`, `soundtrack`, `wallpaper_art`, `guide`,
`other`). Screenshot/lightbox images are excluded from all four — they live
in `screens`.

### Masked links

F95 wraps many mirror links as `https://f95zone.to/masked/<host>/...`. The
token is **encrypted server-side and cannot be decoded offline**, so the
masked URL is stored verbatim with `"masked": true` and the real `host`
(e.g. `mega.nz`). To get the real destination, resolve it on demand with the
authenticated session:

```python
from scraper.auth import F95Session
session = F95Session()
real_url = session.resolve_masked(entry["url"])
```

`resolve_masked` makes one network request per call (it follows F95's
redirect), so resolve lazily when a user actually wants the link rather than
resolving every mirror on every scrape.

## Notable changes from the previous version

- Secrets moved out of `config.py` into `.env`.
- New `scraper/auth.py` (login + cookie persistence + liveness check).
- `f95.py` rebuilt to fetch detail pages authenticated and parse the two
  guest-gating structures; the parser is split into `f95_detail.py`.
- `db.py` collapsed to one connection helper, parameterised queries,
  whitelisted table names, fixed MySQL upsert placeholders.
- Packager/`directory_manager` paths unified via `config.package_dir`
  (they previously pointed at different folders).
- `ParseViews`/`ParseReplies` integer bug fixed.
- Removed dead files: `scraper_old.py`, `test/` (incl. the `engines/` lists,
  `blank.dll/.exe`, `dict_test.py`, `steamdb.py`), empty `steam.py`,
  unused `f95id.py`, and the committed `.vscode/`.

The `scraper/fixtures/*.html` files are saved F95 pages used only for tests;
delete them (and drop the `tests/` reference) if you don't want them in the repo.

## Request pacing

To avoid rate limiting, every F95 request (listing pages and per-thread detail
fetches) waits a randomised interval rather than a fixed cadence. Tune it in
`.env`:

```dotenv
F95_DELAY_MIN=2.0
F95_DELAY_MAX=4.0
```

Failed-listing retries use a fixed 10s backoff.

### Incremental runs

Skipped (unchanged) games incur **no delay** — the jitter only applies to
listing-page loads and to detail fetches that actually happen. On an
incremental run the crawl also **stops early** once it reaches a listing page
with nothing new/updated (the listing is newest-activity-first), so it doesn't
walk — or wait between — pages of already-current games. Use the full flag
(`python api.py true true`) to force a complete re-crawl.

## Web server: /api/updates endpoint

The client requests `/api/updates` (no extension). It's served by a PHP script
(`server/updates.php`) that returns the `updates` table as a JSON array of
`{date, name, md5}`. Database credentials for it live in `server/config.php`
using a read-only MySQL user, kept outside the web root. Apache maps the path:

```apache
Alias /api/updates /var/www/html/api/updates.php
<Directory /var/www/html/api>
    Require all granted
</Directory>
```
