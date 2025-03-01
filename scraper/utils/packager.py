from scraper.utils.db import *
from deepdiff import DeepDiff
from scraper.utils.directory_manager import *
from scraper.utils.db import *
import datetime
import json
import time

# import gzip
import tarfile
import hashlib
import zlib
import lz4.frame


class packager:
    def __init__(self) -> None:
        pass

    def createPackage(type, start_time):
        folder = "C:/packages"
        if type == database.LOCAL:
            folder = "C:/packages"
        if type == database.REMOTE:
            folder = "/usr/atlas/Atlas-gamesdb/public_html/packages"
        # Check if any files exist, if not the make first package
        if os.listdir(folder) == []:
            print("Base file does not exist. Running for first time")
            packager.createFile(
                type,
                folder,
                str(int(time.time())),
                "base",
                packager.createBaseUpdate(type, start_time),
                True,
            )
            print("Creating daily backup")
            packager.createBackup(type, folder, start_time)
        else:
            print("Creating daily backup")
            packager.createBackup(type, folder, start_time)
            print("Creating daily update")
            packager.createFile(
                type,
                folder,
                str(int(time.time())),
                "daily",
                packager.createBaseUpdate(type, start_time),
                True,
            )

    def createFile(dbtype, folder, filename, backuptype, data, compress=False):
        file = os.path.join(
            folder,
            filename,
        )
        if compress:
            with open(
                file + ".update",
                "wb",
            ) as outfile:
                outfile.write(
                    lz4.frame.compress(json.dumps(data, default=str).encode("utf-8"))
                    #zlib.compress(json.dumps(data, default=str).encode("utf-8"), 9)
                )
            # Store each update in the database so we can retrieve a list later
            item = {
                "date": int(filename),
                "name": filename + ".update",
                "md5": hashlib.md5(open(file + ".update", "rb").read()).hexdigest(),
            }
            UpdatetableDynamic("updates", item, dbtype)
        else:
            with open(
                file + ".json",
                "w",
            ) as outfile:
                outfile.write(json.dumps(data, default=str))

    def createBaseUpdate(type, start_time):
        atlas_object = {"atlas": downloadBase(type, "atlas", start_time)}
        f95_object = {"f95_zone": downloadBase(type, "f95_zone", start_time)}
        min_ver = {"min_ver": "0.0.0"}
        data = {**atlas_object, **f95_object, **min_ver}
        return data

    def createBackup(type, folder, start_time):
        atlas_object = downloadBase(type, "atlas", start_time)
        f95_object = downloadBase(type, "f95_zone", start_time)
        packager.createFile(
            type,
            os.path.join(folder, "backup"),
            "atlas_backup_" + datetime.datetime.today().strftime("%Y%m%d"),
            "backup",
            atlas_object,
            False,
        )
        packager.createFile(
            type,
            os.path.join(folder, "backup"),
            "f95_backup_" + datetime.datetime.today().strftime("%Y%m%d"),
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
        # atlas_previous = json.load(
        ##    open(
        #       os.path.join(
        #           folder,
        #           "backup",
        #           "atlas_backup_"
        #           + (datetime.datetime.today() - datetime.timedelta(days=1)).strftime(
        #               "%Y%m%d"
        #           )
        #           + ".json",
        #       )
        #   )
        # )

        # atlas_diff = DeepDiff(atlas_current, atlas_previous, group_by="id")

        # Write changes to file
        # json_object = json.dumps(atlas_diff, default=str)
        json_object = json.dumps(atlas_current, default=str)

        return json_object
        # with open(str(int(time.time())) + ".json", "w") as outfile:
        #    outfile.write(json_object)
        #    print("file written: " + str(int(time.time())) + ".json")
