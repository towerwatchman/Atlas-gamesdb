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
