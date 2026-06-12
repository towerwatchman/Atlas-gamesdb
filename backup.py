"""
Rebuild a full master package (ignores the per-run update history).

    python backup.py
"""
import time
from sys import platform

from scraper.types.eTypes import database
from scraper.config import config
from scraper.utils.packager import packager
from scraper.utils.db import TruncateLocalUpdatesTable


def main():
    db_type = config.resolve_db_type()
    if db_type == database.LOCAL:
        print(f"Running LOCAL  -> SQLite (data.db)   [DB_MODE={config.db_mode()}]")
    else:
        print(f"Running REMOTE -> MySQL @ {config.host(database.REMOTE.value)}   [DB_MODE={config.db_mode()}]")
    print("  env:", config.env_status())

    # Clear previous update records, then create a master (start_time=0).
    TruncateLocalUpdatesTable(db_type)
    packager.createPackage(db_type, 0)
    print("Master package created")


if __name__ == "__main__":
    main()
