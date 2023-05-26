from scraper.utils.db import *
from deepdiff import DeepDiff
from scraper.utils.directory_manager import *
from scraper.utils.db import *
import datetime
import json
import time
import gzip


class packager:
    def __init__(self) -> None:
        pass

    def createPackage(type):
        folder = "C:/packages"
        if type == database.LOCAL:
            folder = "C:/packages"
        if type == database.REMOTE:
            folder = "/var/www/html/packages"
        # Check if base package exist
        if not os.path.isfile(os.path.join(folder, "base.update")):
            print("Base file does not exist. Running for first time")
            packager.createFile(
                type,
                folder,
                "base.update",
                "base",
                packager.createBaseUpdate(type),
                True,
            )
            print("Creating daily backup")
            packager.createBackup(type, folder)
        else:
            print("Creating daily backup")
            packager.createBackup(type, folder)
            print("Creating daily update")
            packager.createFile(
                type,
                folder,
                str(int(time.time())) + ".json",
                "daily",
                packager.createUpdate(type, folder),
                False,
            )

    def createFile(dbtype, folder, filenamne, backuptype, data, compress=False):
        file = os.path.join(
            folder,
            filenamne,
        )
        # bin = json.dumps(data, default=str)
        if compress:
            with open(
                file,
                "wb",
            ) as outfile:
                outfile.write(
                    gzip.compress(json.dumps(data, default=str).encode("utf-8"), 9)
                )
        else:
            with open(
                file,
                "w",
            ) as outfile:
                outfile.write(json.dumps(data, default=str))

        InsertUpdate(
            {
                "file_name": file,
                "type": backuptype,
                "last_update": datetime.datetime.utcnow(),
            },
            dbtype,
        )

    def createBaseUpdate(type):
        atlas_object = {"atlas": downloadBase(type, "atlas")}
        f95_object = {"f95_zone_data": downloadBase(type, "f95_zone_data")}
        data = {**atlas_object, **f95_object}
        return data

    def createBackup(type, folder):
        atlas_object = downloadBase(type, "atlas")
        f95_object = downloadBase(type, "f95_zone_data")
        packager.createFile(
            type,
            os.path.join(folder, "backup"),
            "atlas_backup_" + datetime.datetime.today().strftime("%Y%m%d") + ".json",
            "backup",
            atlas_object,
            False,
        )
        packager.createFile(
            type,
            os.path.join(folder, "backup"),
            "f95_backup_" + datetime.datetime.today().strftime("%Y%m%d") + ".json",
            "backup",
            f95_object,
            False,
        )

    def createUpdate(type, folder):
        atlas_current = json.load(
            open(
                os.path.join(
                    folder,
                    "backup",
                    "atlas_backup_"
                    + datetime.datetime.today().strftime("%Y%m%d")
                    + ".json",
                )
            )
        )
        atlas_previous = json.load(
            open(
                os.path.join(
                    folder,
                    "backup",
                    "atlas_backup_"
                    + (datetime.datetime.today() - datetime.timedelta(days=1)).strftime(
                        "%Y%m%d"
                    )
                    + ".json",
                )
            )
        )

        atlas_diff = DeepDiff(atlas_current, atlas_previous, group_by="id")

        # Write changes to file
        json_object = json.dumps(atlas_diff, default=str)

        return json_object
        # with open(str(int(time.time())) + ".json", "w") as outfile:
        #    outfile.write(json_object)
        #    print("file written: " + str(int(time.time())) + ".json")
