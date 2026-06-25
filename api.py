"""
Main entry point.

Usage:
    python api.py [f95] [full] [dlsite] [package] [lewdcorner] [lc_full] [f95_new_only] [f95_ts_only]
each optional arg is 'true'/'false' (positional, matching the old CLI).

Flow:
    1. ensure output dirs + DB schema (MySQL only)
    2. scrape enabled sources (F95 detail fetches are authenticated)
    3. build the downloadable package (base + daily update + backups)
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
    f95_new_only = _flag(7, False)      # API-only sweep: new/missing games only
    f95_ts_only = _flag(8, False)       # pure API sweep: ts/listing fields only,
                                         # never opens a detail page

    start_time = time.time()

    db_type = config.resolve_db_type()
    print(f"Running -> MySQL @ {config.host()}")
    print("  env:", config.env_status())

    createDirectories(db_type)
    CreateDatabase(db_type)

    if f95_enable:
        print("Downloading from F95")
        f95(F95Session()).run(
            db_type, full_detail=f95_full, new_only=f95_new_only,
            ts_only=f95_ts_only,
        )

    if dlsite_enable:
        print("Downloading from DLSITE")
        dlsite.updateCircleID(db_type, "pro")
        dlsite.updateCircleID(db_type, "maniax")

    if lc_enable:
        print("Downloading from LewdCorner")
        lewdcorner(LCSession()).run(db_type, full=lc_full)

    # Once scraping is done, build the downloadable package file.
    if create_package:
        print("Creating package")
        packager.createPackage(db_type, start_time)

    print("All updates complete")


if __name__ == "__main__":
    main()
