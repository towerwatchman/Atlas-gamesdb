"""
Regression tests for the F95 thread-detail parser, run against saved
fixtures (no network). Covers five real threads with different layouts.

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


if __name__ == "__main__":
    test_logged_out_is_gated()
    test_logged_in_unlocks_everything()
    test_orphan_downloads_default_to_downloads()
    test_dik_interleaved_patches_split_out()
    test_patch_thread_links_captured()
    test_chapter_threads_and_member_links()
    print("all parser tests passed")
