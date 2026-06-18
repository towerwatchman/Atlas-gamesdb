"""
LewdCorner scraper.

LewdCorner runs XenForo (like F95) and exposes a JSON feed for its
"Latest Updates" page:

    https://lewdcorner.com/latest-updates.php?api=1&action=list
        &page=<n>&perPage=<n>&cat=All&tier=All&sort=date
        &q=&searchIn=title&platform=&dateDays=0&tags_mode=and

The feed is returned for an AUTHENTICATED session, so we reuse the same
dummy-account session-cookie approach as F95 (see scraper.auth.LCSession).

Response envelope (confirmed against a live sample):
    {
      "status": "ok",
      "data": { "items": [ {item}, ... ],
                "total": 9550, "page": 1, "perPage": 30, "hasMore": true,
                "meta": {...} },
      "error": null,
      "items": [ ... ]            # mirror of data.items
    }

Each item (fields we use):
    id            -> stable thread id  (lc_id)
    title         -> game title
    developer     -> creator
    version       -> version string ("0.3", "Final", "Prologue", ...)
    link          -> full thread URL
    image         -> cover image
    images        -> [cover, screenshot, screenshot, ...]
    tags          -> [str, ...]
    badges        -> [{name: "Ren'Py"/"Unity"/"Completed"/...}]  engine+status+prefixes
    platforms     -> ["Windows","Linux",...]  -> os
    view_count, like_score, rating
    post_date     -> original post epoch        (register_date)
    timestamp     -> newest-activity epoch (sort key; updated bumps it)
    activity_type -> "new" | "upd"
    is_premium    -> bool  -> tier "Premium"/"Free"

De-duplication rule (per requirements)
--------------------------------------
Every feed entry is recorded in the `lewdcorner` table, linked to an atlas_id.
For each item:
  1. lc_id already in `lewdcorner` table  -> update that atlas row + lc row.
  2. else id_name already in `atlas` (e.g. from F95) -> LINK: write a lewdcorner
     row pointing at the existing atlas_id, WITHOUT inserting a duplicate atlas
     row or overwriting the existing (F95-owned) atlas fields.
  3. else -> insert new atlas row + new lewdcorner row.

Cross-source match key is the atlas `id_name`, computed the SAME way F95
computes it (short_name + "_" + CREATOR). See _normalise_id_name().

  >>> Title/developer formatting differs between sites, so this is a fuzzy
  >>> match. Two identical-title threads by the same dev in one feed (e.g.
  >>> "Fairy Tails" by Milfsgiving, ids 23056 & 23061) map to one atlas game;
  >>> because lewdcorner.atlas_id is UNIQUE, the second upserts over the first
  >>> (last-write-wins), matching the f95_zone single-row-per-game model.
"""
import json
import os
import random
import re
import time

from scraper.auth import LCSession
from scraper.datatypes.record import gameRecord
from scraper.utils.epoch import epoch
from scraper.utils.db import (
    UpdatetableDynamic, getAtlasIdByLcId, findIdByTitle,
    insertAtlas, updateAtlasById, atlasOwnedByOtherSource,
)

BASE = "https://lewdcorner.com"
API = BASE + "/latest-updates.php"

# Badge names that denote a thread STATUS rather than an engine/prefix.
_STATUS_BADGES = {"COMPLETED", "ABANDONED", "ONHOLD", "ON HOLD"}
# Badge names that denote an ENGINE.
_ENGINE_BADGES = {
    "REN'PY", "UNITY", "UNREAL ENGINE", "RPGM", "HTML", "FLASH", "JAVA",
    "QSP", "WOLF RPG", "ADRIFT", "TADS", "RAGS", "WEBGL", "OTHERS",
}


def _jitter():
    """Randomised inter-request delay, same idea as the F95 agent.
    Tunable via LC_DELAY_MIN / LC_DELAY_MAX."""
    lo = float(os.environ.get("LC_DELAY_MIN", "2.0"))
    hi = float(os.environ.get("LC_DELAY_MAX", "4.0"))
    if hi < lo:
        hi = lo
    time.sleep(random.uniform(lo, hi))


