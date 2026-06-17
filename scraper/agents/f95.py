"""
F95 scraper.

Listing  : public forum listing at /forums/games.2/ (unchanged approach;
           login is not required to enumerate threads).
Detail   : each new/updated thread page is fetched through an AUTHENTICATED
           session so the guest-gated content (external IDs, downloads,
           spoiler sections) resolves. See scraper/agents/f95_detail.py.
"""
import json
import os
import random
import time

import requests
from bs4 import BeautifulSoup

from scraper.auth import F95Session
from scraper.agents.f95_detail import parse_thread_detail
from scraper.datatypes.record import gameRecord
from scraper.utils.epoch import epoch
from scraper.utils.parser import parser
from scraper.utils.db import (
    UpdatetableDynamic, getLastUpdate,
    getAtlasIdByF95Id, insertAtlas, updateAtlasById,
)


def _jitter():
    """Sleep a randomised interval between requests to avoid a regular,
    rate-limit-tripping cadence. Tunable via F95_DELAY_MIN / F95_DELAY_MAX."""
    lo = float(os.environ.get("F95_DELAY_MIN", "2.0"))
    hi = float(os.environ.get("F95_DELAY_MAX", "4.0"))
    if hi < lo:
        hi = lo
    time.sleep(random.uniform(lo, hi))


def baseURL():
    return "https://f95zone.to/forums/games.2/"


class f95:
    def __init__(self, session=None):
        # A single authenticated session is reused for the whole run; the
        # cookie is loaded from disk and only refreshed when it expires.
        self.session = session or F95Session()

    # ---- listing (public) ---------------------------------------------------
    def getThreadPageCount(self):
        r = requests.get(baseURL(), headers=self.session.session.headers, timeout=30)
        if r.status_code != 200:
            print("Listing page error:", r.status_code)
            return 0
        page = BeautifulSoup(r.content, "lxml")
        nav = page.select("div.pageNavSimple")
        if not nav:
            return 0
        text = nav[0].find_all("a")[0].text.strip()
        return int(text.upper().split("OF")[1])

    # ---- main run -----------------------------------------------------------
    def run(self, db_type, full_detail=False, max_pages=None):
        # Authenticate up front so we fail fast on bad credentials.
        self.session.ensure_authenticated()

        total = self.getThreadPageCount()
        pages = min(total, max_pages) if max_pages else total
        print(f"F95: {total} listing pages (processing {pages})")

        for page_no in range(1, pages + 1):
            print(f"---- listing page {page_no} ----")
            url = baseURL() + ("?order=post_date&direction=desc" if page_no == 1
                               else f"page-{page_no}?order=post_date&direction=desc")
            try:
                r = requests.get(url, headers=self.session.session.headers, timeout=30)
            except requests.RequestException as ex:
                print("listing fetch failed:", ex)
                time.sleep(10)
                continue
            if r.status_code != 200:
                print("listing timeout, waiting 10s")
                time.sleep(10)
                continue

            html = BeautifulSoup(r.content, "lxml")
            processed = 0
            for element in html.find_all("div", class_="structItem"):
                try:
                    if self._process_listing_item(element, db_type, full_detail):
                        processed += 1
                except Exception as ex:   # keep going on a single bad row
                    print("item error:", ex)

            # Incremental runs: the listing is newest-activity-first, so once a
            # whole page has nothing new/updated, everything below is older too
            # -> stop crawling (no more page loads, no more waiting). Skipped
            # games never incur a delay; only fetched detail pages do.
            if not full_detail and processed == 0:
                print("page fully up-to-date; stopping early")
                break
            _jitter()

    def _process_listing_item(self, element, db_type, full_detail):
        atlas = gameRecord.atlasRecord()
        f95rec = gameRecord.f95Record()

        title_links = element.select("div.structItem-title")[0].find_all("a")
        parser.ParseThreadItem(title_links, atlas, f95rec)
        if atlas.get("category") == "README":
            return False

        f95rec["thread_publish_date"] = epoch.ConvertToUnixTime(
            element.select("li.structItem-startDate")[0].find_all("a")[0]
            .select("time")[0]["datetime"].replace("T", " ")[:-5]
        )
        f95rec["last_thread_comment"] = epoch.ConvertToUnixTime(
            parser.ParseDateTimeItem(element.select("time.structItem-latestDate"))
        )
        f95rec["replies"] = parser.ParseReplies(element)
        f95rec["views"] = parser.ParseViews(element)
        f95rec["rating"] = parser.ParseRating(element)

        last_update = int(getLastUpdate(db_type, f95rec["f95_id"]))
        is_new = last_update == 0
        is_updated = int(f95rec["last_thread_comment"] or 0) > last_update
        if not (is_new or is_updated or full_detail):
            return False          # unchanged -> skip, no detail fetch, no delay

        print("detail:", f95rec["f95_id"], atlas.get("title"))
        self._fetch_detail(f95rec["site_url"], atlas, f95rec)

        self._update_record(atlas, f95rec, db_type)
        return True

    # ---- detail (authenticated) ---------------------------------------------
    def _fetch_detail(self, site_url, atlas, f95rec):
        _jitter()  # politeness + jitter to avoid rate limiting
        r = self.session.get(site_url)
        if r.status_code != 200:
            print("detail fetch failed:", r.status_code, site_url)
            return
        d = parse_thread_detail(r.text)

        if d.get("logged_in") is False:
            # Session died and re-login failed; skip rather than store guest data.
            print("WARNING: not logged in for", site_url, "- skipping gated fields")

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
            # F95's own "Thread Updated: YYYY-MM-DD" label on the thread page,
            # not the time our scraper happened to run.
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
        # f95rec["thread_updated"], which is F95's own "Thread Updated" date
        # scraped off the page. Stamped here, right before the write, rather
        # than back at listing-parse time.
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