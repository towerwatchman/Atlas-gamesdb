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
