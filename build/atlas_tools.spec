# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for AtlasTools.exe.

Build it with build/build_exe.bat, or by hand from the PROJECT ROOT:

    pyinstaller build/atlas_tools.spec --noconfirm

Two things here are deliberate and worth not "tidying up":

1. ONEDIR, not onefile.
   The app runs each tool by re-invoking its own exe with --child. A onefile
   build re-extracts the entire bundle to a temp folder on every single
   invocation, so every task run would pay several seconds of unzip before
   printing anything. Onedir starts instantly. If you really want the single
   file, set ONEFILE = True below and accept that cost.

2. hiddenimports is generated FROM THE REGISTRY.
   The tools are imported dynamically via importlib, so PyInstaller's static
   analysis cannot see them and would silently ship a build where every task
   fails with ModuleNotFoundError. Deriving the list from registry.TASKS means
   adding a tool to the registry is all you ever have to do.
"""
import os
import sys

ONEFILE = False

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from atlas_tools.registry import TASKS  # noqa: E402

# --- every module the app might import at runtime --------------------------
task_modules = sorted({t.module for t in TASKS})

hiddenimports = task_modules + [
    # The scraper package, imported through the task modules.
    "scraper", "scraper.auth", "scraper.config",
    "scraper.agents.f95", "scraper.agents.f95_detail",
    "scraper.agents.dlsite", "scraper.agents.lewdcorner",
    "scraper.datatypes.data", "scraper.datatypes.record",
    "scraper.tables.base", "scraper.types.eTypes",
    "scraper.utils.db", "scraper.utils.directory_manager",
    "scraper.utils.epoch", "scraper.utils.packager", "scraper.utils.parser",

    # mysql-connector loads its auth plugin and its error strings by NAME at
    # runtime. Miss these and you get "Authentication plugin
    # 'mysql_native_password' cannot be loaded" only once you're on a real
    # server, never on your dev box.
    "mysql.connector.plugins.mysql_native_password",
    "mysql.connector.plugins.caching_sha2_password",
    "mysql.connector.plugins.sha256_password",
    "mysql.connector.locales",
    "mysql.connector.locales.eng",
    "mysql.connector.locales.eng.client_error",

    # BeautifulSoup picks its parser by string ("lxml"), so the backend is
    # invisible to static analysis.
    "lxml", "lxml.etree", "lxml._elementpath",
    "bs4", "bs4.builder", "bs4.builder._lxml", "bs4.builder._htmlparser",

    # Packaging / diffing / TLS.
    "lz4", "lz4.frame", "deepdiff", "truststore",

    # SFTP deploy. cryptography's backend is loaded indirectly.
    "paramiko", "paramiko.ed25519key", "paramiko.rsakey",
    "cryptography", "cryptography.hazmat.backends.openssl",
]

# --- things we definitely do not want in the bundle ------------------------
excludes = [
    # requirements.txt listed pandas but nothing imports it. Leaving it in
    # would add ~50MB (plus numpy) to the exe for no reason.
    "pandas", "numpy", "matplotlib", "scipy",
    "pytest", "_pytest", "IPython", "notebook",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "tkinter.test", "test",
]

a = Analysis(
    [os.path.join(ROOT, "atlas_tools", "__main__.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

_icon = os.path.join(SPECPATH, "atlas.ico")
icon = _icon if os.path.exists(_icon) else None

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="AtlasTools",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        # No console window: the GUI creates its own pipes for child tasks, so
        # nothing needs a terminal. See docs/DESKTOP_APP.md if you want a
        # console build for debugging.
        console=False,
        icon=icon,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="AtlasTools",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=icon,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False,
        upx=False,
        name="AtlasTools",
    )
