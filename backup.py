"""
Rebuild a full master package (ignores the per-run update history).
Always runs against the production MySQL database.

    python backup.py
"""
from scraper.types.eTypes import database
from scraper.config import config
from scraper.utils.directory_manager import createDirectories
from scraper.utils.packager import packager
from scraper.utils.db import TruncateLocalUpdatesTable


def main():
    db_type = database.REMOTE          # packaging/backups are MySQL-only
    print(f"Backup -> MySQL @ {config.host(database.REMOTE.value)}")
    print("  env:", config.env_status())

    createDirectories(db_type)
    # Clear previous update records, then create a master (start_time=0).
    TruncateLocalUpdatesTable(db_type)
    packager.createPackage(db_type, 0)
    print("Master package created")


if __name__ == "__main__":
    main()
