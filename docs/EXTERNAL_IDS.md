# external_ids: the route-name failure mode

This has now bitten twice, in the same way, on the same field. Worth writing
down.

## The shape of the bug

`_classify_external` in `scraper/agents/f95_detail.py` turns a URL into
`(kind, value)` with a regex per platform. For platforms whose account page is
just `host.com/<name>`, the pattern captures the first path segment:

```python
("patreon", r"patreon\.com/([\w-]+)")
```

That is correct right up until the platform introduces a new URL prefix. Then
the *prefix* is the first path segment, and it gets stored as the account id for
every thread using the new format. Nothing errors. Nothing looks wrong in the
logs. The field just quietly contains a word.

Two occurrences so far:

| When | Platform changed to | Stored id became |
| --- | --- | --- |
| earlier | `patreon.com/user?u=12345` | `"user"` |
| 2024 | `patreon.com/c/<creator>` | `"c"` (~725 games) |

The first fix added a negative lookahead for `user` only, so the second
occurrence sailed straight through.

## How it's guarded now

Reserved first-path segments live in one constant per platform
(`_PATREON_ROUTES`, `_FACEBOOK_ROUTES`, `_TWITTER_ROUTES`), the specific
prefixed forms are matched *before* the bare-slug pattern, and the bare-slug
pattern excludes every reserved word:

```python
("patreon", r"patreon\.com/(?:user|bePatron)\?u=(\d+)"),
("patreon", r"patreon\.com/cw?/([\w-]+)"),
("patreon", r"patreon\.com/(?:join|checkout)/([\w-]+)"),
("patreon", rf"patreon\.com/(?!(?:{_PATREON_ROUTES})(?:[/?]|$))([\w-]+)"),
```

Note the `(?: ... )` around the route list. Without it, `|` binds looser than
the trailing `(?:[/?]|$)` and the lookahead rejects any slug that merely
*starts* with a reserved word — so `patreon.com/coolgamedev` silently stops
being captured. `tests/test_f95_detail.py::test_classify_external_url_shapes`
pins exactly that case.

All forms normalise to the bare slug, so a thread that switched from
`patreon.com/Caribdis` to `patreon.com/c/Caribdis` keeps the same stored value.

## Finding it if it happens again

```bash
python tools/maintenance/repair_external_ids.py
```