def _normalise_id_name(title, creator):
    """Reproduce F95's id_name so the same game matches across sites.

    Mirrors scraper/utils/parser.ParseThreadItem:
        short_name = strip non-alnum from title, uppercase
        id_name    = short_name + "_" + CREATOR
    """
    short = re.sub(r"[\W_]+", "", (title or "").strip().replace(" ", "")).upper()
    return short, short + "_" + (creator or "").upper()


def _classify_badges(badges):
    """Split the badge list into (engine, status, prefixes_csv)."""
    engine = ""
    status = ""
    names = []
    for b in badges or []:
        name = (b.get("name") or "").strip()
        if not name:
            continue
        names.append(name)
        up = name.upper()
        if up in _ENGINE_BADGES and not engine:
            engine = name
        elif up in _STATUS_BADGES and not status:
            status = name
    return engine, status, ",".join(names)


def _extract(item):
    """Map ONE raw API item dict -> (atlas_record, lc_record).

    Returns (None, None) for rows we can't key (no id/title)."""
    lc_id = item.get("id")
    title = (item.get("title") or "").strip()
    if not lc_id or not title:
        return None, None

    creator = (item.get("developer") or "").strip()
    version = (item.get("version") or "").strip()
    url = item.get("link") or ""

    tags = item.get("tags") or []
    tags_csv = ",".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)

    images = item.get("images") or []
    # images[0] duplicates `image` (the cover); the rest are screenshots.
    screens = images[1:] if len(images) > 1 else []
    screens_csv = ",".join(str(s) for s in screens)

    platforms = item.get("platforms") or []
    os_csv = ",".join(str(p) for p in platforms) if isinstance(platforms, list) else str(platforms)

    engine, status, prefixes = _classify_badges(item.get("badges"))

    short_name, id_name = _normalise_id_name(title, creator)

    atlas = gameRecord.atlasRecord()
    atlas["title"] = title
    atlas["short_name"] = short_name
    atlas["id_name"] = id_name
    atlas["creator"] = creator
    atlas["developer"] = creator
    atlas["version"] = version
    atlas["tags"] = tags_csv
    atlas["os"] = os_csv
    if engine:
        atlas["engine"] = engine
    if status:
        atlas["status"] = status

    lc = gameRecord.lcRecord()
    lc["lc_id"] = lc_id
    lc["site_url"] = url
    lc["banner_url"] = item.get("image") or (images[0] if images else "")
    lc["tier"] = "Premium" if item.get("is_premium") else "Free"
    lc["prefixes"] = prefixes
    lc["tags"] = tags_csv
    lc["views"] = item.get("view_count") or 0
    lc["likes"] = item.get("like_score") or 0
    lc["rating"] = item.get("rating") or 0.0
    lc["screens"] = screens_csv
    if item.get("post_date"):
        lc["register_date"] = int(item["post_date"])
    if item.get("timestamp"):
        lc["thread_updated"] = int(item["timestamp"])

    return atlas, lc


