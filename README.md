# Atlas game-scraper

Scrapes game metadata from F95zone (and DLsite) into the Atlas database and
produces a downloadable update package.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in real values
```

`.env` holds all secrets and is git-ignored. Required keys:

| key | purpose |
| --- | --- |
| `DB_USER`, `DB_PASSWORD` | database login |
| `DB_MODE` | `remote` = always MySQL, `local` = always SQLite, `auto` = by OS |
| `DB_NAME`, `DB_HOST_LOCAL`, `DB_HOST_REMOTE` | database location |
| `F95_USER`, `F95_PASSWORD` | the **dummy** F95 account used to get a session cookie |
| `F95_COOKIE_FILE` | where the reusable cookie is cached (also git-ignored) |
| `PACKAGE_DIR_LOCAL`, `PACKAGE_DIR_REMOTE` | where packages are written |

> The DB password that used to be hard-coded in `config.py` should be
> rotated — it was committed in plaintext in the old version.

## Running

```bash
python api.py                       # scrape new/updated F95 threads, then package
python api.py true true             # re-fetch detail for EVERY thread (full)
python api.py false false false true  # skip sources, just rebuild the package
python backup.py                    # rebuild a full master package
```

`api.py` picks the database automatically: SQLite locally (Windows),
MySQL on the server (Linux). When the scrape finishes it builds the
downloadable package (`base`/`daily` `.update` files plus dated backups)
in the configured package directory.

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
