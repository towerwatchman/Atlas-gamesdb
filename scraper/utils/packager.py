from scraper.utils.db import *
from deepdiff import DeepDiff
from scraper.utils.directory_manager import *
from scraper.config import config
from scraper.types.eTypes import database
import os
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
        # Packaging always runs against the (only) MySQL database.
        type = database.REMOTE
        folder = config.package_dir()
        os.makedirs(os.path.join(folder, "backup"), exist_ok=True)
        # First run = no package (.update) files yet -> make the base package.
        existing = [f for f in os.listdir(folder) if f.endswith(".update")]
        if not existing:
            print("Base file does not exist. Running for first time")
            packager.createFile(
                type,
                folder,
                str(int(time.time())),
                "base",
                packager.createBaseUpdate(type, start_time, is_full=True),
                compress=True,
                is_full=True,
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
                packager.createBaseUpdate(type, start_time, is_full=False),
                compress=True,
                is_full=False,
            )

    def createFullPackage(type, start_time):
        """Always produces a full (is_full=True) package regardless of what
        .update files already exist on disk. Used by backup.py, which
        truncates the updates table before calling this -- without its own
        dedicated path it would fall into createPackage's daily-snapshot
        branch just because old .update files are still sitting on disk."""
        type = database.REMOTE
        folder = config.package_dir()
        os.makedirs(os.path.join(folder, "backup"), exist_ok=True)
        print("Creating full package")
        packager.createFile(
            type,
            folder,
            str(int(time.time())),
            "base",
            packager.createBaseUpdate(type, start_time, is_full=True),
            compress=True,
            is_full=True,
        )
        print("Creating daily backup")
        packager.createBackup(type, folder, start_time)

    def createFile(dbtype, folder, filename, backuptype, data, compress=False, is_full=False):
        file = os.path.join(folder, filename)
        if compress:
            with open(file + ".update", "wb") as outfile:
                outfile.write(
                    lz4.frame.compress(json.dumps(data, default=str).encode("utf-8"))
                )
            # Store each update in the database so we can retrieve a list later.
            # is_full=1 -> client should treat this as a complete dataset;
            # is_full=0 -> snapshot/delta of records updated since start_time.
            item = {
                "date": int(filename),
                "name": filename + ".update",
                "md5": hashlib.md5(open(file + ".update", "rb").read()).hexdigest(),
                "is_full": 1 if is_full else 0,
            }
            UpdatetableDynamic("updates", item, dbtype)
        else:
            with open(file + ".json", "w") as outfile:
                outfile.write(json.dumps(data, default=str))

    def createBaseUpdate(type, start_time, is_full=False):
        # Atlas rows carry admin manual links (atlas_manual_links) overlaid into
        # external_ids so approved manual links always reach clients, without the
        # scraper ever writing them back to the stored column.
        atlas_object = {"atlas": downloadAtlasBase(type, start_time)}
        f95_object = {"f95_zone": downloadBase(type, "f95_zone", start_time)}
        lc_object = {"lewdcorner": downloadBase(type, "lewdcorner", start_time)}
        min_ver = {"min_ver": "0.0.0"}
        # Include the full flag in the package payload itself so the client
        # knows how to interpret the data without a separate API call.
        full_flag = {"full": is_full}
        data = {**full_flag, **atlas_object, **f95_object, **lc_object, **min_ver}
        return data

    def createBackup(type, folder, start_time):
        # Raw table snapshot (for restore/archival), so external_ids is the
        # stored value, NOT the manual-link overlay used in the client package.
        # Manual links are backed up via their own table's dump if needed.
        atlas_object = downloadBase(type, "atlas", start_time)
        f95_object = downloadBase(type, "f95_zone", start_time)
        lc_object = downloadBase(type, "lewdcorner", start_time)
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
        packager.createFile(
            type,
            os.path.join(folder, "backup"),
            "lewdcorner_backup_" + datetime.datetime.today().strftime("%Y%m%d"),
            "backup",
            lc_object,
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