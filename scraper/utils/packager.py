from scraper.utils.db import *
from deepdiff import DeepDiff
from scraper.utils.directory_manager import *
from scraper.utils.db import *
from datetime import datetime
import json
import time


class packager:
    def __init__(self) -> None:
        pass

    def createPackage(type):
        folder = "C:\packages"
        if type == database.LOCAL:
            folder = "C:\packages"
        if type == database.REMOTE:
            folder = "/var/www/html/packages"
        # Check if base package exist
        if not os.path.isfile(os.path.join(folder, "base.json")):
            print("Base file does not exist. Running for first time")
            with open(os.path.join(folder, "base.json"), "w") as outfile:
                outfile.write(json.dumps(packager.createBackup(type), default=str))
            # Insert record in database
            InsertUpdate(
                {
                    "file_name": os.path.join(folder, "base.json"),
                    "type": "base",
                    "last_update": datetime.utcnow(),
                }
            )

            print("Creating Daily Backup")
            with open(
                os.path.join(
                    folder,
                    "daily_backup_" + datetime.today().strftime("%Y%m%d") + ".json",
                ),
                "w",
            ) as outfile:
                outfile.write(json.dumps(packager.createBackup(type), default=str))

        else:
            # Get yesterdays backup and compare against todays
            print("Creating Daily Backup")
            with open(
                os.path.join(
                    folder,
                    "daily_backup_" + datetime.today().strftime("%Y%m%d") + ".json",
                ),
                "w",
            ) as outfile:
                outfile.write(json.dumps(packager.createBackup(type), default=str))

            current = json.load(
                open(
                    os.path.join(
                        folder,
                        "daily_backup_" + datetime.today().strftime("%Y%m%d") + ".json",
                    )
                )
            )
            previous = json.load(open(os.path.join))

    def createBackup(type):
        atlas_object = {"atlas": downloadBase(type, "atlas")}
        f95_object = {"f95_zone_data": downloadBase(type, "f95_zone_data")}
        data = {**atlas_object, **f95_object}
        return data
