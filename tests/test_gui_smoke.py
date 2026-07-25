"""
GUI smoke test: build the real window, walk every task, exercise the prompt bar
and the form's conditional fields, and confirm nothing raises.

Needs a display. On a headless box:

    xvfb-run -a python tests/test_gui_smoke.py
    xvfb-run -a python tests/test_gui_smoke.py --shot out.png   (needs ImageMagick)

This is not a substitute for clicking around on Windows, but it does catch the
class of error that only shows up once Tk actually lays the widgets out.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tkinter as tk

from atlas_tools import registry
from atlas_tools.gui import App


def build():
    root = tk.Tk()
    root.title("Atlas Tools")
    root.geometry("1040x760")
    app = App(root)
    root.update_idletasks()
    root.update()
    return root, app


def test_window_builds_and_every_task_selects():
    root, app = build()
    try:
        for task in registry.TASKS:
            app._select_task(task.id)
            root.update_idletasks()
            root.update()
            # The preview must always render something runnable-looking.
            assert app.preview.cget("text").startswith("python "), task.id
            # Every param must have produced a variable.
            for p in task.params:
                assert p.key in app._values, (task.id, p.key)
        print(f"    walked {len(registry.TASKS)} tasks")
    finally:
        app.shutdown()
        root.destroy()


def test_conditional_fields_hide_and_show():
    root, app = build()
    try:
        app._select_task("reconcile_lc")
        root.update()

        def mapped(key):
            return app._task_widgets[key].winfo_ismapped()

        app._values["cmd"].set("cleanup")
        root.update_idletasks(); root.update()
        assert not mapped("threshold"), "defer field visible under cleanup"
        assert not mapped("fuzzy_auto"), "fuzzy field visible under cleanup"

        app._values["cmd"].set("defer")
        root.update_idletasks(); root.update()
        assert mapped("threshold"), "defer threshold hidden under defer"
        assert not mapped("fuzzy_auto"), "fuzzy field visible under defer"

        app._values["cmd"].set("fuzzy")
        root.update_idletasks(); root.update()
        assert mapped("fuzzy_auto"), "fuzzy auto hidden under fuzzy"
        assert not mapped("threshold"), "defer threshold visible under fuzzy"
    finally:
        app.shutdown()
        root.destroy()


def test_api_mode_toggles_the_checkboxes():
    root, app = build()
    try:
        app._select_task("api")
        root.update()
        app._values["mode"].set("Incremental (default)")
        root.update_idletasks(); root.update()
        assert not app._task_widgets["f95_full"].winfo_ismapped()
        assert "true false false true" in app.preview.cget("text")

        app._values["mode"].set("Custom (use the checkboxes)")
        root.update_idletasks(); root.update()
        assert app._task_widgets["f95_full"].winfo_ismapped()
    finally:
        app.shutdown()
        root.destroy()


def test_prompt_bar_shows_and_hides():
    root, app = build()
    try:
        assert not app.prompt_bar.winfo_ismapped()
        app._show_prompt("    delete orphaned atlas_id 42? [y/N] ")
        root.update_idletasks(); root.update()
        assert app.prompt_bar.winfo_ismapped()
        # A y/N prompt should offer the two quick buttons.
        kids = app.prompt_quick.winfo_children()
        assert len(kids) == 2, kids
        assert {k.cget("text") for k in kids} == {"Yes", "No"}

        app._hide_prompt()
        root.update_idletasks(); root.update()
        assert not app.prompt_bar.winfo_ismapped()
    finally:
        app.shutdown()
        root.destroy()


def test_log_tagging_and_trim():
    root, app = build()
    try:
        app._log("Traceback (most recent call last):\n", app._tag_for("Traceback"))
        app._log("  + scraper/db.py   (new)\n", app._tag_for("  + x"))
        for i in range(200):
            app._log(f"line {i}\n")
        text = app.log.get("1.0", "end")
        assert "Traceback" in text
        assert "line 199" in text
    finally:
        app.shutdown()
        root.destroy()


def test_deploy_tab_targets_render():
    root, app = build()
    try:
        assert set(app.target_vars) == {"python", "node"}
        assert app.dry_var.get() is True, "dry run should default ON"
        assert app.env_var.get() is False, "env upload must default OFF"
    finally:
        app.shutdown()
        root.destroy()


def screenshot(path):
    """Render the window and grab it with ImageMagick's import."""
    import subprocess
    import time
    root, app = build()
    app._select_task("api")
    app._log("$ python api.py true false false true false false false false\n", "cmd")
    app._log("Running -> MySQL @ 46.202.176.220\n")
    app._log("  env: loaded /opt/atlas-scraper/.env\n")
    app._log("Downloading from F95\n")
    app._log("  page 1: 90 items, 12 new, 4 updated\n")
    app._log("  + Eternum [v0.8] -> refreshed\n", "ok")
    app._log("  !! thread 12345 detail fetch failed, retrying\n", "warn")
    app._log("Creating package\n")
    for _ in range(30):
        root.update_idletasks()
        root.update()
        time.sleep(0.01)
    time.sleep(0.6)
    root.update()
    subprocess.run(["import", "-window", "root", path], check=True)
    app.shutdown()
    root.destroy()
    print(f"    wrote {path}")


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
            import traceback
            traceback.print_exc()
        else:
            print(f"ok    {name}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--shot" in sys.argv:
        screenshot(sys.argv[sys.argv.index("--shot") + 1])
    else:
        raise SystemExit(_run_all())
