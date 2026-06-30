"""
F95 scraper.

Listing  : the public "latest updates" JSON feed used by F95's own
           /sam/latest_alpha/ page:

               https://f95zone.to/sam/latest_alpha/latest_data.php
                   ?cmd=list&cat=games&page=N&sort=date&rows=R

           This is a single fast request per page (no HTML parse) and gives
           us a `ts` field per thread -- the real timestamp of the latest
           activity. That's more reliable than F95's own "Thread Updated"
           label on the thread page itself (devs often forget to bump it),
           so `ts` is what we store as `thread_updated`, overriding
           whatever the detail-page label says. Change detection compares
           the feed's `ts` against the stored `thread_updated` column --
           NOT against last_thread_comment (raw forum reply activity),
           which produced too many false positives since a thread can get
           new replies without the game itself actually updating.

Detail   : each new/updated thread is still fetched through an AUTHENTICATED
           session so the guest-gated content (external IDs, downloads,
           spoiler sections, full tag list, category/engine/status
           prefixes) resolves -- the listing feed only gives prefix/tag IDs,
           not names, so it can't replace the detail fetch on its own.
           See scraper/agents/f95_detail.py.

Pacing   : the SAME jitter delay (F95_DELAY_MIN/MAX, default 2-4s) is used
           before every actual outbound F95 request -- both listing/API
           calls and detail-page fetches. (An earlier, much smaller delay
           just for listing calls got us rate-limited, so listing calls now
           pace identically to detail fetches.) Skipped/unchanged/already-
           known items never sleep at all -- only an actual request pays
           the delay.

DB cost  : per-page freshness checks are batched into ONE query
           (getLastUpdatesBulk) instead of one query per item, and
           scraper/utils/db.py reuses a single connection for the whole
           process instead of reconnecting per query -- reconnecting to a
           remote MySQL host on every single SELECT was the actual source
           of multi-second-per-page delays, not the API call itself.
"""
import json
import os
import random
import re
import time
from datetime import datetime, timezone

from scraper.auth import F95Session
from scraper.agents.f95_detail import parse_thread_detail
from scraper.datatypes.data import data
from scraper.datatypes.record import gameRecord
from scraper.utils.epoch import epoch
from scraper.utils.db import (
    UpdatetableDynamic, getLastUpdate, getLastUpdatesBulk,
    getAtlasIdByF95Id, insertAtlas, updateAtlasById,
)

LATEST_DATA_URL = "https://f95zone.to/sam/latest_alpha/latest_data.php"


def _jitter():
    """Sleep a randomised interval. Called immediately before every actual
    outbound F95 request -- both listing/API page fetches and detail-page
    fetches (see _fetch_detail) -- but never for items we skip, since those
    make no request at all. Tunable via F95_DELAY_MIN / F95_DELAY_MAX."""
    lo = float(os.environ.get("F95_DELAY_MIN", "2.0"))
    hi = float(os.environ.get("F95_DELAY_MAX", "4.0"))
    if hi < lo:
        hi = lo
    time.sleep(random.uniform(lo, hi))


def _list_rows():
    """Items per listing page. Tunable via F95_LIST_ROWS (matches the rows
    param F95's own front-end requests -- 90 -- by default)."""
    try:
        return int(os.environ.get("F95_LIST_ROWS", "90"))
    except ValueError:
        return 90


def _debug_enabled():
    """Set F95_DEBUG_TS=true to print, for EVERY item the feed returns
    (changed or not), the API's current `ts` side by side with what's
    stored in the DB as thread_updated -- the exact two values that drive
    change detection. Useful for confirming, against a live run, where in
    the feed the stored values stop matching the API's (i.e. where the
    catalog's thread_updated backfill actually left off)."""
    return os.environ.get("F95_DEBUG_TS", "false").lower() == "true"


def _fmt_ts(ts):
    if not ts:
        return "(unset)"
    try:
        return f"{ts} ({datetime.fromtimestamp(ts, tz=timezone.utc).date()})"
    except (ValueError, OSError, OverflowError):
        return str(ts)


def threadURL(thread_id):
    # No slug needed: F95 (XenForo) redirects a numeric-only thread URL to
    # the canonical slugged one, and requests follows redirects by default.
    return f"https://f95zone.to/threads/{thread_id}/"


