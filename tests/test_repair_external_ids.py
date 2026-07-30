"""
Tests for tools/maintenance/repair_external_ids.py.

The DB layer is stubbed, so this runs anywhere -- no MySQL, no network.

    python tests/test_repair_external_ids.py
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tools.maintenance.repair_external_ids as repair

# atlas_id, title, external_ids (dict, or a raw string for the broken case), f95_id
FAKE_ROWS = [
    (1, "Everybody Lies", {"patreon": "c", "twitter": "EBL_VN"}, 300521),
    (2, "Eternum", {"patreon": "Caribdis", "vndb_id": "v31929"}, 93340),
    (3, "New cw Link", {"patreon": "cw"}, 111111),
    (4, "Route Twitter", {"twitter": "i", "patreon": "gooddev"}, 222222),
    (5, "FB Group Link", {"facebook": "groups"}, 333333),
    (6, "Ko-fi Shop Link", {"kofi": "s"}, 444444),
    (7, "LewdCorner Only", {"patreon": "c"}, None),
    (8, "Legit c-name", {"patreon": "coolgamedev"}, 555555),
    (9, "Broken JSON", "{not json", 666666),
    (10, "No ids at all", {}, 777777),
    (11, "Uppercase route", {"patreon": "C"}, 888888),
]

# Every row above that genuinely holds a route name rather than an account id.
EXPECTED_BAD = {
    1: {"patreon": "c"},
    3: {"patreon": "cw"},
    4: {"twitter": "i"},
    5: {"facebook": "groups"},
    6: {"kofi": "s"},
    7: {"patreon": "c"},
    11: {"patreon": "C"},
}


def _install_stubs():
    """Point the tool at FAKE_ROWS and capture enqueue calls."""
    queued = []

    def fake_run(sql, params=(), commit=False, fetch=None, dict_cursor=False):
        rows = []
        for atlas_id, title, ext, f95_id in FAKE_ROWS:
            raw = ext if isinstance(ext, str) else json.dumps(ext)
            rows.append({"atlas_id": atlas_id, "title": title,
                         "external_ids": raw, "f95_id": f95_id})
        return rows

    def fake_enqueue(f95_id, requested_by=None, priority=None, db_type=None):
        queued.append((f95_id, priority))
        return len(queued)

    repair._run = fake_run
    repair.enqueueF95Refresh = fake_enqueue
    return queued


def test_detects_exactly_the_route_values():
    _install_stubs()
    bad, scanned, unparseable = repair.find_bad_rows()
    found = {r["atlas_id"]: r["hits"] for r in bad}
    assert found == EXPECTED_BAD, f"\ngot  {found}\nwant {EXPECTED_BAD}"
    assert scanned == len(FAKE_ROWS)
    assert unparseable == 1, "the malformed JSON row should be counted, not raise"


def test_real_slugs_are_not_flagged():
    """The near-misses matter most: these must never be reported."""
    _install_stubs()
    bad, _, _ = repair.find_bad_rows()
    flagged = {r["atlas_id"] for r in bad}
    for atlas_id in (2, 8, 10):
        assert atlas_id not in flagged, f"row {atlas_id} wrongly flagged"


def test_platform_filter():
    _install_stubs()
    bad, _, _ = repair.find_bad_rows(platforms=["patreon"])
    assert {r["atlas_id"] for r in bad} == {1, 3, 7, 11}
    bad, _, _ = repair.find_bad_rows(platforms=["kofi", "facebook"])
    assert {r["atlas_id"] for r in bad} == {5, 6}


def test_report_renders_and_separates_orphans():
    _install_stubs()
    bad, scanned, unparseable = repair.find_bad_rows()
    buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = buf
    try:
        repair.report(bad, scanned, unparseable)
    finally:
        sys.stdout = real_stdout
    text = buf.getvalue()
    assert "7 row(s) hold a URL route" in text, text
    # atlas 7 has no f95_zone row, so only 6 are refreshable
    assert "6 can be fixed by re-scraping" in text, text
    assert "LewdCorner Only" in text, text
    assert "unparseable" in text, text


def test_enqueue_skips_rows_with_no_f95_id():
    queued = _install_stubs()
    bad, _, _ = repair.find_bad_rows()
    repair.enqueue(bad)
    assert sorted(f for f, _ in queued) == \
        [111111, 222222, 300521, 333333, 444444, 888888], queued
    # 7 bad rows, but only 6 queued -- the LewdCorner-only one can't be refreshed
    assert len(queued) == 6


def test_enqueue_respects_limit_and_priority():
    queued = _install_stubs()
    bad, _, _ = repair.find_bad_rows()
    repair.enqueue(bad, limit=2, priority=10)
    assert len(queued) == 2, queued
    assert all(p == 10 for _, p in queued), queued


def test_report_is_clean_when_nothing_is_wrong():
    def fake_run(*a, **k):
        return [{"atlas_id": 1, "title": "Fine",
                 "external_ids": json.dumps({"patreon": "Caribdis"}),
                 "f95_id": 1}]
    repair._run = fake_run
    bad, scanned, unparseable = repair.find_bad_rows()
    assert bad == []
    buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = buf
    try:
        repair.report(bad, scanned, unparseable)
    finally:
        sys.stdout = real_stdout
    assert "No rows hold" in buf.getvalue()


def test_csv_output(tmp_path=None):
    import csv
    import tempfile
    _install_stubs()
    bad, _, _ = repair.find_bad_rows()
    path = os.path.join(tempfile.mkdtemp(), "bad.csv")
    buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = buf
    try:
        repair.write_csv(bad, path)
    finally:
        sys.stdout = real_stdout
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 7, rows
    assert {r["platform"] for r in rows} == {"patreon", "twitter", "facebook", "kofi"}
    everybody = [r for r in rows if r["atlas_id"] == "1"][0]
    assert everybody["stored_value"] == "c"
    assert everybody["f95_id"] == "300521"


# --------------------------------------------------------------- refetch mode
# The normal scraper will not clear external_ids: f95.py does
#     ext = d.get("external_ids", {})
#     if ext: atlas["external_ids"] = json.dumps(ext)
# and an empty dict is falsy, so a page with no external ids leaves the stored
# value alone. Right for a crawl -- a partial fetch must not blank good data --
# but it means a false positive can never be repaired by a refresh. --refetch is
# the one path allowed to clear, and only when the fetch actually SUCCEEDED.

REFETCH_ROWS = [
    # atlas_id, external_ids, f95_id, what the stubbed page returns
    (880001, {"patreon": "c", "discord": "keepme"}, 880001, {"patreon": "real"}),
    (880002, {"patreon": "c"}, 880002, {}),                    # false positive
    (880003, {"patreon": "c", "discord": "keepme"}, 880003, None),  # fetch fails
    (880004, {"patreon": "c", "discord": "keepme"}, 880004, {}),    # prune vs clear
]


def _install_refetch_stubs(monkey_writes):
    """Stub the DB and the F95 agent; record every UPDATE instead of running it."""
    import json as _json

    def fake_run(sql, params=(), commit=False, fetch=None, dict_cursor=False):
        low = " ".join(str(sql).split()).lower()
        if low.startswith("update atlas set external_ids"):
            monkey_writes.append({"value": params[0], "atlas_id": params[2]})
            return None
        if "from f95_zone where f95_id" in low:
            return (f"https://f95zone.to/threads/x.{params[0]}/",)
        rows = []
        for atlas_id, ext, f95_id, _page in REFETCH_ROWS:
            rows.append({"atlas_id": atlas_id, "title": f"Case {atlas_id}",
                         "external_ids": _json.dumps(ext), "f95_id": f95_id})
        return rows

    class FakeAgent:
        def _fetch_detail(self, site_url, atlas, f95rec, retries=0):
            for atlas_id, _ext, _f95, page in REFETCH_ROWS:
                if site_url.endswith(f".{atlas_id}/"):
                    if page is None:
                        return False                 # fetch failed
                    if page:
                        atlas["external_ids"] = _json.dumps(page)
                    return True                      # parsed; may be empty
            return False

    import scraper.agents.f95 as f95mod
    import scraper.auth as authmod
    repair._run = fake_run
    f95mod.f95 = lambda *a, **k: FakeAgent()
    authmod.F95Session = lambda *a, **k: None


def _refetch(apply=True, clear_all=False, only=None):
    writes = []
    _install_refetch_stubs(writes)
    bad, _, _ = repair.find_bad_rows()
    if only:
        bad = [b for b in bad if b["atlas_id"] in only]
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        stats = repair.refetch_and_apply(bad, apply=apply, clear_all=clear_all)
    return writes, stats, buf.getvalue()


def test_refetch_replaces_when_the_page_has_ids():
    writes, stats, _ = _refetch(only={880001})
    assert len(writes) == 1, writes
    assert json.loads(writes[0]["value"]) == {"patreon": "real"}, writes
    assert stats["replace"] == 1, stats


def test_refetch_clears_a_false_positive():
    """The whole point: nothing on the page, so the stored value must go."""
    writes, stats, _ = _refetch(only={880002})
    assert len(writes) == 1, writes
    assert writes[0]["value"] is None, f"expected NULL, got {writes[0]['value']!r}"
    assert stats["prune"] == 1, stats


def test_refetch_never_writes_when_the_fetch_failed():
    """The safety rule. A failed fetch is indistinguishable from an empty page.

    Without this a transient 403 would wipe external ids across the library.
    """
    writes, stats, out = _refetch(only={880003})
    assert writes == [], f"a failed fetch must not write: {writes}"
    assert stats["failed"] == 1, stats
    assert "leaving the row untouched" in out, out


def test_refetch_keeps_unflagged_keys_by_default():
    writes, _, _ = _refetch(only={880004})
    assert json.loads(writes[0]["value"]) == {"discord": "keepme"}, writes


def test_clear_all_wipes_the_whole_column():
    writes, stats, out = _refetch(only={880004}, clear_all=True)
    assert writes[0]["value"] is None, writes
    assert stats["clear"] == 1, stats
    assert "CLEARING the column" in out, out


def test_refetch_dry_run_writes_nothing():
    writes, stats, out = _refetch(apply=False)
    assert writes == [], writes
    assert any(k.startswith("would_") for k in stats), stats
    assert "Add --apply to write" in out, out


def test_refetch_bumps_the_export_timestamp():
    """A corrected row that never re-exports leaves clients on the old value."""
    writes = []
    _install_refetch_stubs(writes)
    real_run = repair._run

    seen = []

    def spy(sql, params=(), commit=False, fetch=None, dict_cursor=False):
        if "update atlas set external_ids" in " ".join(str(sql).split()).lower():
            seen.append(" ".join(str(sql).split()).lower())
        return real_run(sql, params, commit, fetch, dict_cursor)

    repair._run = spy
    bad, _, _ = repair.find_bad_rows()
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        repair.refetch_and_apply([b for b in bad if b["atlas_id"] == 880002],
                                 apply=True)
    assert seen, "no UPDATE issued"
    assert "last_record_update" in seen[0], \
        f"the corrected row must be re-exported: {seen[0]}"


def test_refetch_skips_rows_with_no_f95_link():
    writes = []
    _install_refetch_stubs(writes)
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        stats = repair.refetch_and_apply(
            [{"atlas_id": 1, "title": "x", "f95_id": None, "hits": {"patreon": "c"},
              "external_ids": {}}], apply=True)
    assert writes == [], writes
    assert stats == {}, stats


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
