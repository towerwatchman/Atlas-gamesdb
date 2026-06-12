"""
Regression tests for the F95 thread-detail parser, run against the two
saved fixtures (logged-out vs logged-in). No network required.

    python -m pytest tests/            # or:  python tests/test_f95_detail.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.agents.f95_detail import parse_thread_detail

FIX = os.path.join(os.path.dirname(__file__), "..", "scraper", "fixtures")


def _load(name):
    with open(os.path.join(FIX, f"eternum_{name}.html"), encoding="utf-8") as fh:
        return parse_thread_detail(fh.read())


def _load_named(stem):
    with open(os.path.join(FIX, f"{stem}.html"), encoding="utf-8") as fh:
        return parse_thread_detail(fh.read())


def test_logged_out_is_gated():
    d = _load("loggedout")
    assert d["logged_in"] is False
    assert d["thread_id"] == "93340"
    # guest sees the inline fields...
    assert d["version"] == "0.9.5 Public"
    assert d["censored"] == "No"
    assert d["os"].startswith("Windows")
    # ...but not the gated content
    assert d["locked_link_count"] > 0
    assert d["locked_spoiler_count"] > 0
    assert d["external_ids"] == {}
    assert all(v is None for v in d["spoilers"].values())


def test_logged_in_unlocks_everything():
    d = _load("loggedin")
    assert d["logged_in"] is True
    assert d["locked_link_count"] == 0
    assert d["locked_spoiler_count"] == 0
    assert d["developer"] == "Caribdis"
    assert d["external_ids"].get("vndb_id") == "v31929"
    assert d["external_ids"].get("itch_url") == "caribdis.itch.io"
    assert "patreon" in d["external_ids"]
    # spoiler sections now have content
    assert all(v is not None for v in d["spoilers"].values())
    # split lists: game mirrors / extras / translations, each non-empty
    assert d["downloads"] and d["extras"] and d["translations"]
    # nothing is duplicated across the three lists
    assert all(x["section"].lower() in ("download", "downloads") for x in d["downloads"])
    assert all(x["section"].lower() == "extras" for x in d["extras"])
    assert all(x["section"].lower().startswith("translation") for x in d["translations"])
    # extras carry the right normalised type
    ex = {x["label"]: x["type"] for x in d["extras"]}
    assert ex["Walkthrough"] == "walkthrough"
    assert ex["Multi Mod"] == "mod"
    assert ex["Gallery Unlocker"] == "gallery_unlock"
    # game mirrors include masked links, flagged as such
    assert any(x["host"] == "mega.nz" for x in d["downloads"])
    assert any(x["masked"] for x in d["downloads"])
    # masked URLs are preserved verbatim, not fabricated
    masked = next(x for x in d["downloads"] if x["masked"])
    assert masked["url"].startswith("https://f95zone.to/masked/")
    # screenshots are NOT swept into any download list
    assert not any(x["url"].endswith((".jpg", ".png"))
                   for x in d["downloads"] + d["extras"] + d["translations"])
    assert len(d["screens"]) > 0


def test_logged_out_has_no_gated_mirrors():
    # Public Extras/Translations thread links are visible to guests, but the
    # gated download mirrors (mega/mediafire/...) must NOT appear.
    d = _load("loggedout")
    assert d["downloads"] == []          # all game mirrors are gated
    assert not any(x["host"] in ("mega.nz", "mediafire.com", "mixdrop.ag")
                   for x in d["extras"] + d["translations"])


def test_dik_download_sections_not_leaked_to_extras():
    # Being a DIK has a "Patch" sub-group and Season blocks inside DOWNLOAD.
    # Those must stay in `downloads` (not flip the section into `extras`).
    d = _load_named("being_a_dik_loggedin")
    # extras must be real extras only — no bare mirror hosts leaking in
    mirror_hosts = {"mega.nz", "pixeldrain.com", "gofile.io", "mixdrop.ag",
                    "uploadhaven.com"}
    assert not any(x["host"] in mirror_hosts for x in d["extras"])
    assert {x["type"] for x in d["extras"]} <= {
        "walkthrough", "mod", "guide", "save", "gallery_unlock",
        "wallpaper_art", "soundtrack", "cheat", "patch", "other"}
    # patches are kept in downloads, typed patch
    assert any(x["type"] == "patch" for x in d["downloads"])
    # Steam app id captured (Being a DIK is on Steam)
    assert d["external_ids"].get("steam_appid") == "1126320"


if __name__ == "__main__":
    test_logged_out_is_gated()
    test_logged_in_unlocks_everything()
    test_logged_out_has_no_gated_mirrors()
    test_dik_download_sections_not_leaked_to_extras()
    print("all parser tests passed")
