"""
Tests for scraper/agents/lc_detail.py -- the LewdCorner thread-page parser.

Runs entirely against saved fixtures, no network.

    python -m pytest tests/test_lc_detail.py -q
    python tests/test_lc_detail.py

The three things most worth guarding, all of which are easy to get wrong and
silent when you do:

  * The opening post is NOT the first div.bbWrapper on the page -- the poster's
    signature block comes first in document order. Grabbing the first match
    yields a signature and an empty overview.
  * Screenshot URLs come from the lightbox ANCHOR's href, not the nested
    <img src>, which is a ~267px thumbnail. Reading img.src "works" and silently
    collects thumbnails, which is exactly what the API already gave us.
  * Download links are masked behind /masked/out?t=<jwt>; the payload has to be
    decoded or every host comes out as lewdcorner.com.
  * Developer, version, language, OS, both dates and the developer's support
    links live in the XenForo custom-field block above the post -- not in the
    post body, and not in F95-style inline labels, which LC doesn't have.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scraper.agents.lc_detail import (   # noqa: E402
    parse_lc_thread, unmask, extract_images, extract_downloads, extract_fields,
    parse_lc_date, _op_body,
)

FIX = os.path.join(os.path.dirname(__file__), "..", "scraper", "fixtures")

# Every fixture, with what the page actually says.
EXPECTED = {
    "lc_eternum": {
        "thread_id": "424",
        "title": "Eternum [v0.9.5 Public] [Caribdis]",
        "version": "0.9.0", "version_title": "v0.9.5 Public",
        "developer": "Caribdis",
        "prefixes": ["VN", "Ren'Py", "[HS]"],
        "min_tags": 20,
        "min_screens": 20,
        "min_downloads": 10,
    },
    "lc_bright_past": {
        "thread_id": "2117",
        "title": "Bright Past [v1.006] [Kosmos Games]",
        "version": "1.006", "version_title": "v1.006",
        "developer": "Kosmos Games",
        "prefixes": ["Ren'Py", "DAZ"],
        "min_tags": 30,
        "min_screens": 10,
        "min_downloads": 10,
    },
    "lc_school_tales": {
        "thread_id": "9631",
        "title": "School Tales [v10.7 ] [Kenzi Shinyuiki]",
        "version": "v10.7", "version_title": "v10.7",
        "developer": "Kenzi Shinyuiki",
        "prefixes": ["Ren'Py", "[Koikatsu]"],
        "min_tags": 12,
        "min_screens": 5,
        "min_downloads": 10,
    },
    "lc_village_of_love": {
        "thread_id": "23783",
        "title": "Village of Love [Demo] [TempAD]",
        "version": "Demo", "version_title": "Demo",
        "developer": "TempAD",
        "prefixes": ["[Unreal Engine]"],
        "min_tags": 10,
        "min_screens": 5,
        "min_downloads": 2,
    },
    "lc_desire_on_tap": {
        "thread_id": "21439",
        "title": "Desire on Tap [v0.2.0] [DesireOnTap]",
        "version": "0.2.0", "version_title": "v0.2.0",
        "developer": "DesireOnTap",
        "prefixes": ["Other", "Other"],
        "min_tags": 15,
        "min_screens": 3,
        "min_downloads": 4,
    },
}


def _html(name):
    with open(os.path.join(FIX, f"{name}.html"), encoding="utf-8") as fh:
        return fh.read()


def _load(name):
    return parse_lc_thread(_html(name))


# --------------------------------------------------------------- identity
def test_thread_id_and_login_state():
    for name, want in EXPECTED.items():
        d = _load(name)
        assert d["thread_id"] == want["thread_id"], name
        assert d["logged_in"] is True, name


def test_title_excludes_prefix_chips_and_the_type_icon():
    """The h1 holds a FontAwesome icon whose <title> reads "discussion".

    get_text() pulls that in, so every title came out as
    "discussion Bright Past [v1.006] [Kosmos Games]".
    """
    for name, want in EXPECTED.items():
        d = _load(name)
        assert d["title"] == want["title"], f"{name}: {d['title']!r}"
        assert "discussion" not in d["title"].lower(), name
        for prefix in want["prefixes"]:
            assert prefix not in d["title"], f"{name}: prefix {prefix} leaked into the title"


def test_prefixes():
    for name, want in EXPECTED.items():
        assert _load(name)["prefixes"] == want["prefixes"], name


def test_version_and_developer_come_from_the_custom_field_block():
    """LC keeps structured metadata in XenForo custom thread fields.

    Not the title brackets, which was the first guess, and not F95-style inline
    labels, which LC doesn't have at all.
    """
    for name, want in EXPECTED.items():
        d = _load(name)
        assert d["developer"] == want["developer"], f"{name}: {d['developer']!r}"
        assert d["version"] == want["version"], f"{name}: {d['version']!r}"
        assert d["version_field"] == want["version"], name
        assert d["version_title"] == want["version_title"], name


def test_a_stale_version_field_is_flagged_not_hidden():
    """The field and the title genuinely diverge.

    Eternum's field says 0.9.0 while its title says v0.9.5 Public -- posters
    update the title on every release and sometimes forget the field. Both values
    are kept and the disagreement is flagged so the choice can be revisited.
    """
    d = _load("lc_eternum")
    assert d["version_mismatch"] is True
    assert d["version_field"] == "0.9.0"
    assert d["version_title"] == "v0.9.5 Public"
    for name in ("lc_bright_past", "lc_school_tales", "lc_village_of_love",
                 "lc_desire_on_tap"):
        assert _load(name)["version_mismatch"] is False, name


def test_custom_fields_are_all_captured():
    d = _load("lc_eternum")
    f = d["fields"]
    for key in ("developer", "version", "language", "os", "donations",
                "release_date", "latest_update"):
        assert key in f, f"missing field {key}: {sorted(f)}"
    assert f["developer"]["label"] == "Developer Name"
    assert f["os"]["items"] == ["Windows", "Linux", "MacOS", "Android"]


def test_language_and_os():
    assert _load("lc_eternum")["language"] == "English"
    assert _load("lc_eternum")["os"] == ["Windows", "Linux", "MacOS", "Android"]
    assert _load("lc_village_of_love")["os"] == ["Windows"]
    # LC truncates long lists in the stored value itself; the missing entries are
    # nowhere else on the page, so this is as complete as it gets.
    assert _load("lc_desire_on_tap")["language"].endswith("+6")


def test_dates_parse_to_epoch():
    # scraper.utils.epoch.ConvertToUnixTime returns 0 for LC's "Mon D, YYYY".
    assert parse_lc_date("Jul 26, 2026") == 1785024000
    assert parse_lc_date("Nov 1, 2018") == 1541030400
    for junk in ["", None, "garbage", "2026-07-26", "Foo 1, 2020"]:
        assert parse_lc_date(junk) == 0, junk
    for name in EXPECTED:
        d = _load(name)
        assert d["release_date"] > 0, f"{name}: no release date"
        assert d["latest_update"] > 0, f"{name}: no latest update"
        assert d["latest_update"] >= d["release_date"], name


def test_developer_links_are_the_external_id_source():
    """They live in the `donations` custom field, NOT the post body.

    Body-only parsing produced an empty external_ids on every sample. These
    values match what is already stored for Eternum in production.
    """
    d = _load("lc_eternum")
    assert d["external_ids"]["patreon"] == "onceinalifetime"
    assert d["external_ids"]["subscribestar"] == "caribdis"
    assert d["external_ids"]["itch_url"] == "caribdis.itch.io"
    assert d["external_ids"]["discord"] == "caribdisgames"
    assert d["external_ids"]["twitter"] == "Caribdis_games"

    assert _load("lc_bright_past")["external_ids"]["patreon"] == "kosmosgames"
    assert _load("lc_school_tales")["external_ids"]["patreon"] == "KenziShinyuiki"


def test_a_steam_developer_page_is_not_an_app_id():
    # Village of Love's only support link is
    # store.steampowered.com/developer/TempAD -- a developer page, not a game.
    d = _load("lc_village_of_love")
    assert "steam_appid" not in d["external_ids"], d["external_ids"]


def test_other_games_links_are_captured():
    games = _load("lc_eternum")["other_games"]
    assert any(g["title"] == "Once in a lifetime" for g in games), games
    assert all(g["url"].startswith("http") for g in games)


def test_tags():
    for name, want in EXPECTED.items():
        tags = _load(name)["tags"]
        assert len(tags) >= want["min_tags"], f"{name}: only {len(tags)} tags"
        assert all(t == t.strip() and t for t in tags), name
        assert len(tags) == len(set(tags)), f"{name}: duplicate tags"


# --------------------------------------------------------------- overview
def test_overview_is_present_and_not_a_signature():
    """Guards the "first bbWrapper is a signature" trap.

    On these pages the poster's signature block is the FIRST div.bbWrapper in
    document order; the real post is the third. Taking the first match gives a
    handful of characters of social links.
    """
    for name in EXPECTED:
        d = _load(name)
        assert len(d["overview"]) > 120, \
            f"{name}: overview is {len(d['overview'])} chars — signature block?"
        assert "subscribestar" not in d["overview"].lower()[:60], name


def test_overview_does_not_repeat_its_own_heading():
    """next_elements walks INTO the <b> label, so its text was captured twice.

    One fixture also repeats the heading as plain text in the post itself
    ("<b>Overview:</b><br>Overview:<br>..."), which is in the source but isn't
    part of the description.
    """
    for name in EXPECTED:
        overview = _load(name)["overview"]
        assert not overview.lower().startswith("overview"), \
            f"{name}: {overview[:40]!r}"


def test_overview_stops_before_the_changelog_spoiler():
    # Bright Past has a long spoiler-wrapped changelog straight after the
    # overview; swallowing it would make the overview thousands of chars.
    d = _load("lc_bright_past")
    assert len(d["overview"]) < 3000, len(d["overview"])
    assert "v1.005" not in d["overview"], "changelog leaked into the overview"


# ----------------------------------------------------------------- images
def test_screens_are_full_size_attachments_not_thumbnails():
    """The whole point of scraping the page rather than trusting the API.

    Full size:  /attachments/<name>-jpg.<id>/
    Thumbnail:  /data/attachments/<bucket>/<id>-<hash>.jpg?hash=...
    """
    for name, want in EXPECTED.items():
        d = _load(name)
        assert len(d["screens"]) >= want["min_screens"], \
            f"{name}: only {len(d['screens'])} screens"
        for shot in d["screens"]:
            assert "/attachments/" in shot["url"], f"{name}: {shot['url']}"
            assert "/data/attachments/" not in shot["url"], \
                f"{name}: thumbnail captured as the full image: {shot['url']}"
            assert "?hash=" not in shot["url"], \
                f"{name}: that is a generated thumbnail URL: {shot['url']}"
            # The thumbnail is still recorded, just not as the image.
            if shot["thumb"]:
                assert "/data/attachments/" in shot["thumb"], f"{name}: {shot['thumb']}"


def test_banner_is_full_size_and_not_repeated_in_screens():
    for name in EXPECTED:
        d = _load(name)
        assert d["banner_url"], f"{name}: no banner"
        assert "/attachments/" in d["banner_url"], name
        assert "/data/attachments/" not in d["banner_url"], name
        # The banner shares an attachment id with no screenshot.
        ids = [re.search(r"\.(\d+)/?$", s["url"]) for s in d["screens"]]
        ids = {m.group(1) for m in ids if m}
        banner_id = re.search(r"\.(\d+)/?$", d["banner_url"])
        if banner_id:
            assert banner_id.group(1) not in ids, \
                f"{name}: the banner is also listed as a screenshot"


def test_screens_are_unique():
    for name in EXPECTED:
        urls = [s["url"] for s in _load(name)["screens"]]
        assert len(urls) == len(set(urls)), name


# -------------------------------------------------------------- downloads
def test_masked_links_are_decoded():
    """/masked/out?t=<base64 payload>.<signature> -> {"u": "<real url>"}."""
    masked = ("https://lewdcorner.com/masked/out?t=eyJ1IjoiaHR0cHM6Ly9kYXRhbm9kZXMu"
              "dG8vMmFhZ2I1and3M2hkL0JyaWdodF9QYXN0LTEuMDA2LXBjLnppcCJ9.CBb5olQijH1"
              "0MUnYqEMC-YAvCdHqC_AKHWawQHwopxY&r=aHR0cHM6Ly9sZXdkY29ybmVyLmNvbQ")
    assert unmask(masked) == \
        "https://datanodes.to/2aagb5jww3hd/Bright_Past-1.006-pc.zip"


def test_unmask_passes_through_what_it_cannot_read():
    for href in ["https://bzzhr.to/fm0i789yxuzr", "", None,
                 "https://lewdcorner.com/masked/out?t=not-base64!!",
                 "https://lewdcorner.com/masked/out"]:
        assert unmask(href) == href, href


def test_downloads_resolve_to_real_hosts():
    for name, want in EXPECTED.items():
        d = _load(name)
        assert len(d["downloads"]) >= want["min_downloads"], \
            f"{name}: only {len(d['downloads'])} downloads"
        for dl in d["downloads"]:
            assert dl["url"].startswith("http"), f"{name}: {dl['url']}"
            # If a masked link weren't decoded, every host would be lewdcorner.
            assert "lewdcorner.com" not in dl["host"], \
                f"{name}: undecoded masked link: {dl['url']}"
            assert "/masked/out" not in dl["url"], f"{name}: {dl['url']}"
            assert dl["host"], name


def test_downloads_carry_their_section_heading():
    d = _load("lc_bright_past")
    sections = {dl["section"] for dl in d["downloads"] if dl["section"]}
    assert sections, "no section headings captured"
    assert any("DOWNLOAD" in s.upper() for s in sections), sections


def test_platform_is_derived_from_the_heading():
    d = _load("lc_bright_past")
    win = [dl for dl in d["downloads"] if "windows" in dl["platforms"]]
    assert win, "no Windows downloads detected from 'DOWNLOAD Win/Linux'"
    assert any("linux" in dl["platforms"] for dl in d["downloads"])


def test_social_links_are_not_downloads():
    for name in EXPECTED:
        for dl in _load(name)["downloads"]:
            assert not re.search(r"patreon|subscribestar|discord|itch\.io|steam",
                                 dl["host"], re.I), f"{name}: {dl['host']}"


# --------------------------------------------------------------- external
def test_a_patreon_post_link_does_not_become_the_creator_id():
    """School Tales' post body links patreon.com/posts/... — a changelog.

    The creator id must come from the donations field ("KenziShinyuiki"), not
    from a route name in the body.
    """
    d = _load("lc_school_tales")
    assert d["external_ids"].get("patreon") == "KenziShinyuiki"
    assert d["external_ids"].get("patreon") not in ("posts",)


def test_external_ids_are_a_dict_of_strings():
    for name in EXPECTED:
        ext = _load(name)["external_ids"]
        assert isinstance(ext, dict), name
        for key, value in ext.items():
            assert isinstance(key, str) and isinstance(value, str), (name, key, value)


# ------------------------------------------------------------- robustness
def test_junk_input_does_not_raise():
    for html in ["", None, "<html></html>", "not html at all",
                 "<html><body><article class='message--post'></article></body></html>"]:
        d = parse_lc_thread(html)
        assert d["screens"] == [] and d["downloads"] == []
        assert d["title"] == "" or isinstance(d["title"], str)
        assert isinstance(d["external_ids"], dict)


def test_a_post_with_no_images_yields_no_screens():
    html = """<html data-content-key="thread-1"><body>
      <h1 class="p-title-value">Bare [v1] [Dev]</h1>
      <article class="message--post"><article class="message-body">
        <div class="bbWrapper"><b>Overview:</b><br>Some text.</div>
      </article></article></body></html>"""
    d = parse_lc_thread(html)
    assert d["banner_url"] is None
    assert d["screens"] == []
    assert d["overview"] == "Some text."
    assert d["version"] == "v1" and d["developer"] == "Dev"


def test_output_is_json_serialisable():
    # The agent stores screens/downloads as text, so anything non-serialisable
    # here would fail at the DB write rather than at parse time.
    for name in EXPECTED:
        json.dumps(_load(name))


# ------------------------------------------------------------ scrape output
# The agent prints a per-page summary so a run is visibly doing something. A
# thread fetch takes seconds, and previously nothing was printed on success, so
# a run looked stalled and there was no way to tell whether pages were being
# scraped at all.

def _capture(fn, *args):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)
    return buf.getvalue()


def test_scrape_summary_reports_what_was_found():
    from scraper.agents.lewdcorner import lewdcorner
    out = _capture(lewdcorner._describe_detail, _load("lc_eternum"), 2.3)
    assert "ok in 2.3s" in out, out
    for token in ("overview", "tags 23", "screens 27", "downloads 14", "banner yes"):
        assert token in out, f"{token!r} missing from:\n{out}"
    assert "developer='Caribdis'" in out, out
    assert "patreon=onceinalifetime" in out, out
    # Hosts are listed so an undecoded masked link (every host reading
    # "lewdcorner.com") is obvious at a glance.
    assert "hosts:" in out and "mega.nz" in out, out


def test_scrape_summary_shouts_when_the_field_block_is_missing():
    """LC layout change -> developer/version/links silently unavailable."""
    from scraper.agents.lewdcorner import lewdcorner
    detail = _load("lc_eternum")
    detail["fields"] = {}
    detail["external_ids"] = {}
    detail["banner_url"] = None
    out = _capture(lewdcorner._describe_detail, detail, 1.0)
    assert "no custom-field block found" in out, out
    assert "banner NO" in out, out
    assert "external: none found" in out, out


def test_scrape_summary_survives_an_empty_parse():
    from scraper.agents.lewdcorner import lewdcorner
    out = _capture(lewdcorner._describe_detail, parse_lc_thread(""), 0.2)
    assert "overview 0 chars" in out, out
    assert "screens 0" in out and "downloads 0" in out, out


def test_verbose_can_be_turned_off():
    import importlib
    import os as _os
    from scraper.agents import lewdcorner as mod
    prior = _os.environ.get("LC_VERBOSE")
    try:
        for value, expected in [("0", False), ("false", False), ("no", False),
                                ("1", True), ("", True)]:
            if value == "":
                _os.environ.pop("LC_VERBOSE", None)
            else:
                _os.environ["LC_VERBOSE"] = value
            importlib.reload(mod)
            assert mod._verbose() is expected, f"LC_VERBOSE={value!r}"
    finally:
        if prior is None:
            _os.environ.pop("LC_VERBOSE", None)
        else:
            _os.environ["LC_VERBOSE"] = prior
        importlib.reload(mod)


def _run_all():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
