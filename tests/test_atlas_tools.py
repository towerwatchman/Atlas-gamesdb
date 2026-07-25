"""
Tests for the desktop front end: argv building, and the deploy file matcher
(the parent/child pipe protocol is covered by test_pipe.py).

    python -m pytest tests/test_atlas_tools.py -q
    python tests/test_atlas_tools.py            (no pytest needed)

None of these touch the database or the network.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from atlas_tools import registry
from atlas_tools.deploy import collect_files, matches


# --------------------------------------------------------------------- argv
def test_api_modes_expand_to_eight_positionals():
    for mode in registry.API_MODES:
        argv = registry.build_argv(registry.BY_ID["api"], {"mode": mode})
        assert len(argv) == 8, (mode, argv)
        assert all(a in ("true", "false") for a in argv), argv


def test_api_incremental_matches_documented_default():
    # README: `python api.py` == incremental
    argv = registry.build_argv(registry.BY_ID["api"],
                               {"mode": "Incremental (default)"})
    assert argv == ["true", "false", "false", "true",
                    "false", "false", "false", "false"]


def test_api_ts_only_matches_readme():
    # README: python api.py true false false true false false false true
    argv = registry.build_argv(registry.BY_ID["api"], {"mode": "Ts-only sweep"})
    assert argv == ["true", "false", "false", "true",
                    "false", "false", "false", "true"]


def test_api_custom_uses_checkboxes():
    values = {"mode": "Custom (use the checkboxes)", "f95_enable": True,
              "f95_full": True, "dlsite_enable": False, "create_package": False,
              "lc_enable": True, "lc_full": False, "f95_new_only": False,
              "f95_ts_only": False}
    argv = registry.build_argv(registry.BY_ID["api"], values)
    assert argv == ["true", "true", "false", "false",
                    "true", "false", "false", "false"]


def test_flags_only_emitted_when_true():
    task = registry.BY_ID["backfill_atlas_export"]
    assert registry.build_argv(task, {"apply": False, "all_linked": False}) == []
    assert registry.build_argv(task, {"apply": True, "all_linked": False}) == \
        ["--apply"]
    assert registry.build_argv(task, {"apply": True, "all_linked": True}) == \
        ["--apply", "--all-linked"]


def test_blank_values_are_dropped():
    task = registry.BY_ID["refresh_missing_tags"]
    assert registry.build_argv(task, {"dry_run": True, "limit": ""}) == \
        ["--dry-run"]
    assert registry.build_argv(task, {"dry_run": False, "limit": "25"}) == \
        ["--limit", "25"]


def test_positional_splits_on_whitespace():
    task = registry.BY_ID["refresh_game"]
    assert registry.build_argv(task, {"ids": "12345 67890  24680"}) == \
        ["12345", "67890", "24680"]


def test_value_map_produces_bare_flag():
    task = registry.BY_ID["refresh_worker"]
    assert registry.build_argv(task, {"mode": "Daemon (run until stopped)"}) == []
    assert registry.build_argv(
        task, {"mode": "Once (single item, then exit)"}) == ["--once"]
    assert registry.build_argv(
        task, {"mode": "Drain (everything pending, then exit)"}) == ["--drain"]


def test_conditional_params_are_not_emitted_for_other_subcommands():
    task = registry.BY_ID["reconcile_lc"]
    # cleanup takes nothing, even though defer/fuzzy fields hold values
    argv = registry.build_argv(task, {
        "cmd": "cleanup", "fuzzy_floor": "0.55", "fuzzy_auto": "0.9",
        "kind": "multi", "threshold": "0.8", "defer_floor": "0.55",
        "defer_dry": True})
    assert argv == ["cleanup"]

    argv = registry.build_argv(task, {
        "cmd": "defer", "fuzzy_floor": "0.55", "fuzzy_auto": "0.9",
        "kind": "multi", "threshold": "0.9", "defer_floor": "0.6",
        "defer_dry": True})
    assert argv[0] == "defer"
    assert "--threshold" in argv and "0.9" in argv
    assert "--floor" in argv and "0.6" in argv
    assert "--dry-run" in argv
    assert "--auto" not in argv          # fuzzy-only
    assert "--kind" not in argv          # queue-only


def test_queue_kind_all_emits_nothing():
    task = registry.BY_ID["reconcile_lc"]
    argv = registry.build_argv(task, {"cmd": "queue", "kind": "(all)"})
    assert argv == ["queue"]
    argv = registry.build_argv(task, {"cmd": "queue", "kind": "fuzzy"})
    assert argv == ["queue", "--kind", "fuzzy"]


def test_every_task_module_is_importable_and_has_main():
    import importlib
    for task in registry.TASKS:
        module = importlib.import_module(task.module)
        assert callable(getattr(module, "main", None)), task.module


def test_every_task_builds_argv_from_its_defaults():
    for task in registry.TASKS:
        values = {p.key: p.default for p in task.params}
        registry.build_argv(task, values)      # must not raise
        assert registry.preview(task, values).startswith("python ")


# ------------------------------------------------------------------- globbing
def test_double_star_crosses_separators():
    assert matches("scraper/utils/db.py", "scraper/**/*.py")
    assert matches("scraper/db.py", "scraper/**/*.py")
    assert not matches("tools/db.py", "scraper/**/*.py")


def test_leading_double_star_matches_at_root_too():
    # The bug fnmatch has: '**/__pycache__/**' must match a top-level hit.
    assert matches("__pycache__/x.pyc", "**/__pycache__/**")
    assert matches("scraper/__pycache__/x.pyc", "**/__pycache__/**")
    assert matches("a/b/c/__pycache__/x.pyc", "**/__pycache__/**")


def test_single_star_does_not_cross_separators():
    assert matches("web/src/App.jsx", "web/src/*")
    assert not matches("web/src/pages/Home.jsx", "web/src/*")


def test_exact_names():
    assert matches("api.py", "api.py")
    assert not matches("tools/api.py", "api.py")


def test_collect_files_respects_excludes(tmp_path=None):
    import shutil
    import tempfile
    root = tempfile.mkdtemp()
    try:
        for rel in ["api.py", "scraper/db.py", "scraper/__pycache__/db.pyc",
                    "scraper/fixtures/page.html", "tools/x/y.py", "notes.txt"]:
            p = os.path.join(root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write("x")

        got = collect_files(
            root,
            include=["api.py", "scraper/**/*.py", "tools/**/*.py"],
            exclude=["**/__pycache__/**", "scraper/fixtures/**"])
        assert got == ["api.py", "scraper/db.py", "tools/x/y.py"], got
    finally:
        shutil.rmtree(root)


def test_collect_files_expands_bare_folder_name():
    import shutil
    import tempfile
    root = tempfile.mkdtemp()
    try:
        for rel in ["sql/001.sql", "sql/nested/002.sql", "other.txt"]:
            p = os.path.join(root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write("x")
        got = collect_files(root, include=["sql"], exclude=[])
        assert got == ["sql/001.sql", "sql/nested/002.sql"], got
    finally:
        shutil.rmtree(root)


def _run_all():
    """Run every test without pytest."""
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
        else:
            print(f"ok    {name}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
