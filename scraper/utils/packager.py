from scraper.utils.db import *
from deepdiff import DeepDiff
import json
import time


class packager:
    def __init__(self) -> None:
        pass

    def createPackage(type):
        # /var/www/html/packages

        b = open("base.json")
        n = open("base1.json")
        base = json.load(b)
        next = json.load(n)

        diff = DeepDiff(
            base,
            next,
            exclude_regex_paths=[r"root\[\d+\]\['last_db_update'\]"],
            group_by="id",
            verbose_level=2,
        )
        for item in diff.items():
            print(item)

        json_object = json.dumps(diff, default=str)

        with open(str(int(time.time())) + ".json", "w") as outfile:
            outfile.write(json_object)
            print("file written: " + str(int(time.time())) + ".json")
