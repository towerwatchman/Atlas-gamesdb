# LewdCorner scraper — changes

Adds a LewdCorner source that consumes the `latest-updates.php?api=1&action=list`
JSON feed, de-dupes against existing games, and feeds new games into the same
`atlas` table the rest of the scraper uses.

## De-duplication rule (as requested)
For each game in the feed:
1. **`lc_id` already in `lewdcorner`** → update that atlas row + lc row in place.
2. **`id_name` already in `atlas`** (e.g. it came from F95) → **skip** — no duplicate,
   no `lewdcorner` row attached to the F95 game.
3. **Otherwise** → insert a new `atlas` row + a new `lewdcorner` row.

Cross-source matching uses the atlas `id_name`, computed the *same* way F95 does it
(`SHORTNAME_CREATOR`), so the same game on both sites collides on the key.

## Auth
LewdCorner is XenForo, like F95. `scraper/auth.py` was refactored into a shared
`XenForoSession` base; `F95Session` is unchanged in behaviour, and a new `LCSession`
adds the LewdCorner base URL + credentials. The feed is fetched through the
authenticated session via the new `get_json()` helper. The "api key/token" is the
same dummy-account session cookie model as F95 (cached in `lc_cookies.json`).

## Files changed / added
- `scraper/auth.py` — extracted `XenForoSession`; added `LCSession`; `get_json()`.
- `scraper/config.py` — `lc_user()`, `lc_password()`, `lc_cookie_file()`.
- `scraper/agents/lewdcorner.py` — **new** agent (feed walk, mapping, dedup).
- `scraper/datatypes/record.py` — `lcRecord()`.
- `scraper/tables/base.py` — expanded `lewdcorner` table: added `last_record_update`
  (the packager filters on it and it was missing), `thread_updated`, `tier`,
  `prefixes`, `downloads`.
- `scraper/utils/db.py` — `getAtlasIdByLcId()`.
- `scraper/utils/packager.py` — `lewdcorner` rows now included in the package + a
  `lewdcorner_backup_YYYYMMDD.json` backup.
- `api.py` — new positional flags: `lewdcorner` (arg 5) and `lc_full` (arg 6).
- `.env` — `LC_USER`, `LC_PASSWORD`, `LC_COOKIE_FILE`, `LC_DELAY_MIN/MAX`
  (fill in `LC_USER`/`LC_PASSWORD`; real DB/F95/FTP secrets were REDACTED in this
  copy — restore them).
- `scraper/fixtures/lewdcorner_list.json` — sample feed for the offline self-test.

## Field mapping (confirmed against the live sample)
| atlas / lc field | source |
| --- | --- |
| `lc_id` | `id` |
| `title` | `title` |
| `creator` / `developer` | `developer` |
| `version` | `version` |
| `engine` | derived from `badges` (Ren'Py/Unity/Unreal/RPGM/…) |
| `status` | derived from `badges` (Completed/Abandoned/OnHold) |
| `prefixes` | all `badges[].name`, comma-joined |
| `os` | `platforms` |
| `tags` | `tags` |
| `banner_url` | `image` |
| `screens` | `images[1:]` (image[0] duplicates the cover) |
| `views` / `likes` / `rating` | `view_count` / `like_score` / `rating` |
| `register_date` | `post_date` |
| `thread_updated` | `timestamp` (bumps on update; also the feed sort key) |
| `tier` | `is_premium` → "Premium"/"Free" |

## Running
```bash
# F95 only (default, unchanged):           python api.py
# LewdCorner incremental (stop-early):      python api.py false false false false true
# LewdCorner full crawl (every page):       python api.py false false false false true true
# F95 + LewdCorner + package:               python api.py true false false true true
```
Incremental stops once a feed page has nothing new/updated; full walks until the
feed's `hasMore` is false. Request pacing via `LC_DELAY_MIN`/`LC_DELAY_MAX`.

## Verified offline
`python -m scraper.agents.lewdcorner` runs the mapping self-test against the fixture.
A full dedup test (seed an F95 game → run the feed) confirmed: matching F95 title
skips, new titles insert, duplicate titles within a feed collapse to one atlas game,
and a second pass updates the LC-owned rows in place without creating duplicates.

## Still open (your call)
- **Skip vs. cross-link** for rule 2: currently skips F95-owned games entirely. If you
  ever want one atlas game to show both sources, the single `# DECISION POINT` block in
  `_process_item` is where to attach a `lewdcorner` row to the existing `atlas_id`.
- **Auth check on the live box:** confirm the dummy LC account can pull `api=1` (and that
  there's no Cloudflare/paid-tier gate). The sample you sent was logged-in; the agent
  assumes the cookie is required, same as F95.
