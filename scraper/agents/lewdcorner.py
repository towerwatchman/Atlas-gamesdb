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
import difflib
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
    getLcThreadUpdatesBulk, getLcThreadUpdated,
    findAtlasIdsByIdName, findFuzzyAtlasCandidates,
    getAtlasRowsByIds, enqueueLcReview, isLcInReviewQueue,
)

# --- Fuzzy match scoring (integer 0-100) -----------------------------------
# When an incoming LC game has no EXACT id_name match, we still want to know
# whether a differently-spelled atlas row is really the same game before we
# create a brand-new atlas row for it. We score each fuzzy candidate on an
# integer 0-100 similarity scale (mirrors the weighting the admin-only
# reconcile_lc.py uses: 70% title, 30% creator) and branch on empirically
# verified bands:
#     best score 71-99  -> ambiguous          -> review queue ("fuzzy")
#     best score <= 70  -> genuinely different -> add as a new atlas row
# An EXACT id_name match never reaches the scorer -- it's handled earlier as a
# direct link (1 match) or a "multi" queue (>1 match). So a perfect 100 here
# is only ever produced by, and equivalent to, that exact-match link path.
_TITLE_WEIGHT = 0.7
_CREATOR_WEIGHT = 0.3
# Lower edge of the "send to review" band. <= this = add as new.
LC_REVIEW_FLOOR = 70


def _sim(a, b):
    """0.0-1.0 order-insensitive similarity between two strings."""
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _score_candidate(lc_title, lc_creator, atlas_row):
    """Integer 0-100 similarity of an incoming LC game to one atlas row.

    Weighted 70% title / 30% creator, matching reconcile_lc._score. Returns
    an int in [0, 100].
    """
    t = _sim(lc_title, atlas_row.get("title"))
    c = _sim(lc_creator, atlas_row.get("creator") or atlas_row.get("developer"))
    return int(round(100 * (_TITLE_WEIGHT * t + _CREATOR_WEIGHT * c)))


def _best_candidate(lc_title, lc_creator, atlas_rows):
    """Return (best_score:int, best_atlas_id) over atlas_rows, or (0, None)."""
    best_score = 0
    best_id = None
    for row in atlas_rows or []:
        s = _score_candidate(lc_title, lc_creator, row)
        if s > best_score:
            best_score = s
            best_id = row.get("atlas_id")
    return best_score, best_id

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


# LewdCorner's feed sometimes bakes a literal " - Version:" (and whatever
# followed it) into the `title` field itself, e.g. "Lust for Life - Version:"
# instead of just "Lust for Life" -- the real version string is already a
# separate `version` field, so this is pure noise that needs stripping.
_VERSION_SUFFIX_RE = re.compile(r"\s*-\s*Version\s*:.*$", re.IGNORECASE)


def _strip_version_suffix(title):
    return _VERSION_SUFFIX_RE.sub("", title or "").strip()


def _normalize_ws(s):
    """Collapse any run of whitespace (tabs/newlines/double-spaces/etc.) to
    a single space and strip the ends. Applied to every string value before
    it's written to the DB."""
    if not isinstance(s, str):
        return s
    return re.sub(r"\s+", " ", s).strip()