class lewdcorner:
    def __init__(self, session=None):
        self.session = session or LCSession()

    def _build_url(self, page, per_page):
        return (
            f"{API}?ps=1&cat=Games&api=1&action=list&page={page}&perPage={per_page}"
            f"&tier=All&sort=date&q=&searchIn=title"
            f"&platform=&dateDays=0&tags_mode=and"
        )

    @staticmethod
    def _items_from_payload(payload):
        """Pull the list of game items out of the API response envelope.
        Prefer data.items; fall back to top-level items / list shapes."""
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        for key in ("items", "results", "threads", "list"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []

    @staticmethod
    def _has_more(payload, items):
        """True if the feed says there are more pages."""
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict) and "hasMore" in data:
                return bool(data["hasMore"])
            if "hasMore" in payload:
                return bool(payload["hasMore"])
        return bool(items)

    def run(self, db_type, full=False, per_page=30, max_pages=None):
        """Walk the latest-updates feed and add new games.

        Incremental (full=False): the feed is newest-activity-first, so once a
        whole page yields nothing new/updated we stop early (same strategy as
        the F95 agent). Full (full=True): walk every page until hasMore=false
        (or max_pages)."""
        self.session.ensure_authenticated()

        page = 1
        added = updated = linked = skipped = 0
        while True:
            if max_pages and page > max_pages:
                break
            url = self._build_url(page, per_page)
            print(f"---- LewdCorner feed page {page} ----")
            payload = self.session.get_json(url)
            items = self._items_from_payload(payload)
            if not items:
                print("no items returned; stopping")
                break

            page_changed = 0
            for item in items:
                try:
                    result = self._process_item(item, db_type, full)
                except Exception as ex:   # one bad row shouldn't kill the run
                    print("item error:", ex)
                    continue
                if result == "added":
                    added += 1; page_changed += 1
                elif result == "updated":
                    updated += 1; page_changed += 1
                elif result == "linked":
                    linked += 1; page_changed += 1
                elif result == "skipped":
                    skipped += 1

            if not full and page_changed == 0:
                print("page fully up-to-date; stopping early")
                break
            if not self._has_more(payload, items):
                print("feed reports no more pages; stopping")
                break
            page += 1
            _jitter()

        print(f"LewdCorner done: {added} added, {updated} updated, "
              f"{linked} linked to existing, {skipped} skipped.")

    def _process_item(self, item, db_type, full):
        atlas, lc = _extract(item)
        if atlas is None:
            return "skipped"

        lc_id = lc["lc_id"]
        now = int(time.time())
        lc["last_record_update"] = now

        # 1. Already scraped this exact LewdCorner thread -> update in place.
        #    Refresh the atlas fields ONLY if no other source owns this game
        #    (so we never clobber an F95/dlsite/sxs-owned atlas row).
        existing_atlas_id = getAtlasIdByLcId(lc_id, db_type)
        if existing_atlas_id:
            if not atlasOwnedByOtherSource(existing_atlas_id, db_type):
                atlas["last_record_update"] = now
                updateAtlasById(existing_atlas_id, self._clean(atlas), db_type)
            lc["atlas_id"] = existing_atlas_id
            UpdatetableDynamic("lewdcorner", self._clean(lc), db_type)
            return "updated"

        # 2. Game already in atlas from another source (e.g. F95) -> LINK.
        #    We do NOT insert a duplicate atlas row and we do NOT overwrite the
        #    existing (F95-owned) atlas fields; we just record a lewdcorner row
        #    pointing at that atlas_id so every feed entry is captured.
        #    NOTE: lewdcorner.atlas_id is UNIQUE, so if two different LC threads
        #    map to the same atlas game (same title+dev), the upsert keeps the
        #    most recently written one (last-write-wins) -- same single-row-per-
        #    game model as f95_zone.
        linked_atlas_id = findIdByTitle("atlas", atlas["id_name"], db_type)
        if linked_atlas_id:
            lc["atlas_id"] = linked_atlas_id
            UpdatetableDynamic("lewdcorner", self._clean(lc), db_type)
            print("  linked lc_id", lc_id, "-> existing atlas_id", linked_atlas_id,
                  atlas["title"])
            return "linked"

        # 3. Genuinely new -> insert a new atlas row + a new lewdcorner row.
        atlas["last_record_update"] = now
        new_atlas_id = insertAtlas(self._clean(atlas), db_type)
        lc["atlas_id"] = new_atlas_id
        UpdatetableDynamic("lewdcorner", self._clean(lc), db_type)
        print("  added lc_id", lc_id, "-> atlas_id", new_atlas_id, atlas["title"])
        return "added"

    @staticmethod
    def _clean(d):
        return {k: v for k, v in d.items() if v not in ("", None)}


# ---- offline self-test (no network): mapping + dedup against a fixture ----
if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    fx = os.path.join(here, "..", "fixtures", "lewdcorner_list.json")
    with open(fx, encoding="utf-8") as f:
        payload = json.load(f)
    items = lewdcorner._items_from_payload(payload)
    print("items parsed:", len(items), "| hasMore:",
          lewdcorner._has_more(payload, items))
    for it in items:
        a, l = _extract(it)
        print(f"\nlc_id={l['lc_id']}  id_name={a['id_name']!r}")
        print("  title   :", a["title"])
        print("  engine  :", a["engine"], "| status:", a["status"], "| os:", a["os"])
        print("  version :", a["version"], "| tier:", l["tier"])
        print("  cover   :", l["banner_url"])
        print("  screens :", l["screens"][:60], "...")
