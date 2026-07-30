"""
Manual external links must reach the client, exactly once, on every export.

Needs a scratch MySQL/MariaDB with the schema applied and a .env pointing at it.
SKIPS cleanly when there isn't one, so it's safe to run anywhere.

    python tests/test_manual_link_export.py

It creates and removes its own atlas rows in the 9xxxx id range — point it at a
scratch database, never production.

Each test corresponds to a way links were being lost or duplicated:

  * a Steam link added as a URL had no ext_id, and only ext_id was read
  * an itch link added as an id had no url, and only url was read
  * a manual link duplicating a scraped one was listed twice under different
    keys, because "caribdis.itch.io" and "https://caribdis.itch.io" compared
    unequal
  * an atlas row whose last_record_update was 0 or NULL was excluded from a
    FULL export by `WHERE last_record_update > 0`, taking its links with it —
    and a full rebuild was precisely the thing that skipped it
  * a link of an unrecognised kind was dropped entirely
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BASE_ID = 990000

passed = 0
failures = []


def ok(name):
    global passed
    passed += 1
    print(f"ok    {name}")


def fail(name, err):
    failures.append(f"{name}: {err}")
    print(f"FAIL  {name}: {err}")


def test(name, fn):
    try:
        fn()
    except Exception as exc:                       # noqa: BLE001
        fail(name, f"{type(exc).__name__}: {exc}")
    else:
        ok(name)


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: got {a!r}, want {b!r}")


def main():
    try:
        from scraper.utils.db import (
            _run, downloadAtlasBase, downloadManualLinks,
        )
        _run("SELECT 1", (), fetch="one")
    except Exception as exc:                       # noqa: BLE001
        print(f"SKIP: no usable database ({type(exc).__name__}: "
              f"{str(exc)[:90]})")
        print("      point .env at a scratch database to run these.")
        return 0

    def reset():
        _run("DELETE FROM atlas_manual_links WHERE atlas_id >= %s",
             (BASE_ID,), commit=True)
        _run("DELETE FROM atlas WHERE atlas_id >= %s", (BASE_ID,), commit=True)

    def make_game(offset, last_update=1, external_ids=None):
        atlas_id = BASE_ID + offset
        _run(
            """INSERT INTO atlas
                 (atlas_id, title, id_name, short_name, creator,
                  last_record_update, external_ids)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (atlas_id, f"Export Test {offset}", f"EXPORTTEST{offset}_T",
             f"EXPORTTEST{offset}", "T", last_update,
             json.dumps(external_ids) if external_ids else None),
            commit=True)
        return atlas_id

    def add_link(atlas_id, kind, ext_id=None, url=None, label="t",
                 entry_type="game"):
        _run(
            """INSERT INTO atlas_manual_links
                 (atlas_id, kind, label, ext_id, url, entry_type,
                  added_by, added_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'test', 1)""",
            (atlas_id, kind, label, ext_id, url, entry_type), commit=True)

    def ext_for(atlas_id, start_time=0):
        for row in downloadAtlasBase(None, start_time):
            if row.get("atlas_id") == atlas_id:
                return json.loads(row["external_ids"] or "{}")
        return None

    # -------------------------------------------------------------- id/url
    def t_url_only_store_link():
        reset()
        aid = make_game(1)
        add_link(aid, "steam", url="https://store.steampowered.com/app/999002/")
        ext = ext_for(aid)
        assert ext is not None, "row missing from the export"
        assert "999002" in (ext.get("steam_appids") or []), ext
        assert_eq(ext.get("steam_appid"), "999002", "scalar")

    def t_id_only_itch_link():
        reset()
        aid = make_game(2)
        add_link(aid, "itch", ext_id="caribdis")
        ext = ext_for(aid)
        assert ext.get("itch") == ["https://caribdis.itch.io"], ext

    def t_id_only_store_link():
        reset()
        aid = make_game(3)
        add_link(aid, "gog", ext_id="some_gog")
        ext = ext_for(aid)
        assert_eq(ext.get("gog_ids"), ["some_gog"], "gog ids")
        assert_eq(ext.get("gog_id"), "some_gog", "gog scalar")

    def t_both_columns_agree():
        reset()
        aid = make_game(4)
        add_link(aid, "steam", ext_id="111",
                 url="https://store.steampowered.com/app/111/")
        assert_eq(ext_for(aid).get("steam_appids"), ["111"], "should appear once")

    # ------------------------------------------------------------ dedupe
    def t_manual_matching_scraped_is_not_duplicated():
        reset()
        aid = make_game(5, external_ids={"steam_appid": "1126320"})
        add_link(aid, "steam", ext_id="1126320")
        assert_eq(ext_for(aid).get("steam_appids"), ["1126320"], "one entry")

    def t_itch_url_forms_are_recognised_as_equal():
        """The scraped value is a bare host, the manual one a full URL."""
        reset()
        aid = make_game(6, external_ids={"itch_url": "caribdis.itch.io"})
        add_link(aid, "itch", url="https://caribdis.itch.io")
        add_link(aid, "itch", ext_id="caribdis")
        assert_eq(len(ext_for(aid).get("itch") or []), 1,
                  "three spellings of one page")

    def t_trailing_slash_and_www_are_ignored():
        reset()
        aid = make_game(7)
        add_link(aid, "custom", url="https://blog.example.com/")
        add_link(aid, "custom", url="https://www.blog.example.com")
        assert_eq(len(ext_for(aid).get("custom") or []), 1, "same page")

    def t_several_distinct_ids_all_survive():
        reset()
        aid = make_game(8, external_ids={"steam_appid": "100"})
        for appid in ("201", "202", "203"):
            add_link(aid, "steam", ext_id=appid)
        ext = ext_for(aid)
        assert_eq(ext.get("steam_appids"), ["201", "202", "203", "100"], "all kept")
        assert_eq(ext.get("steam_appid"), "201", "manual overrides the scalar")

    # -------------------------------------------------------- export scope
    def t_full_export_includes_untouched_rows():
        """The reported symptom: links missing after a full rebuild."""
        reset()
        aid = make_game(9, last_update=0)
        add_link(aid, "steam", ext_id="555555")
        ext = ext_for(aid, start_time=0)
        assert ext is not None, \
            "a row with last_record_update=0 was excluded from a FULL export"
        assert_eq(ext.get("steam_appids"), ["555555"], "link exported")

    def t_full_export_includes_null_timestamp_rows():
        reset()
        aid = make_game(10, last_update=0)
        _run("UPDATE atlas SET last_record_update = NULL WHERE atlas_id = %s",
             (aid,), commit=True)
        add_link(aid, "gog", ext_id="null_ts")
        ext = ext_for(aid, start_time=0)
        assert ext is not None, "NULL last_record_update excluded from a full export"
        assert_eq(ext.get("gog_ids"), ["null_ts"], "link exported")

    def t_delta_still_self_heals_old_rows():
        """A link added without bumping the timestamp still ships in a delta."""
        reset()
        aid = make_game(11, last_update=100)
        add_link(aid, "steam", ext_id="deltatest")
        ext = ext_for(aid, start_time=5000)     # row is older than the cutoff
        assert ext is not None, "row with links should be unioned into the delta"
        assert_eq(ext.get("steam_appids"), ["deltatest"], "link exported")

    def t_delta_excludes_unchanged_rows_without_links():
        reset()
        make_game(12, last_update=100)
        rows = downloadAtlasBase(None, 5000)
        assert all(r.get("atlas_id") != BASE_ID + 12 for r in rows), \
            "a delta must not include an unchanged row with no manual links"

    # ------------------------------------------------------------- misc
    def t_unknown_kind_is_not_dropped():
        reset()
        aid = make_game(13)
        add_link(aid, "epic", url="https://store.epicgames.com/p/thing")
        ext = ext_for(aid)
        assert ext.get("epic") == ["https://store.epicgames.com/p/thing"], ext

    def t_scraped_ids_are_preserved():
        reset()
        aid = make_game(14, external_ids={
            "patreon": "someone", "discord": "abc", "steam_appid": "77"})
        add_link(aid, "custom", url="https://example.com/")
        ext = ext_for(aid)
        assert_eq(ext.get("patreon"), "someone", "untouched key")
        assert_eq(ext.get("discord"), "abc", "untouched key")
        assert_eq(ext.get("steam_appid"), "77", "untouched when no manual steam")

    def t_malformed_stored_json_does_not_lose_the_link():
        reset()
        aid = make_game(15)
        _run("UPDATE atlas SET external_ids = %s WHERE atlas_id = %s",
             ("{not json", aid), commit=True)
        add_link(aid, "steam", ext_id="88")
        assert_eq(ext_for(aid).get("steam_appids"), ["88"], "link still exported")

    def t_row_without_links_is_untouched():
        reset()
        aid = make_game(16, external_ids={"steam_appid": "5"})
        ext = ext_for(aid)
        assert "steam_appids" not in ext, "no array without manual links"
        assert_eq(ext.get("steam_appid"), "5", "left alone")

    def t_backup_dump_includes_manual_links():
        """The archival dump stays raw, but must not be incomplete."""
        reset()
        aid = make_game(17)
        add_link(aid, "steam", ext_id="backup_me")
        rows = downloadManualLinks(None)
        assert any(r.get("atlas_id") == aid and r.get("ext_id") == "backup_me"
                   for r in rows), "manual links missing from the backup dump"

    for name, fn in [
        ("a store link added as a URL is exported", t_url_only_store_link),
        ("an itch link added as an id is exported", t_id_only_itch_link),
        ("a GOG link added as an id is exported", t_id_only_store_link),
        ("id and url on one link yields one entry", t_both_columns_agree),
        ("a manual id matching the scraped one is not duplicated",
         t_manual_matching_scraped_is_not_duplicated),
        ("itch url spellings collapse to one", t_itch_url_forms_are_recognised_as_equal),
        ("trailing slash and www. are ignored", t_trailing_slash_and_www_are_ignored),
        ("several distinct ids all survive", t_several_distinct_ids_all_survive),
        ("a FULL export includes rows never exported before",
         t_full_export_includes_untouched_rows),
        ("a FULL export includes NULL-timestamp rows",
         t_full_export_includes_null_timestamp_rows),
        ("a delta self-heals rows whose links were added later",
         t_delta_still_self_heals_old_rows),
        ("a delta still excludes unchanged rows without links",
         t_delta_excludes_unchanged_rows_without_links),
        ("an unrecognised kind is not dropped", t_unknown_kind_is_not_dropped),
        ("scraper-found ids are preserved", t_scraped_ids_are_preserved),
        ("malformed stored JSON does not lose the link",
         t_malformed_stored_json_does_not_lose_the_link),
        ("a row with no manual links is untouched", t_row_without_links_is_untouched),
        ("the backup dump includes manual links", t_backup_dump_includes_manual_links),
    ]:
        test(name, fn)

    reset()
    print(f"\n{passed}/{passed + len(failures)} passed")
    if failures:
        print("\nfailures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