def _clean_tag(tag):
    """Tags come through with hyphens (e.g. "big-tits") -- strip those out
    entirely before they're ever stored."""
    return _normalize_ws(str(tag).replace("-", ""))


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
    title = _strip_version_suffix(title)
    if not lc_id or not title:
        return None, None

    creator = (item.get("developer") or "").strip()
    version = (item.get("version") or "").strip()
    url = item.get("link") or ""

    tags = item.get("tags") or []
    if isinstance(tags, list):
        clean_tags = [_clean_tag(t) for t in tags]
    else:
        clean_tags = [_clean_tag(tags)]
    tags_csv = ",".join(t for t in clean_tags if t)

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

        Change detection for already-known threads compares the feed's
        `timestamp` against the stored thread_updated column -- an
        already-seen lc_id is only re-written if it's actually newer.
        (Previously every re-seen lc_id was unconditionally treated as
        "updated" with no freshness check at all, which both wasted writes
        and meant the early-stop below almost never actually triggered.)

        Incremental (full=False): the feed is newest-activity-first, so once a
        whole page yields nothing new/updated/linked we stop early (same
        strategy as the F95 agent). Full (full=True): re-writes every
        already-known thread regardless of freshness, and walks every page
        until hasMore=false (or max_pages)."""
        self.session.ensure_authenticated()

        page = 1
        added = updated = linked = skipped = queued = 0
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
            # One round trip for the whole page's freshness check, same
            # pattern as the F95 agent -- avoids a query per item for the
            # (usually large) majority of items that are already known and
            # unchanged.
            lc_ids = [it.get("id") for it in items]
            last_updates = getLcThreadUpdatesBulk(lc_ids, db_type)

            for item in items:
                try:
                    result = self._process_item(item, db_type, full, last_updates)
                except Exception as ex:   # one bad row shouldn't kill the run
                    print("item error:", ex)
                    continue
                if result == "added":
                    added += 1; page_changed += 1
                elif result == "updated":
                    updated += 1; page_changed += 1
                elif result == "linked":
                    linked += 1; page_changed += 1
                elif result == "queued":
                    queued += 1; page_changed += 1
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
              f"{linked} linked to existing, {queued} queued for review, "
              f"{skipped} skipped.")

    def _process_item(self, item, db_type, full, last_updates=None):
        atlas, lc = _extract(item)
        if atlas is None:
            return "skipped"

        lc_id = lc["lc_id"]
        now = int(time.time())
        lc["last_record_update"] = now

        # 1. Already scraped this exact LewdCorner thread -> update in place,
        #    but ONLY if it's actually new/changed. Comparison is against
        #    thread_updated (the feed's `timestamp` field, i.e. real
        #    last-activity), not blind re-writes -- previously every re-seen
        #    lc_id was unconditionally treated as "updated" regardless of
        #    whether anything changed, which both wasted writes and meant
        #    the early-stop check in run() almost never actually triggered.
        #    Refresh the atlas fields ONLY if no other source owns this game
        #    (so we never clobber an F95/dlsite/sxs-owned atlas row).
        existing_atlas_id = getAtlasIdByLcId(lc_id, db_type)
        if existing_atlas_id:
            item_ts = int(lc.get("thread_updated") or 0)
            if last_updates is not None:
                stored_ts = int(last_updates.get(str(lc_id), 0))
            else:
                stored_ts = getLcThreadUpdated(lc_id, db_type)
            if not full and item_ts <= stored_ts:
                return "skipped"
            if not atlasOwnedByOtherSource(existing_atlas_id, db_type):
                atlas["last_record_update"] = now
                updateAtlasById(existing_atlas_id, self._clean(atlas), db_type)
            lc["atlas_id"] = existing_atlas_id
            UpdatetableDynamic("lewdcorner", self._clean(lc), db_type)
            return "updated"

        # If this LC thread is already parked in the review queue awaiting a
        # human decision, leave it there -- don't insert a new atlas row or a
        # lewdcorner row behind the reviewer's back. Refresh the queued snapshot
        # so the reviewer sees current data, then move on.
        if isLcInReviewQueue(lc_id, db_type):
            self._enqueue(item, atlas, lc, kind=None, candidates=None,
                          db_type=db_type, refresh_only=True)
            return "queued"

        # 2. Not seen before as an lc_id, and not queued. Decide how it maps to
        #    atlas by COUNTING exact id_name matches -- the old code used a
        #    LIMIT 1 lookup that silently linked to whichever row came back
        #    first when more than one matched. Now:
        #      exactly 1 exact match -> LINK (safe, unambiguous)
        #      >1 exact match        -> AMBIGUOUS -> review queue ("multi")
        #      0 exact matches       -> try fuzzy; if fuzzy candidates exist,
        #                               review queue ("fuzzy"); else brand new.
        exact_ids = findAtlasIdsByIdName(atlas["id_name"], db_type)

        if len(exact_ids) == 1:
            linked_atlas_id = exact_ids[0]
            lc["atlas_id"] = linked_atlas_id
            UpdatetableDynamic("lewdcorner", self._clean(lc), db_type)
            print("  linked lc_id", lc_id, "-> existing atlas_id",
                  linked_atlas_id, atlas["title"])
            return "linked"

        if len(exact_ids) > 1:
            self._enqueue(item, atlas, lc, kind="multi",
                          candidates=exact_ids, db_type=db_type)
            print("  QUEUED (multi-match) lc_id", lc_id,
                  "-> candidates", exact_ids, atlas["title"])
            return "queued"

        # 0 exact matches -> look for fuzzy near-misses, then SCORE them.
        # An exact id_name miss doesn't prove the game is absent (site
        # formatting differs), so we score each candidate 0-100 (70% title /
        # 30% creator) and use the best:
        #     71-99 -> ambiguous, could be the same game  -> review queue
        #     <= 70 -> verified genuinely different game   -> add as new
        # No candidates at all also falls through to "add as new".
        fuzzy_ids = findFuzzyAtlasCandidates(
            atlas["short_name"], atlas["creator"], db_type)
        if fuzzy_ids:
            candidate_rows = getAtlasRowsByIds(fuzzy_ids, db_type)
            best_score, best_id = _best_candidate(
                atlas["title"], atlas["creator"], candidate_rows)
            if best_score > LC_REVIEW_FLOOR:
                self._enqueue(item, atlas, lc, kind="fuzzy",
                              candidates=fuzzy_ids, db_type=db_type,
                              score=best_score)
                print("  QUEUED (fuzzy", str(best_score) + "%) lc_id", lc_id,
                      "-> best atlas_id", best_id, "of", fuzzy_ids,
                      atlas["title"])
                return "queued"
            # best_score <= LC_REVIEW_FLOOR: not a real match -> new game.
            print("  fuzzy best only", str(best_score) + "% (<= "
                  + str(LC_REVIEW_FLOOR) + "); adding as new:", atlas["title"])

        # 3. Genuinely new -> insert a new atlas row + a new lewdcorner row.
        atlas["last_record_update"] = now
        new_atlas_id = insertAtlas(self._clean(atlas), db_type)
        lc["atlas_id"] = new_atlas_id
        UpdatetableDynamic("lewdcorner", self._clean(lc), db_type)
        print("  added lc_id", lc_id, "-> atlas_id", new_atlas_id, atlas["title"])
        return "added"

    def _enqueue(self, item, atlas, lc, kind, candidates,
                 db_type=None, refresh_only=False, score=None):
        """Park an ambiguous LC item in lc_review_queue for manual resolution.

        Stores enough to (a) show the reviewer the game, and (b) actually
        perform the link once resolved: the cleaned lc + atlas records are
        serialised so the reconciler can write the real lewdcorner row later
        without re-scraping. candidate atlas_ids are stored as CSV.

        `score` (int 0-100) is the best fuzzy similarity that routed this item
        here; stored in match_score so the reviewer sees how close it was. It
        is only meaningful for kind="fuzzy" -- "multi" rows are exact id_name
        collisions, not similarity-based, so they leave match_score NULL.
        """
        now = int(time.time())
        lc_id = lc["lc_id"]
        row = {
            "lc_id": lc_id,
            "title": atlas.get("title") or "",
            "creator": atlas.get("creator") or "",
            "version": atlas.get("version") or "",
            "id_name": atlas.get("id_name") or "",
            "short_name": atlas.get("short_name") or "",
            "site_url": lc.get("site_url") or "",
            "banner_url": lc.get("banner_url") or "",
            "lc_payload": json.dumps(self._clean(lc)),
            "atlas_payload": json.dumps(self._clean(atlas)),
            "last_seen": now,
            "first_seen": now,
        }
        if not refresh_only:
            row["match_kind"] = kind
            row["candidate_ids"] = ",".join(str(c) for c in (candidates or []))
            if score is not None:
                row["match_score"] = int(score)
        enqueueLcReview(row, db_type)

    @staticmethod
    def _clean(d):
        out = {}
        for k, v in d.items():
            if isinstance(v, str):
                v = _normalize_ws(v)
            if v not in ("", None):
                out[k] = v
        return out


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