class f95:
    def __init__(self, session=None):
        # A single authenticated session is reused for the whole run; the
        # cookie is loaded from disk and only refreshed when it expires.
        # The listing feed doesn't strictly require auth, but reusing the
        # same session keeps headers/cookies consistent and avoids a second
        # code path.
        self.session = session or F95Session()

    # ---- listing (JSON feed) -------------------------------------------------
    def _fetch_listing_page(self, page_no, category="games", rows=None):
        """Returns (items, total_pages). total_pages comes from the feed's
        own pagination.total field, e.g.:
            {"status": "ok", "msg": {"data": [...],
                "pagination": {"page": 1, "total": 877}, "count": 26297}}

        This matters because F95 does NOT return an empty page once you
        page past the real end -- it just keeps re-serving the last page's
        data forever. Relying on "items is empty -> stop" alone means the
        crawl never terminates; total_pages is the only reliable signal for
        where the feed actually ends.

        Returns (None, None) on an API error/transient failure (caller
        retries); returns (items, total_pages) -- total_pages may be None
        if the feed response is missing pagination, in which case the
        caller falls back to the old empty-page heuristic."""
        url = (f"{LATEST_DATA_URL}?cmd=list&cat={category}&page={page_no}"
               f"&sort=date&rows={rows or _list_rows()}")
        resp = self.session.get_json(url)
        if not resp or resp.get("status") != "ok":
            print("listing API error:", resp)
            return None, None
        msg = resp.get("msg") or {}
        items = msg.get("data") or []
        total_pages = (msg.get("pagination") or {}).get("total")
        try:
            total_pages = int(total_pages) if total_pages is not None else None
        except (TypeError, ValueError):
            total_pages = None
        return items, total_pages

    # ---- main run -----------------------------------------------------------
    def run(self, db_type, full_detail=False, new_only=False, ts_only=False,
            max_pages=None, category="games"):
        """
        Four modes (checked in this priority order if more than one is True):

        ts_only     : pure API sweep, NEVER opens a detail page. Walks the
                      entire feed and, for any thread that's new or whose
                      `ts` is newer than what we have, stores just the
                      listing-level fields (title/creator/version/views/
                      likes/rating/ts). Never touches banner_url/screens --
                      those only ever come from the real detail page. This
                      is the "just load every API page and capture ts" mode.
        new_only    : API-only sweep for missing games -- walks the ENTIRE
                      feed (no early stop) but only fetches the detail page
                      for threads that don't exist in our DB yet. Threads we
                      already have are left untouched even if `ts` shows
                      newer activity.
        full_detail : re-fetch the detail page for EVERY thread in the feed
                      (a full re-crawl). No early stop.
        (default)   : incremental -- new OR updated threads get a detail
                      fetch; stops early once a page has nothing new to do,
                      since the feed is newest-activity-first.

        Pacing in every mode: the same jitter (_jitter) happens before every
        actual request -- both listing-page fetches and detail-page
        fetches. Skipped/unchanged/already-known items make no request at
        all, so they never sleep.
        """
        # Authenticate up front so we fail fast on bad credentials.
        self.session.ensure_authenticated()

        # The feed is sorted by latest activity, so "nothing new on this
        # page -> stop" only holds for the plain incremental mode. The other
        # three modes all have to walk the full feed for their own reasons
        # (new_only: a brand-new thread can sit anywhere relative to old
        # threads bumped by an update; full_detail: revisiting everything by
        # definition; ts_only: the point is a complete catalog-wide sweep).
        allow_early_stop = not (full_detail or new_only or ts_only)

        page_no = 1
        prev_page_ids = None
        while True:
            if max_pages and page_no > max_pages:
                print(f"reached max_pages={max_pages}; stopping")
                break

            print(f"---- listing page {page_no} (API) ----")
            _jitter()
            try:
                items, total_pages = self._fetch_listing_page(page_no, category=category)
            except Exception as ex:
                print("listing fetch failed:", ex)
                time.sleep(10)
                continue

            if items is None:
                # transient/API error -> brief backoff then retry the page
                time.sleep(10)
                continue
            if not items:
                print("listing returned no items; end of feed")
                break

            # F95 does NOT return an empty page once you page past the real
            # end -- it just keeps re-serving the last page's data forever.
            # pagination.total (from the feed itself) is the reliable signal
            # for where the feed actually ends; without it we'd loop forever
            # past the real last page, since "items is empty" never happens.
            if total_pages and page_no >= total_pages:
                print(f"reached last page per feed pagination "
                      f"(page {page_no}/{total_pages}); stopping after this page")
                stop_after_this_page = True
            else:
                stop_after_this_page = False

            # Fallback safety net for the same problem, in case a future
            # response is ever missing pagination entirely: if this page's
            # items are EXACTLY the same set as the previous page's, we've
            # walked past the real end and the feed is just repeating itself.
            current_page_ids = frozenset(it.get("thread_id") for it in items)
            if not stop_after_this_page and prev_page_ids is not None \
                    and current_page_ids == prev_page_ids:
                print("page is identical to the previous page (no pagination "
                      "info available) -- past the real end of the feed; stopping")
                break
            prev_page_ids = current_page_ids

            # One round trip for the whole page's freshness check instead of
            # one per item -- this is what actually made "skip everything
            # unchanged" fast. The per-item write path (new/updated games)
            # still does its own queries, proportional to actual changes.
            last_updates = getLastUpdatesBulk(
                [it.get("thread_id") for it in items], db_type
            )

            processed = 0
            for item in items:
                try:
                    if self._process_listing_item(item, db_type, full_detail,
                                                   new_only, ts_only,
                                                   last_updates):
                        processed += 1
                except Exception as ex:   # keep going on a single bad row
                    print("item error:", ex)

            if allow_early_stop and processed == 0:
                print("page fully up-to-date; stopping early")
                break

            if stop_after_this_page:
                break

            page_no += 1
            # The _jitter() pause happens at the top of the next loop
            # iteration, right before that page's fetch -- not here.

    def _process_listing_item(self, item, db_type, full_detail,
                               new_only=False, ts_only=False,
                               last_updates=None):
        atlas = gameRecord.atlasRecord()
        f95rec = gameRecord.f95Record()

        thread_id = item.get("thread_id")
        if not thread_id:
            return False
        f95rec["f95_id"] = str(thread_id)
        f95rec["site_url"] = threadURL(thread_id)

        # str(...) guards against the feed occasionally returning one of
        # these as a JSON number (e.g. an unset/blank field) instead of a
        # string -- .strip() on a bare float blows up otherwise.
        atlas["title"] = str(item.get("title") or "").strip()
        atlas["creator"] = str(item.get("creator") or "").strip()
        atlas["version"] = str(item.get("version") or "").strip()
        atlas["short_name"] = re.sub(
            r"[\W_]+", "", atlas["title"].strip().replace(" ", "")
        ).upper()
        atlas["id_name"] = atlas["short_name"] + "_" + atlas["creator"].upper()

        f95rec["views"] = item.get("views") or 0
        f95rec["likes"] = item.get("likes") or 0
        f95rec["rating"] = item.get("rating") or 0.0
        # Deliberately NOT pulling item["cover"]/item["screens"] here. Those
        # are low-res preview thumbnails from the listing feed, not the
        # actual game images -- banner_url/screens should only ever be set
        # from the real detail page (see _fetch_detail's d["cover_url"] /
        # d["screens"]). In ts_only mode, which never visits the detail
        # page, that means these columns simply stay whatever they already
        # were (untouched) rather than getting filled with thumbnails.

        # `ts` is the feed's accurate last-activity timestamp. It's still
        # stored as last_thread_comment for reference/display, but it is
        # NOT used for change detection anymore -- see is_updated below,
        # which compares against thread_updated instead.
        ts = int(item.get("ts") or 0)
        f95rec["last_thread_comment"] = ts

        if last_updates is not None:
            last_update = int(last_updates.get(f95rec["f95_id"], 0))
        else:
            # Fallback for direct/standalone calls that didn't batch-fetch.
            last_update = int(getLastUpdate(db_type, f95rec["f95_id"]))
        is_new = last_update == 0
        # Comparison is purely against thread_updated now -- last_thread_comment
        # (raw forum reply activity) is no longer used for change detection at
        # all; it produced too many false positives, since a thread can get new
        # replies without the game itself actually updating. A row with no
        # thread_updated yet (0) naturally compares as "older" than any real
        # `ts`, so it gets picked up and backfilled the next time it's seen --
        # no special-casing needed for that.
        is_updated = ts > last_update

        if _debug_enabled():
            print(f"  compare f95_id={f95rec['f95_id']} {atlas['title']!r}: "
                  f"api_ts={_fmt_ts(ts)}  db_thread_updated={_fmt_ts(last_update)}  "
                  f"is_new={is_new} is_updated={is_updated}")

        if ts_only:
            # Pure API sweep -- never opens a detail page (only the
            # listing-page jitter applies, never an extra one per item).
            # Still skip a write when nothing changed, so this stays cheap
            # even walking the full catalog every time.
            if not (is_new or is_updated):
                return False
            if ts:
                f95rec["thread_updated"] = ts
            self._update_record(atlas, f95rec, db_type)
            return True

        if new_only:
            # API-only sweep: skip anything we already have a row for,
            # purely a quick "do we have this thread at all" check, no
            # detail page involved -- and so no jitter for the skip.
            if not is_new:
                return False
        elif not (is_new or is_updated or full_detail):
            return False          # unchanged -> skip, no detail fetch, no delay

        print("detail:", f95rec["f95_id"], atlas.get("title"))
        self._fetch_detail(f95rec["site_url"], atlas, f95rec)

        # `ts` from the feed is more accurate than F95's own "Thread Updated"
        # label scraped off the thread page (devs often forget to bump it) --
        # stamp it last so it wins over whatever _fetch_detail just set.
        if ts:
            f95rec["thread_updated"] = ts

        self._update_record(atlas, f95rec, db_type)
        return True

    # ---- detail (authenticated) ---------------------------------------------
    def _fetch_detail(self, site_url, atlas, f95rec):
        _jitter()  # politeness + jitter to avoid rate limiting -- ONLY here,
                   # right before an actual page load.
        r = self.session.get(site_url)
        if r.status_code != 200:
            print("detail fetch failed:", r.status_code, site_url)
            return
        d = parse_thread_detail(r.text)

        if d.get("logged_in") is False:
            # Session died and re-login failed; skip rather than store guest data.
            print("WARNING: not logged in for", site_url, "- skipping gated fields")

        # Category / engine / status come from the thread page's own prefix
        # labels (e.g. "VN", "Ren'Py", "Completed") -- the listing feed only
        # gives numeric prefix IDs, which we'd have to map ourselves, so the
        # detail page remains the source of truth for these.
        for label in d.get("prefixes") or []:
            up = label.strip().upper()
            if up in data.Tcategory():
                atlas["category"] = label.strip()
            elif up in data.Tengine():
                atlas["engine"] = label.strip()
            elif up in data.Tstaus():
                atlas["status"] = label.strip()

        # f95-specific
        if d.get("cover_url"):
            f95rec["banner_url"] = d["cover_url"]
        if d.get("screens"):
            f95rec["screens"] = ",".join(d["screens"])
        if d.get("tags"):
            f95rec["tags"] = ",".join(d["tags"])
        if d.get("downloads"):
            f95rec["downloads"] = json.dumps(d["downloads"], ensure_ascii=False)
        if d.get("patches"):
            f95rec["patches"] = json.dumps(d["patches"], ensure_ascii=False)
        if d.get("extras"):
            f95rec["extras"] = json.dumps(d["extras"], ensure_ascii=False)
        if d.get("translations"):
            f95rec["translations"] = json.dumps(d["translations"], ensure_ascii=False)
        if d.get("likes") is not None:
            f95rec["likes"] = d.get("likes")
        if d.get("thread_updated"):
            # F95's own "Thread Updated: YYYY-MM-DD" label on the thread page.
            # Kept as a fallback; the caller overrides this with the feed's
            # `ts` right after this call when one is available.
            f95rec["thread_updated"] = epoch.ConvertToUnixTime(d["thread_updated"])

        # canonical / atlas
        atlas["overview"] = d.get("overview", "")
        atlas["censored"] = d.get("censored", "")
        atlas["language"] = d.get("language", "")
        atlas["os"] = d.get("os", "")
        atlas["length"] = d.get("length", "")
        atlas["voice"] = d.get("voice", "")
        if d.get("release_date"):
            atlas["release_date"] = epoch.ConvertToUnixTime(d["release_date"])

        ext = d.get("external_ids", {})
        if ext:
            atlas["external_ids"] = json.dumps(ext, ensure_ascii=False)

    # ---- persistence --------------------------------------------------------
    @staticmethod
    def _clean(d):
        return {k: v for k, v in d.items() if v}

    def _update_record(self, atlas, f95rec, db_type):
        # Bookkeeping timestamp: when OUR scraper wrote this row. Distinct from
        # f95rec["thread_updated"], which is the feed's `ts` (or, as a
        # fallback, F95's own "Thread Updated" date scraped off the page).
        # Stamped here, right before the write, rather than back at
        # listing-parse time.
        now = int(time.time())
        f95rec["last_record_update"] = now
        atlas["last_record_update"] = now

        # Find-or-create the atlas row by the thread's stable f95_id, NOT by
        # the title-derived id_name. id_name can change (renames) or collide
        # (two threads, same title+creator); f95_id never does.
        f95_id = f95rec["f95_id"]
        atlas_id = getAtlasIdByF95Id(f95_id, db_type)
        if atlas_id:
            # Known thread -> update its existing atlas row in place.
            updateAtlasById(atlas_id, self._clean(atlas), db_type)
        else:
            # New thread -> insert a fresh atlas row and take its new id.
            atlas_id = insertAtlas(self._clean(atlas), db_type)
        f95rec["atlas_id"] = atlas_id
        UpdatetableDynamic("f95_zone", self._clean(f95rec), db_type)
        print("  stored f95_id", f95_id, "-> atlas_id", atlas_id)
