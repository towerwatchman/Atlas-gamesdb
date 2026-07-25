"""
Central configuration.

Secrets (DB credentials, F95 login) are read from environment variables,
which are loaded from a local .env file that is NOT committed to the repo.
See .env.example for the required keys.
"""
import os
import sys

from scraper.types.eTypes import database


def app_root():
    """Directory that .env / cookie files / relative paths resolve against.

    * normal checkout -> the project root (one level above this package)
    * PyInstaller exe -> the folder containing the .exe, NOT the temporary
      _MEIPASS extraction dir, so a user can drop a .env next to the exe and
      edit it without rebuilding.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve(path):
    """Absolutise a possibly-relative path against app_root()."""
    if not path:
        return path
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(app_root(), path)


_ENV_STATUS = "no-dotenv (python-dotenv not installed)"
_ENV_PATH = None
try:
    from dotenv import load_dotenv
    # Load .env from the app root. ATLAS_ENV_FILE overrides it outright, which
    # is how the GUI points at a .env somewhere else.
    _env_path = os.environ.get("ATLAS_ENV_FILE") or os.path.join(app_root(), ".env")
    _env_path = os.path.abspath(os.path.expanduser(_env_path))
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        _ENV_PATH = _env_path
        _ENV_STATUS = f"loaded {_env_path}"
    else:
        _ENV_STATUS = f"NO .env FOUND at {_env_path}"
except ImportError:
    # python-dotenv is optional; real environment variables still work.
    pass


def _require(key):
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable '{key}'. "
            f"Copy .env.example to .env and fill it in."
        )
    return val


class config:
    # ----- Database -----
    # MySQL only -- there is no SQLite/local fallback. Every run, dev or
    # production, talks to the same database server.
    @staticmethod
    def env_status():
        return _ENV_STATUS

    @staticmethod
    def resolve_db_type():
        # Kept for call-site compatibility (api.py / backup.py reference a
        # "db_type" enum value) but there is now only one database.
        return database.REMOTE

    @staticmethod
    def db_user():
        return _require("DB_USER")

    @staticmethod
    def db_password():
        return _require("DB_PASSWORD")

    @staticmethod
    def db_host():
        host = os.environ.get("DB_HOST")
        if host:
            return host
        # Back-compat with the old LOCAL/REMOTE split: DB_HOST_REMOTE was the
        # value actually used for every real MySQL connection (DB_HOST_LOCAL
        # was never read by the connection code). If you still have these
        # set, double-check DB_HOST_REMOTE is genuinely reachable from
        # wherever this runs -- "localhost" only works when this script runs
        # ON the database server itself. Set DB_HOST explicitly to silence
        # this fallback.
        legacy = os.environ.get("DB_HOST_REMOTE") or os.environ.get("DB_HOST_LOCAL")
        if legacy:
            return legacy
        return _require("DB_HOST")

    @staticmethod
    def host(_unused_db_type=None):
        # _unused_db_type kept only so existing call sites that pass
        # database.REMOTE.value etc. don't need to change.
        return config.db_host()

    @staticmethod
    def database():
        return os.environ.get("DB_NAME", "games")

    # ----- F95 login (dummy account) -----
    @staticmethod
    def f95_user():
        return _require("F95_USER")

    @staticmethod
    def f95_password():
        return _require("F95_PASSWORD")

    @staticmethod
    def env_file():
        """Absolute path of the .env that was loaded, or None."""
        return _ENV_PATH

    @staticmethod
    def app_root():
        return app_root()

    @staticmethod
    def f95_cookie_file():
        # Where the persisted session cookie is stored (kept out of the repo).
        # A relative F95_COOKIE_FILE resolves against the app root, not the
        # current working directory -- otherwise the cookie lands wherever the
        # process happened to be started from and gets re-created every run.
        return _resolve(os.environ.get("F95_COOKIE_FILE") or "f95_cookies.json")

    # ----- LewdCorner login (dummy account) -----
    # LewdCorner is XenForo, same as F95, so the auth model is identical:
    # a dummy account whose session cookie is reused across runs. The
    # latest-updates.php?api=1 feed is returned for an authenticated session.
    @staticmethod
    def lc_user():
        return _require("LC_USER")

    @staticmethod
    def lc_password():
        return _require("LC_PASSWORD")

    @staticmethod
    def lc_cookie_file():
        return _resolve(os.environ.get("LC_COOKIE_FILE") or "lc_cookies.json")

    # ----- Output -----
    @staticmethod
    def package_dir(_unused_db_type=None):
        dir_ = os.environ.get("PACKAGE_DIR")
        if dir_:
            return dir_
        # Back-compat: PACKAGE_DIR_LOCAL was never actually used (packaging
        # has always forced database.REMOTE -- see packager.py), so
        # PACKAGE_DIR_REMOTE is the value that matters.
        return os.environ.get("PACKAGE_DIR_REMOTE", "/var/www/html/packages")