Read-only. It reports any row whose stored id is a known route name, grouped by
platform and value, and separates out the rows with no `f95_zone` link (which
can't be fixed by re-scraping F95).

`BAD_EXTERNAL_VALUES` is derived from the same route constants the regexes use,
and `test_bad_external_values_matches_the_patterns` asserts the two can't drift
apart — if a value is listed as a route, the classifier must actually reject it.

## Repairing the stored rows

The correct slug **cannot** be recovered from the database. Only the parsed value
was ever stored, not the source URL. So affected threads have to be re-scraped:

```bash
python tools/maintenance/repair_external_ids.py --enqueue --limit 50   # try 50
python f95_refresh_worker.py --drain
python tools/maintenance/repair_external_ids.py                        # re-check
python tools/maintenance/repair_external_ids.py --enqueue              # the rest
```

`--enqueue` only inserts into `f95_refresh_queue`; the existing worker does the
actual re-scrape at its normal pace with its normal retry handling. Re-running is
safe — `enqueueF95Refresh` ignores an f95_id that already has a pending request.

At F95's request pacing, ~725 games is a long run. Leave the daemon going rather
than waiting on `--drain`.

Afterwards the affected `atlas` rows get a new `last_record_update`, so they flow
into the next delta package on their own.

## The other failure mode: ids that aren't in an `<a href>`

The route-name bug above is about parsing a URL wrongly. This one is about never
seeing the URL at all.

External ids were originally collected only from anchor tags:

```python
for a in scope.find_all("a", href=True):
```

F95 threads also embed the **Steam store widget**, which is an `<iframe>`, so it
was invisible to that loop. Two further wrinkles:

* XenForo renders media embeds through s9e, which loads them lazily. The real
  `src` is assigned by JS at view time, so server-rendered and saved markup keep
  the URL in `data-s9e-mediaembed-src` and have no usable `src` at all:

  ```html
  <iframe data-s9e-mediaembed="steamstore"
          data-s9e-mediaembed-src="//store.steampowered.com/widget/3291310">
  ```

* The widget path is `/widget/<appid>`, not `/app/<appid>`, so even the URL on
  its own wouldn't have matched the existing Steam pattern.

`_embed_url()` handles the attribute precedence and normalises protocol-relative
URLs, and the embed scan runs *after* the anchor scan so an explicit link always
wins for the same platform.

### Scope still applies

Embeds are scanned within `external_scopes` (the opening post, plus support
widgets whose author matches the credited developer) — not the whole page. Hard
Lessons has a Steam widget in a *reply* from another member; that is not the
game's store page and is correctly ignored. `test_steam_widget_embed_captured`
and `test_steam_widget_in_a_reply_is_ignored` pin both halves.

### Not every Steam route is an app

`store.steampowered.com` also serves `/curator/<id>`, `/bundle/<id>`, `/sub/<id>`
and `/developer/<name>`. Mutant College credits its developer with a curator
link right next to the Developer label, so a generic
`steampowered\.com/\w+/(\d+)` pattern would store the curator id as the game's
appid. Both Steam patterns are deliberately explicit about the route.

### Backfilling

A newly-parseable field only appears on rows that get re-scraped. There is no way
to tell which threads have a Steam widget without fetching them, so the options
are a full re-crawl, or enqueueing the games that currently have no
`steam_appid` (the only ones that could gain one):

```sql
SELECT COUNT(*) FROM atlas a
JOIN f95_zone f ON f.atlas_id = a.atlas_id
WHERE a.external_ids IS NULL
   OR a.external_ids NOT LIKE '%steam_appid%';
```

## Adding a new platform

1. Put the specific prefixed forms *before* the bare-slug pattern.
2. Wrap any route alternation in `(?: ... )`.
3. Add a `_<PLATFORM>_ROUTES` constant and an entry in `BAD_EXTERNAL_VALUES` so
   the repair tool can spot bad rows later.
4. Add cases to `CLASSIFY_CASES`, including at least one legitimate slug that
   begins with a reserved word.

## LewdCorner thread scraping

`scraper/agents/lc_detail.py` is the LewdCorner counterpart to `f95_detail.py`.
It shares `_classify_external` and `_embed_url`, so a fix to either applies to
both sites.

Four things about LC markup that are easy to get wrong, and silent when you do:

**1. The opening post is not the first `div.bbWrapper` on the page.** XenForo
renders the poster's signature/about block inside the user cell, which comes
first in document order. On real threads the first two wrappers were the
author's social links and project name; the actual post was the third. The body
is located by `article.message--post` → `article.message-body` → `div.bbWrapper`.
Taking the first match gives you a signature and an empty overview.

**2. The real image is in the anchor, not the `<img>`.**

```html
<a href="https://lewdcorner.com/attachments/6236382_takeru-jpg.796466/" class="js-lbImage">
  <img src="https://lewdcorner.com/data/attachments/793/793139-....jpg?hash=...">
</a>
```

The `<img src>` is a generated ~267px thumbnail; the full-size original is the
anchor's `href`. Reading `img.src` works and silently collects thumbnails —
which is what the API already gave us, so the page fetch would buy nothing. The
thumbnail is still recorded as `thumb`, just not as the image.

The banner is the single `div.bbImageWrapper[data-src]` at the top of the post,
and is de-duplicated against the screenshot list by attachment id.

**3. Download links are masked.** Hosts are wrapped as
`/masked/out?t=<token>&r=<base64 referrer>`, where the token is JWT-shaped:
`<base64url payload>.<signature>`. The payload decodes to `{"u": "<real url>"}`.
Decoding is local — no request, and the signature is ignored, since we're reading
a URL rather than trusting a claim. Without this every download's host comes out
as `lewdcorner.com`.

**4. LC has no `Developer:` / `Version:` labels.** F95 threads carry an inline
field list; LC threads only have `Overview:` and `DOWNLOAD ...` headings. Version
and developer come from the trailing bracket groups in the title, the same
fallback `f95_detail` uses. Category/engine/status come from the prefix chips.

Two smaller traps, both covered by tests:

* `h1.p-title-value` contains a FontAwesome thread-type icon whose `<title>`
  reads "discussion". `get_text()` pulls it in, so every title parsed as
  `"discussion Bright Past [v1.006] [Kosmos Games]"`.
* `next_elements` walks *into* the `<b>Overview:</b>` label, so its own text was
  captured and every overview began with a duplicated heading. One fixture also
  repeats the heading as plain text in the post itself, which is in the source
  but isn't part of the description.

### The custom-field block is where the metadata actually lives

LewdCorner keeps its structured game data in XenForo custom thread fields,
rendered above the opening post:

```html
<div class="message-fields message-fields--before">
  <dl class="pairs pairs--customField" data-field="Developer">
    <dt>Developer Name</dt><dd>Xlab</dd>
  </dl>
  <dl class="pairs pairs--customField" data-field="donations">
    <dt>Developer Links</dt><dd><div class="bbWrapper">
      <a href="https://www.patreon.com/badhero">Patreon</a> - ...
    </div></dd>
  </dl>
  ...
```

`extract_fields()` reads the whole block keyed by `data-field`:

| `data-field` | Becomes |
| --- | --- |
| `Developer` | `developer` (and `creator`) |
| `version` | `version` |
| `Language` | `language` |
| `OS` | `os` (list, from the `<li>` items) |
| `dategamerelease` | `release_date` (epoch) |
| `dateversionrelease` | `latest_update` (epoch) |
| `donations` | `external_ids` — **the** source for support links |
| `othergames` | `other_games` |

Unrecognised fields are kept under their own lowercased key rather than dropped,
so a field LC adds later still appears in the parsed output.

This is why body-only parsing produced an empty `external_ids` on every sample:
the developer's Patreon/Discord/Twitter links are in the `donations` field, not
the post. Parsing Eternum's block yields exactly what production already holds
for it — `patreon: onceinalifetime`, `subscribestar: caribdis`,
`itch_url: caribdis.itch.io`, `discord: caribdisgames`,
`twitter: Caribdis_games`.

Three things to know:

* **The version field goes stale.** On the Eternum fixture the field reads
  `0.9.0` while the title reads `v0.9.5 Public` — posters update the title on
  every release and sometimes forget the field. Both are kept
  (`version_field` / `version_title`), `version_mismatch` is set, and the
  scraper logs the disagreement. The field currently wins; flipping that is a
  one-line change now that both values are carried.
* **Long language lists are truncated at source**, e.g.
  `"English, French, Italian, German, Spanish, +6"`. The missing entries are not
  elsewhere on the page.
* **Dates need their own parser.** LC renders them as `"Jul 26, 2026"`, and
  `scraper.utils.epoch.ConvertToUnixTime` returns `0` for that format, so
  `parse_lc_date()` handles it.

### When the page is fetched

Mirrors the F95 agent, wired into all three write paths in `lewdcorner.py`:

| Case | Page fetched? |
| --- | --- |
| New game | Always — the listing has no overview, tags, downloads or full-size images, and nothing later comes back to fill them in |
| Known thread, `thread_updated` newer | Yes — a version bump means new download links |
| Known thread, unchanged | No (unless `full=True`) |
| Linked to an existing atlas row | Yes — the atlas row is another source's, but the lewdcorner row still needs its own banner/screens/downloads |
| `full=True` | Every page of the feed, and every game's thread page |

Paced by `_jitter()` (`LC_DELAY_MIN` / `LC_DELAY_MAX`) and retried
`LC_DETAIL_RETRIES` times (default 2). A page that parses but carries no
overview, screens *or* downloads is treated as a failure worth retrying — that
usually means a guest-gated or partially-rendered response rather than a
genuinely empty post. After the retries are exhausted the game is still stored
with listing-only data rather than skipped.

`_apply_detail` only ever writes non-empty values, so a thread whose post has
been trimmed cannot blank out data already held.

### Seeing it happen

A thread fetch takes a couple of seconds and originally printed nothing on
success, so a run looked stalled and there was no way to tell whether pages were
being scraped at all. With `LC_VERBOSE=1` (the default) each item prints:

```
  [1/30] lc_id 2117 Bright Past [v1.006] [Kosmos Games]
      scraping thread page: https://lewdcorner.com/threads/bright-past-....2117/
        ok in 2.3s | overview 710 chars | tags 32 | screens 12 | downloads 16 | banner yes
        developer='Kosmos Games'  version='1.006'  os=Windows/Linux/MacOS/Android  lang='English, Russian, German, Portuguese'
        external: discord=rwFbCQb, patreon=kosmosgames, subscribestar=kosmos-games
        hosts: mega.nzx4, bzzhr.tox2, datanodes.tox2, pixeldrain.comx2
  added lc_id 2117 -> atlas_id 16901 Bright Past [v1.006] [Kosmos Games]
  [2/30] lc_id 19835 Esterium Project [v0.0002] [Kosmos Games]
        unchanged
```

The progress line prints for **every** item including unchanged ones — a page of
already-known games previously produced no output whatsoever.

Three things in that summary are diagnostics rather than decoration:

* **A line of zeroes** means the parse found nothing and the record is about to
  be stored with listing-only data.
* **`!! no custom-field block found`** means LC changed its layout and
  developer/version/language/OS/links are all silently unavailable.
* **The host list** makes an undecoded masked link obvious — every entry would
  read `lewdcorner.com`.

`LC_VERBOSE=0` restores the terse output.

Fixtures: `scraper/fixtures/lc_*.html` (five real threads, CSRF tokens scrubbed),
covered by `tests/test_lc_detail.py` (22 tests).

---

## Manual links in the export

Admin-added links (`atlas_manual_links`) are overlaid onto `atlas.external_ids`
**at export time only** — the stored column is never written, which is the whole
reason the table exists separately from the scraper's data.

Five ways links were being lost or duplicated, all now covered by
`tests/test_manual_link_export.py`:

**Links were read from one column each.** The admin UI accepts an id, a URL, or
both. But the overlay read `ext_id` for steam/gog and `url` for itch/custom, so
a Steam link added as a URL and an itch link added as an id were both silently
dropped. Every kind is now read from both columns, deriving the missing half
where the platform allows it (`store.steampowered.com/app/<id>` ⇄ id,
`<slug>` → `https://<slug>.itch.io`).

**Duplicates weren't recognised across spellings.** The scraper stores
`itch_url: "caribdis.itch.io"`; an admin adding `https://caribdis.itch.io`
produced a second entry, because the strings differ. Comparison is now on a
normalised URL — scheme, `www.` and trailing slash stripped — so those collapse
to one.

**A full export skipped rows that had never been exported.** `downloadBase` used
`WHERE last_record_update > %s`, and a full package passes `start_time = 0`. Any
atlas row with `last_record_update` of `0` or `NULL` was therefore excluded from
a *full rebuild*, taking its manual links with it — and a full rebuild was
exactly the operation that should have repaired it. `start_time <= 0` now means
everything, with no WHERE clause at all.

> This makes full packages slightly larger, by however many rows had never had
> their export timestamp set. Worth checking before the first run:
> ```sql
> SELECT COUNT(*) FROM atlas WHERE last_record_update IS NULL OR last_record_update <= 0;
> ```

**The delta's self-healing union missed NULL timestamps.** `last_record_update
<= %s` is never true for `NULL`, so those rows weren't rescued in delta runs
either. Now `<= %s OR IS NULL`.

**An unrecognised kind was dropped entirely.** Only steam/gog/itch/custom were
handled, so adding a link kind would have silently lost it here. Anything
unknown now exports as a URL array under its own key.

### The archival backup

`createBackup` deliberately dumps the **raw** atlas table, without the overlay:
restoring merged values into `atlas.external_ids` would destroy the separation
that keeps manual links safe from the scraper. But that left the snapshot
incomplete — a restore lost every admin-added id. `atlas_manual_links` is now
dumped as its own file (`manual_links_backup_YYYYMMDD`), keeping the snapshot
raw *and* complete.

### Export shape

```jsonc
{
  "steam_appid":  "999001",                        // primary, backward compatible
  "steam_appids": ["999001", "999002", "1126320"], // manual first, then scraped
  "gog_id": "...", "gog_ids": [...],
  "itch":   ["https://caribdis.itch.io"],          // url-shaped kinds
  "custom": ["https://blog.example.com/"],
  "steam_urls": [...]                              // store link with no resolvable id
}
```

Manual ids come first in the array and become the scalar, so an admin id is an
override; existing single-id clients keep working unchanged.
