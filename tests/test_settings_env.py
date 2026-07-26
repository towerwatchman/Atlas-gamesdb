"""
Tests for deploy settings coming from .env, and for the Settings tab behaving
sensibly about it.

Two real defects these lock down:

  * The Save button used to sit at the bottom of the scrolling field list --
    around y=1225 in a ~435px viewport, about 800px below the fold behind six
    multi-line pattern boxes. Edits got made and never saved, which looked
    exactly like "I changed it in the app and it didn't work". The footer is now
    outside the scroll area, and test_save_button_is_visible_without_scrolling
    checks it stays there.
  * env_sources() used to deep-copy the live settings dict, which by then held a
    Tk widget reference (the Deploy tab's path label). copy.deepcopy of a Tcl
    object raises, and the caller swallowed the exception, so every .env value
    was silently ignored. Widgets no longer go in the settings dict at all, and
    env_sources() probes a throwaway skeleton.

    python tests/test_settings_env.py
    xvfb-run -a python tests/test_settings_env.py     (headless)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import atlas_tools.runner as runner
import atlas_tools.settings as settings

ENV_KEYS = ("SFTP_HOST", "SFTP_PORT", "SFTP_USER", "SFTP_PASSWORD",
            "SFTP_KEY_PATH", "SFTP_AUTH", "SCRAPER_DIR", "ADMIN_SERVER_DIR",
            "ATLAS_ENV_FILE")


def _sandbox(env_text=None, deploy_json=None):
    """Point settings at a temp folder with an optional .env / deploy.json."""
    work = tempfile.mkdtemp()
    runner.app_root = lambda: work
    settings.app_root = lambda: work
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    if env_text is not None:
        with open(os.path.join(work, ".env"), "w", encoding="utf-8") as fh:
            fh.write(env_text)
    if deploy_json is not None:
        with open(os.path.join(work, "deploy.json"), "w", encoding="utf-8") as fh:
            json.dump(deploy_json, fh)
    return work


# --------------------------------------------------------------- layering
def test_defaults_when_nothing_is_configured():
    _sandbox()
    data = settings.load()
    assert data["connection"]["host"] == ""
    assert settings.env_sources(data) == {}


def test_env_supplies_the_four_requested_fields():
    _sandbox("SFTP_USER=deployer\nSFTP_PASSWORD=s3cret\n"
             "SCRAPER_DIR=/opt/atlas-scraper\n"
             "ADMIN_SERVER_DIR=/opt/atlas/server/admin\n")
    data = settings.load()
    assert data["connection"]["user"] == "deployer"
    assert data["connection"]["password"] == "s3cret"
    assert data["targets"]["python"]["remote"] == "/opt/atlas-scraper"
    assert data["targets"]["node"]["remote"] == "/opt/atlas/server/admin"


def test_password_without_key_selects_password_auth():
    _sandbox("SFTP_PASSWORD=s3cret\n")
    assert settings.load()["connection"]["auth"] == "password"


def test_key_path_stays_on_key_auth():
    _sandbox("SFTP_PASSWORD=s3cret\nSFTP_KEY_PATH=~/.ssh/id_ed25519\n")
    assert settings.load()["connection"]["auth"] == "key"


def test_explicit_sftp_auth_wins():
    _sandbox("SFTP_PASSWORD=s3cret\nSFTP_AUTH=key\n")
    assert settings.load()["connection"]["auth"] == "key"


def test_port_is_an_int_and_bad_values_are_ignored():
    _sandbox("SFTP_PORT=2222\n")
    port = settings.load()["connection"]["port"]
    assert port == 2222 and isinstance(port, int)
    _sandbox("SFTP_PORT=not-a-number\n")
    assert settings.load()["connection"]["port"] == 22


def test_env_file_quirks_are_handled():
    _sandbox('# a comment\n\nexport SFTP_HOST="quoted.example.com"\n'
             "SFTP_USER='single'\n"
             "SFTP_PASSWORD=has spaces and = signs\n")
    conn = settings.load()["connection"]
    assert conn["host"] == "quoted.example.com"
    assert conn["user"] == "single"
    assert conn["password"] == "has spaces and = signs"


def test_real_environment_beats_the_env_file():
    _sandbox("SFTP_HOST=from-file\n")
    os.environ["SFTP_HOST"] = "from-environment"
    try:
        assert settings.load()["connection"]["host"] == "from-environment"
    finally:
        os.environ.pop("SFTP_HOST", None)


def test_env_beats_deploy_json_but_json_fills_the_gaps():
    _sandbox("SFTP_USER=envuser\n",
             {"connection": {"host": "json-host", "user": "json-user"}})
    conn = settings.load()["connection"]
    assert conn["user"] == "envuser", "env must win"
    assert conn["host"] == "json-host", "json must still fill unset fields"


def test_blank_env_values_do_not_override():
    _sandbox("SFTP_HOST=\nSFTP_USER=\n",
             {"connection": {"host": "json-host"}})
    data = settings.load()
    assert data["connection"]["host"] == "json-host"
    assert settings.env_sources(data) == {}


def test_env_file_setting_can_point_elsewhere():
    work = _sandbox()
    other = os.path.join(work, "custom.env")
    with open(other, "w", encoding="utf-8") as fh:
        fh.write("SFTP_HOST=custom-host\n")
    with open(os.path.join(work, "deploy.json"), "w", encoding="utf-8") as fh:
        json.dump({"env_file": "custom.env"}, fh)
    assert settings.load()["connection"]["host"] == "custom-host"


def test_env_sources_reports_the_variable_names():
    _sandbox("SFTP_HOST=h\nSCRAPER_DIR=/x\n")
    src = settings.env_sources(settings.load())
    assert src["connection.host"] == "SFTP_HOST"
    assert src["targets.python.remote"] == "SCRAPER_DIR"


def test_env_sources_survives_unpickleable_values():
    """Regression: it used to deep-copy, and the live dict holds Tk widgets."""
    _sandbox("SFTP_HOST=h\n")

    class Unpickleable:
        def __deepcopy__(self, memo):
            raise TypeError("cannot deepcopy this")

    data = settings.load()
    data["targets"]["python"]["_widget"] = Unpickleable()
    assert settings.env_sources(data)["connection.host"] == "SFTP_HOST"


# ------------------------------------------------------------------- save
def test_save_does_not_write_env_controlled_values():
    _sandbox("SFTP_HOST=h\nSFTP_USER=u\nSFTP_PASSWORD=p\nSCRAPER_DIR=/x\n")
    data = settings.load()
    data["targets"]["python"]["include"] = ["api.py"]
    settings.save(data)
    with open(settings.path(), encoding="utf-8") as fh:
        raw = json.load(fh)
    assert raw["connection"]["password"] == "", "password leaked into deploy.json"
    assert raw["connection"]["host"] == ""
    assert raw["targets"]["python"]["remote"] == ""
    assert raw["targets"]["python"]["include"] == ["api.py"], \
        "non-env edits must still persist"
    # and the env values still come back on the next load
    fresh = settings.load()
    assert fresh["connection"]["password"] == "p"
    assert fresh["targets"]["python"]["remote"] == "/x"


def test_save_persists_everything_when_env_is_empty():
    _sandbox("")
    data = settings.load()
    data["connection"]["host"] = "typed-in-app"
    data["targets"]["node"]["remote"] = "/srv/admin"
    settings.save(data)
    fresh = settings.load()
    assert fresh["connection"]["host"] == "typed-in-app"
    assert fresh["targets"]["node"]["remote"] == "/srv/admin"


# -------------------------------------------------------------------- GUI
def _build_app(env_text=""):
    _sandbox(env_text)
    import tkinter as tk
    from atlas_tools.gui import App
    root = tk.Tk()
    root.geometry("1040x800")
    app = App(root)
    root.update_idletasks()
    root.update()
    app.nb.select(2)                     # Settings
    for _ in range(4):
        root.update_idletasks()
        root.update()
    return root, app


def _widgets(root):
    out = []

    def walk(widget):
        for child in widget.winfo_children():
            out.append(child)
            walk(child)

    walk(root)
    return out


def _settings_entries(app):
    """Plain text entries on the Settings tab only.

    ttk.Combobox subclasses ttk.Entry, so a naive isinstance sweep of the whole
    window also picks up the readonly dropdowns on the Run and Deploy tabs.
    """
    from tkinter import ttk
    return [w for w in _widgets(app._settings_fields_frame)
            if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox)]


def test_save_button_is_visible_without_scrolling():
    root, app = _build_app("SFTP_HOST=h\n")
    try:
        saves = [w for w in _widgets(root)
                 if w.winfo_class() == "TButton" and w.cget("text") == "Save"]
        assert saves, "no Save button"
        save = saves[0]
        assert save.winfo_ismapped(), "Save button is not mapped"
        offset = save.winfo_rooty() - root.winfo_rooty()
        assert 0 <= offset < root.winfo_height(), \
            f"Save button at y={offset} is outside the {root.winfo_height()}px window"
    finally:
        app.shutdown()
        root.destroy()


def test_env_controlled_fields_are_readonly_and_populated():
    root, app = _build_app("SFTP_HOST=atlas-gamesdb.com\nSFTP_USER=deployer\n"
                           "SCRAPER_DIR=/opt/atlas-scraper\n")
    try:
        assert app.s_vars["connection.host"].get() == "atlas-gamesdb.com"
        assert app.s_vars["targets.python.remote"].get() == "/opt/atlas-scraper"
        readonly = [w for w in _settings_entries(app)
                    if str(w.cget("state")) == "readonly"]
        assert readonly, "env-controlled fields must not be editable"
    finally:
        app.shutdown()
        root.destroy()


def test_fields_are_editable_when_env_is_silent():
    root, app = _build_app("")
    try:
        assert app._env_sources == {}
        readonly = [w for w in _settings_entries(app)
                    if str(w.cget("state")) == "readonly"]
        assert not readonly, "nothing should be locked when .env sets nothing"
    finally:
        app.shutdown()
        root.destroy()


def test_deploy_tab_labels_show_the_env_paths():
    root, app = _build_app("SCRAPER_DIR=/opt/atlas-scraper\n"
                           "ADMIN_SERVER_DIR=/opt/atlas/server/admin\n")
    try:
        assert "/opt/atlas-scraper" in app._target_labels["python"].cget("text")
        assert "/opt/atlas/server/admin" in app._target_labels["node"].cget("text")
    finally:
        app.shutdown()
        root.destroy()


def test_reload_picks_up_an_edited_env_without_restarting():
    root, app = _build_app("SFTP_HOST=first.example.com\n")
    try:
        assert app.s_vars["connection.host"].get() == "first.example.com"
        with open(os.path.join(runner.app_root(), ".env"), "w",
                  encoding="utf-8") as fh:
            fh.write("SFTP_HOST=second.example.com\nSFTP_USER=u2\n")
        app._reload_settings()
        root.update()
        assert app.s_vars["connection.host"].get() == "second.example.com"
        assert app.settings["connection"]["host"] == "second.example.com"
    finally:
        app.shutdown()
        root.destroy()


def test_saving_from_the_gui_keeps_the_password_out_of_deploy_json():
    root, app = _build_app("SFTP_HOST=h\nSFTP_PASSWORD=s3cret\n")
    try:
        app.s_vars["targets.python.local"].set(".")
        app._save_settings()
        root.update()
        with open(settings.path(), encoding="utf-8") as fh:
            raw = json.load(fh)
        assert raw["connection"]["password"] == ""
        # ...but the running app still has it, so a deploy would work
        assert app.settings["connection"]["password"] == "s3cret"
    finally:
        app.shutdown()
        root.destroy()


def test_settings_dict_stays_json_serialisable():
    """Tk widgets in the settings dict would break both save and env_sources."""
    root, app = _build_app("SFTP_HOST=h\n")
    try:
        json.dumps(app.settings)          # must not raise
    finally:
        app.shutdown()
        root.destroy()


def _run_all():
    gui_needed = "DISPLAY" in os.environ or sys.platform == "win32"
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = skipped = 0
    for name, fn in fns:
        needs_gui = name in (
            "test_save_button_is_visible_without_scrolling",
            "test_env_controlled_fields_are_readonly_and_populated",
            "test_fields_are_editable_when_env_is_silent",
            "test_deploy_tab_labels_show_the_env_paths",
            "test_reload_picks_up_an_edited_env_without_restarting",
            "test_saving_from_the_gui_keeps_the_password_out_of_deploy_json",
            "test_settings_dict_stays_json_serialisable",
        )
        if needs_gui and not gui_needed:
            skipped += 1
            print(f"skip  {name} (no display)")
            continue
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")
    total = len(fns) - skipped
    print(f"\n{total - failed}/{total} passed"
          + (f", {skipped} skipped (no display)" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
