"""
Main entry point.

Usage:
    python api.py [f95] [full] [dlsite] [package] [lewdcorner] [lc_full]
each optional arg is 'true'/'false' (positional, matching the old CLI).

Flow:
    1. pick LOCAL (Windows) vs REMOTE (Linux server) DB
    2. ensure output dirs + DB schema
    3. scrape enabled sources (F95 detail fetches are authenticated)
    4. build the downloadable package (base + daily update + backups)
"""
import sys
import time
from sys import platform

from scraper.types.eTypes import database
from scraper.config import config
from scraper.utils.directory_manager import createDirectories
from scraper.utils.db import CreateDatabase
from scraper.utils.packager import packager
from scraper.auth import F95Session
from scraper.agents.f95 import f95
from scraper.agents.dlsite import dlsite
from scraper.auth import LCSession
from scraper.agents.lewdcorner import lewdcorner


def _flag(idx, default):
    if len(sys.argv) > idx:
        return sys.argv[idx].lower() == "true"
    return default


def main():
    f95_enable = _flag(1, True)
    f95_full = _flag(2, False)          # re-fetch detail for every thread
    dlsite_enable = _flag(3, False)
    create_package = _flag(4, True)
    lc_enable = _flag(5, False)         # LewdCorner feed scrape
    lc_full = _flag(6, False)           # walk every feed page (vs. stop-early)

    start_time = time.time()

    db_type = config.resolve_db_type()
    if db_type == database.LOCAL:
        print(f"Running LOCAL  -> SQLite (data.db)   [DB_MODE={config.db_mode()}]")
    else:
        print(f"Running REMOTE -> MySQL @ {config.host(database.REMOTE.value)}   [DB_MODE={config.db_mode()}]")
    print("  env:", config.env_status())

    createDirectories(db_type)
    CreateDatabase(db_type)

    if f95_enable:
        print("Downloading from F95")
        f95(F95Session()).run(db_type, full_detail=f95_full)

    if dlsite_enable:
        print("Downloading from DLSITE")
        dlsite.updateCircleID(db_type, "pro")
        dlsite.updateCircleID(db_type, "maniax")

    if lc_enable:
        print("Downloading from LewdCorner")
        lewdcorner(LCSession()).run(db_type, full=lc_full)

    # Once scraping is done, build the downloadable package file.
    # Packaging is MySQL-only, so skip it on local/SQLite dev runs.
    if create_package:
        if db_type == database.REMOTE:
            print("Creating package")
            packager.createPackage(db_type, start_time)
        else:
            print("Packaging skipped (runs against MySQL only)")

    print("All updates complete")


if __name__ == "__main__":
    main()
