import requests
import json
from urllib.request import urlopen
from bs4 import BeautifulSoup
from datetime import datetime
from scraper.utils.parser import *
from scraper.utils.db import *
from scraper.datatypes.record import *
from scraper.utils.epoch import *
from datetime import datetime
import random
from threading import Thread
import pandas as pd
import sys

import time

# TEST URL: https://f95zone.to/threads/the-necromancer-arises-prologue-whiteleaf-studio.154250/
# TEST JSON: https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=list&cat=games&page=1&sort=date&rows=90


def baseURL():
    return "https://f95zone.to/forums/games.2/"

def baseJsonURL():
    #&page=1&sort=date&rows=90
    return "https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=list&cat=games"


class f95:
    def __init__(self) -> None:
        pass
   
    def getLatestPageCount():
        headers ={'accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                  'accept-encoding':'gzip, deflate, br',
                  'accept-language' : 'en-US,en;q=0.9',
                  'cache-control':'max-age=0',
                  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        request = requests.get(baseJsonURL() + "&page=5&sort=date&rows=90", headers)
        if request.status_code == 200:
            data = request.json()
            total_pages = data["msg"]["pagination"]["total"]
            return int(total_pages)
        else:
            print("STATUS CODE",request.status_code)
            return 0

    def downloadLatest(self, type, db_type):
        pages = self.getLatestPageCount()
        print(
            "Staring download from F95",
            "\nDownload type:",
            type,
            "\n",
            pages,
            "total pages",
        )
        for index in range(1, int(pages)):
            atlasRecord = gameRecord.atlasRecord()
            f95Record = gameRecord.f95Record()   
            try:
                time.sleep(2)
                headers ={'accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                  'accept-encoding':'gzip, deflate, br',
                  'accept-language' : 'en-US,en;q=0.9',
                  'cache-control':'max-age=0',
                  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                request = requests.get(baseJsonURL() + "&page=" + str(index) + "&sort=date&rows=90", headers)
                if request.status_code == 200:
                    data = request.json()
                    games = data["msg"]["data"]
                    df = pd.DataFrame(games)
                    for idx in df.index:
                        thread_id = df["thread_id"][idx]
                        print("Downloading data for id: ", thread_id)
                        f95Record["f95_id"] = str(thread_id)
                        f95Record["views"] = df["views"][idx]
                        f95Record["likes"] = df["likes"][idx]
                        f95Record["rating"] = df["rating"][idx]
                        f95Record["banner_url"] = df["cover"][idx].replace("preview","attachments")
                        f95Record["site_url"] = "https://f95zone.to/threads/" + str(thread_id)                      
                        f95Record["screens"] = ','.join(df["screens"][idx]).replace("preview","attachments")

                        atlasRecord["title"] = df["title"][idx]
                        atlasRecord["creator"] = df["creator"][idx]
                        atlasRecord["version"] = df["version"][idx]
                        atlasRecord["short_name"] = re.sub("[\W_]+","",str(atlasRecord["title"]).strip().replace(" ", "")).upper()

                        atlasRecord["id_name"] = (atlasRecord["short_name"] + "_" + str(atlasRecord["creator"]).strip().replace(" ", "").upper())
                        #atlasRecord["category"] = df["title"][idx]
                        #atlasRecord["engine"] = df["title"][idx]
                        #atlasRecord["status"] = df["title"][idx]

                        #Check if date catefory has been updated in mins or hours. If so then scrap from website
                        #mins, hrs

                        self.updateRecord(
                                f95,
                                "atlas",
                                self.formatDictionary(atlasRecord),
                                self.formatDictionary(f95Record),
                                db_type,
                                df["thread_id"][idx],
                            )
                        
                        
            except Exception as ex:
                print("ERROR",ex)
                continue
            

   
   
    def formatDictionary(data):
        data = {k: v for k, v in data.items() if v}
        return data

    def updateRecord(self, table, aRecord, fRecord, db_type, thread_id):

        UpdatetableDynamic(table, aRecord, db_type)
        #Check the datadase and see if an entry already exist
        id = findIdByTitle(table, aRecord["id_name"], db_type)
        fRecord["atlas_id"] = id
        UpdatetableDynamic("f95_zone", fRecord, db_type)
        print(
            "Database update completed for f95_id:",
            fRecord["f95_id"],
            " on thread:",
            thread_id,
        )
