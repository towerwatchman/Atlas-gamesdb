import requests
from urllib.request import urlopen
from bs4 import BeautifulSoup
from scraper.utils.db import *
import json
import time
import re

# Sample url
# https://www.dlsite.com/pro/work/=/product_id/VJ01000221.html
# https://www.dlsite.com/maniax/product/info/ajax?product_id=RJ021041
# https://www.dlsite.com/pro/product/info/ajax?product_id=VJ015697
# https://www.anime-sharing.com/forum/hentai-games-38/other_language-%5Blump-sugar%5D-yumahorome-~toki-o-tometa-yakata-de-asu-o-sagasu-maigo-tachi~-%5Bsteam%5D-2022-08-12-a-1250586/


# FIRST
# https://www.dlsite.com/maniax/product/info/ajax?product_id=RJ01002988
# SECOND
#


class dlsite:
    def __init__(self) -> None:
        pass

    def getIDs(type, db_type):
        baseURL = "https://www.dlsite.com/pro/product/info/ajax?product_id=" + type

        starting_id = 1000

    def updateCircleID(db_type):
        baseURL = "https://www.dlsite.com/maniax/circle/list/=/name_header/"
        circle_list = [
            "A",
            "B",
            "C",
            "D",
            "E",
            "F",
            "G",
            "H",
            "I",
            "J",
            "K",
            "L",
            "M",
            "N",
            "O",
            "P",
            "Q",
            "R",
            "S",
            "T",
            "U",
            "V",
            "W",
            "X",
            "Y",
            "Z",
            "あ",
            "い",
            "う",
            "え",
            "お",
            "か",
            "き",
            "く",
            "け",
            "こ",
            "さ",
            "し",
            "す",
            "せ",
            "そ",
            "た",
            "ち",
            "つ",
            "て",
            "と",
            "な",
            "に",
            "ぬ",
            "ね",
            "の",
            "は",
            "ひ",
            "ふ",
            "へ",
            "ほ",
            "ま",
            "み",
            "む",
            "め",
            "も",
            "や",
            "ゆ",
            "よ",
            "ら",
            "り",
            "る",
            "れ",
            "ろ",
            "わ",
            "を",
            "ん",
        ]

        tmp = {}

        for circle in circle_list:
            request = requests.get(baseURL + circle)
            if request.status_code == 200:
                page = BeautifulSoup(request.content, "html.parser")
                maker_list = (
                    page.select("#maker_list_body")[0]
                    .find("table")
                    .find("tbody")
                    .find_all("tr")
                )
                for maker in maker_list:
                    cells = maker.find_all("td")
                    tmp["id"] = cells[0].get_text()
                    tmp["name"] = cells[1].get_text()
                    tmp["url"] = cells[2].find("a", href=True)["href"]
                    tmp["img"] = cells[2].find("img")["src"]
                    print(
                        "ID: "
                        + str(tmp["id"])
                        + " | Circle: "
                        + str(tmp["name"])
                        + " | url: "
                        + str(tmp["url"])
                        + " | img: "
                        + str(tmp["img"])
                    )
                    UpdatetableDynamic("dlsite_circle", tmp, db_type)
                print("SUCCESS")
            else:
                print("ERROR")

    def getAllGamesHtml(db_type):
        print("test")
        # https://www.dlsite.com/pro/fsr/=/language/en/sex_category[0]/male/work_category[0]/pc/order/release/options_and_or/and/per_page/100/lang_options[0]/Japanese/lang_options[1]/English/lang_options[2]/Alingual/show_type/1

    def getJSONgame(db_type):
        base_url = "https://www.dlsite.com/pro/product/info/ajax?product_id=VJ"
        dlsite_id = "000000"

        atlasRecord = {}
        for x in range(1001, 20000):
            # Format string
            if len(str(x)) == 4:
                dlsite_id = "00" + str(x)
            if len(str(x)) == 5:
                dlsite_id = "0" + str(x)

            print(base_url + dlsite_id)
            request = requests.get(base_url + dlsite_id)
            if request.status_code == 200:
                page = json.loads(request.text)
                atlasRecord["creator"] = findDlsiteMaker(
                    "dlsite_circle", page["VJ" + dlsite_id]["maker_id"], db_type
                )
                atlasRecord["site_url"] = page["VJ" + dlsite_id]["down_url"]
                atlasRecord["title"] = page["VJ" + dlsite_id]["work_name"]
                atlasRecord["banner_url"] = page["VJ" + dlsite_id]["work_image"]
                work_type = page["VJ" + dlsite_id]["work_type"]
                regist_date = page["VJ" + dlsite_id]["regist_date"]

            print(page["VJ" + dlsite_id]["maker_id"])
            print(atlasRecord)
            time.sleep(100)

    def updateRecord(self, table, aRecord, dRecord, db_type, thread_id):
        UpdatetableDynamic(table, aRecord, db_type)
        # print(aRecord)
        id = findIdByTitle(table, aRecord["id_name"], db_type)
        # print(id)
        dRecord["atlas_id"] = id
        # print(fRecord)
        UpdatetableDynamic("f95_zone", dRecord, db_type)
        print(
            "Database update completed for f95_id:",
            dRecord["f95_id"],
            " on thread:",
            thread_id,
        )
