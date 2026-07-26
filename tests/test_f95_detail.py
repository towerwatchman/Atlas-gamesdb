"""
Regression tests for the F95 thread-detail parser, run against saved
fixtures (no network). Covers seven real threads with different layouts.

    python -m pytest tests/            # or:  python tests/test_f95_detail.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.agents.f95_detail import parse_thread_detail

FIX = os.path.join(os.path.dirname(__file__), "..", "scraper", "fixtures")

MIRROR_HOSTS = {"mega.nz", "pixeldrain.com", "gofile.io", "mixdrop.ag",
                "uploadhaven.com", "datanodes.to", "vikingfile.com",
                "mediafire.com"}


def _load(stem):
    with open(os.path.join(FIX, f"{stem}.html"), encoding="utf-8") as fh:
        return parse_thread_detail(fh.read())


def test_logged_out_is_gated():
    d = _load("eternum_loggedout")
    assert d["logged_in"] is False
    assert d["thread_id"] == "93340"
    assert d["version"] == "0.9.5 Public"
    assert d["censored"] == "No"
    assert d["os"].startswith("Windows")
    assert d["locked_link_count"] > 0
    assert d["external_ids"] == {}
    assert all(v is None for v in d["spoilers"].values())
    assert d["downloads"] == []          # all game mirrors are gated for guests


def test_logged_in_unlocks_everything():
    d = _load("eternum_loggedin")
    assert d["logged_in"] is True
    assert d["locked_link_count"] == 0
    assert d["developer"] == "Caribdis"
    assert d["external_ids"].get("vndb_id") == "v31929"
    assert d["external_ids"].get("itch_url") == "caribdis.itch.io"
    assert all(v is not None for v in d["spoilers"].values())
    # split columns
    assert d["downloads"] and d["extras"] and d["translations"]
    # extras type comes from the anchor text
    ex = {x["label"]: x["type"] for x in d["extras"]}
    assert ex["Walkthrough"] == "walkthrough"
    assert ex["Multi Mod"] == "mod"
    assert ex["Gallery Unlocker"] == "gallery_unlock"
    # game mirrors include masked links, stored verbatim
    masked = next(x for x in d["downloads"] if x["masked"])
    assert masked["url"].startswith("https://f95zone.to/masked/")
    # screenshots never land in any download column
    allitems = d["downloads"] + d["patches"] + d["extras"] + d["translations"]
    assert not any(x["url"].endswith((".jpg", ".png")) for x in allitems)
    assert len(d["screens"]) > 0
    # cover_url must be the dev's header image even though the dev named it
    # "..._f95zone_banner.png" -- a real user attachment, not stock chrome.
    assert d["cover_url"] == (
        "https://attachments.f95zone.to/2023/10/3018543_f95zone_banner.png"
    )
    # ...and that dev image must NOT also appear in the screenshots list.
    assert not any("3018543_f95zone_banner" in s for s in d["screens"])


def test_orphan_downloads_default_to_downloads():
    # Hard Lessons has NO "DOWNLOAD" header — it jumps straight to "Win/Linux:".
    # Those mirrors must land in downloads, NOT extras.
    d = _load("hardlessons")
    assert len(d["downloads"]) >= 3
    assert d["extras"] == [] and d["patches"] == [] and d["translations"] == []
    assert {x["group"] for x in d["downloads"]} >= {"Win/Linux", "Mac", "Android"}


def test_dik_interleaved_patches_split_out():
    # Being a DIK interleaves a Patch block between game-download blocks.
    d = _load("being_a_dik_loggedin")
    assert d["patches"]                                   # patches captured
    assert all(p["type"] == "patch" for p in d["patches"])
    assert not any(x["host"] in MIRROR_HOSTS for x in d["extras"])  # no leak
    # game downloads after the patch block are still downloads, not patches
    assert len(d["downloads"]) > len(d["patches"])
    assert d["external_ids"].get("steam_appid") == "1126320"


def test_patch_thread_links_captured():
    # Lost & Found / Double Perception list patches as F95 *thread* links
    # (not file hosts) — they must still be captured into `patches`.
    for stem, label in [("lostfound", "Wincest"),
                        ("doubleperception", "INCEST PATCH")]:
        d = _load(stem)
        labels = {p["label"] for p in d["patches"]}
        assert label in labels, (stem, labels)
        assert not any(x["host"] in MIRROR_HOSTS for x in d["extras"])


def test_chapter_threads_and_member_links():
    # Double Homework / Daughter for Dessert organise downloads by
    # Episode/Chapter, and credit contributors with @user (/members/) links.
    for stem, group_word in [("double_homework", "Episode"),
                            ("daughter_for_dessert", "Chapter")]:
        d = _load(stem)
        # chapter/episode groups land in downloads
        assert any(group_word in x["group"] for x in d["downloads"])
        # @user credit links (/members/) are never captured anywhere
        allitems = d["downloads"] + d["patches"] + d["extras"] + d["translations"]
        assert not any("/members/" in x["url"] for x in allitems)


def test_thread_updated_label_parsed():
    # "Thread Updated" is F95's own freshness date for the post, distinct
    # from last_thread_comment (latest reply) and our own bookkeeping
    # last_record_update (when we wrote the row).
    d = _load("eternum_loggedin")
    assert d["thread_updated"] == "2026-01-21"


def test_new_external_platforms_captured():
    # GOG, Bluesky, and the discordapp.com invite domain are all real links
    # in this dev-info line that were previously silently dropped.
    d = _load("being_a_dik_loggedin")
    assert d["external_ids"].get("gog_url") == "being_a_dik"
    assert d["external_ids"].get("bluesky") == "drpinkcake.bsky.social"
    assert d["external_ids"].get("discord") == "KyCc5E4"


def test_facebook_captured():
    d = _load("daughter_for_dessert")
    assert d["external_ids"].get("facebook") == "LoveJointCom"


def test_patreon_numeric_user_id_not_literal_user():
    # patreon.com/user?u=12345 has no slug; the old regex captured the
    # literal word "user" instead of anything identifying.
    d = _load("lostfound")
    assert d["external_ids"].get("patreon") == "19780656"


def test_support_widget_requires_matching_developer():
    # Hard Lessons has an f95-support-btns widget on the page, but it
    # belongs to a different user's reply (an unrelated dev sharing their
    # own Patreon/Discord), not the thread's credited developer (ADAM!).
    # It must NOT be absorbed into this game's external_ids.
    d = _load("hardlessons")
    assert d["external_ids"] == {}


def test_patreon_new_c_slug_url_format():
    """patreon.com/c/<creator> must yield the creator, not the literal "c".

    Patreon moved creator pages to /c/<slug> during 2024. The bare-slug regex
    captured whatever the first path segment was, so every thread that had been
    updated to the new link format stored a patreon id of "c" -- around 725
    games in the live database.
    """
    d = _load("everybody_lies")
    assert d["external_ids"].get("patreon") == "Everybody_Lies"


def test_everybody_lies_full_parse():
    # The rest of this thread must keep parsing, so a future change to the
    # patreon patterns can't quietly break the surrounding extraction.
    d = _load("everybody_lies")
    assert d["logged_in"] is True
    assert d["thread_id"] == "300521"
    assert d["version"] == "0.1"
    assert d["developer"] == "Yngvi Inc."
    assert d["external_ids"].get("twitter") == "EBL_VN"
    assert d["external_ids"].get("discord") == "dqyTbHTrZF"
    assert d["external_ids"].get("itch_url") == \
        "everybody-lies.itch.io/everybody-lies"
    assert len(d["downloads"]) == 4
    assert len(d["screens"]) == 9


def test_patreon_cw_variant_and_reply_scope():
    """A /cw/ link in a REPLY must not become this game's patreon id.

    This thread happens to contain patreon.com/cw/RenpyToolTotalTranslate in
    another member's signature. Only the opening post is in scope, so the
    game's own /c/ link is the one that wins.
    """
    d = _load("everybody_lies")
    assert d["external_ids"]["patreon"] != "RenpyToolTotalTranslate"


def test_steam_widget_embed_captured():
    """The Steam appid must come out of the embedded store widget.

    F95 threads frequently embed the Steam store widget instead of linking the
    store page. Three separate things stopped this being picked up:
      1. it is an <iframe>, and only <a href> elements were scanned;
      2. s9e media embeds are lazy, so the URL sits in
         data-s9e-mediaembed-src and there is no usable src attribute at all;
      3. the URL path is /widget/<appid>, not /app/<appid>.
    """
    d = _load("mutant_college")
    assert d["external_ids"].get("steam_appid") == "3291310"


def test_steam_curator_link_not_treated_as_appid():
    """store.steampowered.com/curator/<id> is not a game.

    This thread credits the developer with a curator link right next to the
    Developer label. A loose "steampowered.com/<route>/(\\d+)" pattern would
    store the curator id as the game's appid.
    """
    d = _load("mutant_college")
    assert d["external_ids"].get("steam_appid") != "44655465"


def test_steam_widget_in_a_reply_is_ignored():
    """A Steam widget outside the opening post is not this game's store page.

    Hard Lessons has a steamstore embed, but it belongs to a reply from another
    member, so it must not be absorbed. This is the counterpart to
    test_steam_widget_embed_captured -- together they pin that embed scanning
    respects post scope rather than sweeping the whole page.
    """
    import os
    with open(os.path.join(FIX, "hardlessons.html"), encoding="utf-8") as fh:
        raw = fh.read()
    assert 'data-s9e-mediaembed="steamstore"' in raw, \
        "fixture no longer contains the reply-side Steam widget this test covers"
    d = _load("hardlessons")
    assert "steam_appid" not in d["external_ids"]


def test_mutant_college_full_parse():
    d = _load("mutant_college")
    assert d["logged_in"] is True
    assert d["thread_id"] == "234103"
    assert d["version"] == "0.14.0"
    assert d["developer"] == "Space Samurai Games"
    assert d["external_ids"].get("patreon") == "SpaceSamuraiStudio"
    assert d["external_ids"].get("discord") == "BmQGS3smZn"
    assert len(d["downloads"]) == 4
    assert len(d["screens"]) == 9


def test_embed_url_prefers_lazy_attribute_and_fixes_protocol():
    from bs4 import BeautifulSoup
    from scraper.agents.f95_detail import _embed_url
    soup = BeautifulSoup(
        '<iframe data-s9e-mediaembed="steamstore" '
        'data-s9e-mediaembed-src="//store.steampowered.com/widget/1"></iframe>'
        '<iframe src="//example.com/x"></iframe>'
        '<iframe data-s9e-mediaembed-src="//a/1" src="//b/2"></iframe>'
        '<iframe></iframe>', "lxml")
    frames = soup.find_all("iframe")
    # protocol-relative URLs are normalised so urlparse sees a host
    assert _embed_url(frames[0]) == "https://store.steampowered.com/widget/1"
    assert _embed_url(frames[1]) == "https://example.com/x"
    # the lazy data- attribute wins over src
    assert _embed_url(frames[2]) == "https://a/1"
    assert _embed_url(frames[3]) == ""


# --- unit-level coverage of the classifier ---------------------------------
# The fixtures above only cover the URL shapes those five threads happen to
# use. These cases pin the shapes that broke, plus the near-misses that a
# careless fix would regress (a legitimate slug that merely STARTS with a
# reserved route word).

CLASSIFY_CASES = [
    # patreon: every generation of URL normalises to the bare slug
    ("https://www.patreon.com/c/Everybody_Lies", ("patreon", "Everybody_Lies")),
    ("https://www.patreon.com/cw/SomeCreator", ("patreon", "SomeCreator")),
    ("https://www.patreon.com/user?u=19780656", ("patreon", "19780656")),
    ("https://www.patreon.com/bePatron?u=19780656", ("patreon", "19780656")),
    ("https://patreon.com/join/DrPinkCake", ("patreon", "DrPinkCake")),
    ("https://patreon.com/Yngvi", ("patreon", "Yngvi")),
    ("https://patreon.com/c/Caribdis/posts", ("patreon", "Caribdis")),
    ("https://PATREON.COM/C/UpperCase", ("patreon", "UpperCase")),
    ("https://f95zone.to/masked/patreon.com/c/SomeDev", ("patreon", "SomeDev")),
    # site routes are not creators
    ("https://www.patreon.com/posts/dev-log-123456", None),
    ("https://www.patreon.com/home", None),
    # slugs that merely begin with a reserved word must still work
    ("https://patreon.com/coolgamedev", ("patreon", "coolgamedev")),
    ("https://patreon.com/cwilson", ("patreon", "cwilson")),
    ("https://patreon.com/userland", ("patreon", "userland")),
    ("https://patreon.com/mystudio", ("patreon", "mystudio")),
    # twitter / x
    ("https://x.com/EBL_VN", ("twitter", "EBL_VN")),
    ("https://x.com/i/status/123", None),
    ("https://twitter.com/intent/tweet?text=hi", None),
    ("https://x.com/ianDev", ("twitter", "ianDev")),
    # facebook
    ("https://facebook.com/LoveJointCom", ("facebook", "LoveJointCom")),
    ("https://facebook.com/groups/123456", None),
    ("https://facebook.com/profile.php?id=61550", ("facebook", "61550")),
    ("https://facebook.com/pagesOfGlory", ("facebook", "pagesOfGlory")),
    # ko-fi
    ("https://ko-fi.com/somedev", ("kofi", "somedev")),
    ("https://ko-fi.com/s/abc123", None),
    ("https://ko-fi.com/sarah", ("kofi", "sarah")),
    # subscribestar now also on .com
    ("https://subscribestar.adult/dev-name", ("subscribestar", "dev-name")),
    ("https://subscribestar.com/dev-name", ("subscribestar", "dev-name")),
    # steam: the widget embed carries the appid, other routes are not apps
    ("https://store.steampowered.com/app/1126320/Being_a_DIK/",
     ("steam_appid", "1126320")),
    ("//store.steampowered.com/widget/3291310", ("steam_appid", "3291310")),
    ("https://store.steampowered.com/widget/3291310", ("steam_appid", "3291310")),
    ("https://store.steampowered.com/curator/44655465", None),
    ("https://store.steampowered.com/bundle/12345", None),
    ("https://store.steampowered.com/sub/98765", None),
    ("https://store.steampowered.com/developer/spacesamurai", None),
    ("https://steamcommunity.com/app/1126320", ("steam_community", "1126320")),
    # untouched platforms, guarding against collateral damage
    ("https://vndb.org/v31929", ("vndb_id", "v31929")),
    ("https://caribdis.itch.io", ("itch_url", "caribdis.itch.io")),
    ("https://discord.gg/KyCc5E4", ("discord", "KyCc5E4")),
    ("https://store.steampowered.com/app/1126320/", ("steam_appid", "1126320")),
    ("https://www.gog.com/en/game/being_a_dik", ("gog_url", "being_a_dik")),
    ("https://bsky.app/profile/drpinkcake.bsky.social",
     ("bluesky", "drpinkcake.bsky.social")),
]


def test_classify_external_url_shapes():
    from scraper.agents.f95_detail import _classify_external
    wrong = []
    for url, expected in CLASSIFY_CASES:
        got = _classify_external(url)
        if got != expected:
            wrong.append(f"{url} -> {got}, expected {expected}")
    assert not wrong, "\n".join(wrong)


def test_bad_external_values_matches_the_patterns():
    """The repair tool's bad-value set must stay in step with the regexes.

    Anything listed as a reserved route has to actually be rejected by the
    classifier, otherwise the tool would flag rows the scraper still produces.
    """
    from scraper.agents.f95_detail import BAD_EXTERNAL_VALUES, _classify_external
    hosts = {"patreon": "https://patreon.com/{}",
             "facebook": "https://facebook.com/{}",
             "twitter": "https://x.com/{}",
             "kofi": "https://ko-fi.com/{}"}
    for kind, values in BAD_EXTERNAL_VALUES.items():
        for value in values:
            if not value or "." in value:
                continue          # profile.php etc. carry their own pattern
            got = _classify_external(hosts[kind].format(value))
            assert got is None or got[1].lower() != value, \
                f"{kind}: {value!r} is listed as a route but still classifies"


if __name__ == "__main__":
    test_logged_out_is_gated()
    test_logged_in_unlocks_everything()
    test_orphan_downloads_default_to_downloads()
    test_dik_interleaved_patches_split_out()
    test_patch_thread_links_captured()
    test_chapter_threads_and_member_links()
    test_thread_updated_label_parsed()
    test_new_external_platforms_captured()
    test_facebook_captured()
    test_patreon_numeric_user_id_not_literal_user()
    test_support_widget_requires_matching_developer()
    test_patreon_new_c_slug_url_format()
    test_everybody_lies_full_parse()
    test_patreon_cw_variant_and_reply_scope()
    test_classify_external_url_shapes()
    test_bad_external_values_matches_the_patterns()
    test_steam_widget_embed_captured()
    test_steam_curator_link_not_treated_as_appid()
    test_steam_widget_in_a_reply_is_ignored()
    test_mutant_college_full_parse()
    test_embed_url_prefers_lazy_attribute_and_fixes_protocol()
    print("all parser tests passed")
