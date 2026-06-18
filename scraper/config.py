"""
Central configuration.

Secrets (DB credentials, F95 login) are read from environment variables,
which are loaded from a local .env file that is NOT committed to the repo.
See .env.example for the required keys.
"""
import os

from scraper.types.eTypes import database

_ENV_STATUS = "no-dotenv (python-dotenv not installed)"
try:
    from dotenv import load_dotenv
    # Load .env from the project root (two levels up from this file).
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_path = os.path.join(_root, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
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
    @staticmethod
    def env_status():
        return _ENV_STATUS

    @staticmethod
    def db_mode():
        # "remote" -> always MySQL, "local" -> always SQLite, "auto" -> by OS
        return os.environ.get("DB_MODE", "auto").lower()

    @staticmethod
    def resolve_db_type():
        import sys
        mode = config.db_mode()
        if mode == "remote":
            return database.REMOTE
        if mode == "local":
            return database.LOCAL
        # auto: SQLite on Windows dev box, MySQL on the Linux server
        return database.LOCAL if sys.platform == "win32" else database.REMOTE

    @staticmethod
    def db_user():
        return _require("DB_USER")

    @staticmethod
    def db_password():
        return _require("DB_PASSWORD")

    @staticmethod
    def host(db_type):
        # db_type: 1 / REMOTE -> remote host, else local
        remote = os.environ.get("DB_HOST_REMOTE", "localhost")
        local = os.environ.get("DB_HOST_LOCAL", "localhost")
        return remote if int(db_type) == 1 else local

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
    def f95_cookie_file():
        # Where the persisted session cookie is stored (kept out of the repo).
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.environ.get("F95_COOKIE_FILE", os.path.join(_root, "f95_cookies.json"))

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
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.environ.get("LC_COOKIE_FILE", os.path.join(_root, "lc_cookies.json"))

    # ----- Output -----
    @staticmethod
    def package_dir(db_type):
        if int(db_type) == 1:
            return os.environ.get("PACKAGE_DIR_REMOTE", "/var/www/html/packages")
        return os.environ.get("PACKAGE_DIR_LOCAL", "C:/packages")
