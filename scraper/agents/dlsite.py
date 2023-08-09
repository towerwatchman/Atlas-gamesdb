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

    def getIDs(type, db_type):
        baseURL = "https://www.dlsite.com/pro/product/info/ajax?product_id=" + type

        starting_id = 1000

    # books, pro, maniax
    def updateCircleID(db_type, item_type):
        baseURL = "https://www.dlsite.com/" + item_type + "/circle/list/=/name_header/"
        tmp = {}
        for circle in dlsite.circle_list:
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
                    tmp["circle_id"] = cells[0].get_text()
                    tmp["name"] = cells[1].get_text()
                    tmp["url"] = cells[2].find("a", href=True)["href"]
                    tmp["img"] = cells[2].find("img")["src"]
                    # print(tmp["circle_id"])
                    # print(
                    #    "ID: "
                    #    + str(tmp["id"])
                    #    + " | Circle: "
                    #    + str(tmp["name"])
                    #    + " | url: "
                    #    + str(tmp["url"])
                    #    + " | img: "
                    #    + str(tmp["img"])
                    # )
                    UpdatetableDynamic("dlsite_circle", tmp, db_type)
                print(item_type + " Circle ID's Updated for " + circle)
            else:
                print("ERROR! Unable to update for: " + circle)

    def getAllGamesHtml(db_type):
        print("test")
        # https://www.dlsite.com/pro/fsr/=/language/en/sex_category[0]/male/work_category[0]/pc/order/release/options_and_or/and/per_page/100/lang_options[0]/Japanese/lang_options[1]/English/lang_options[2]/Alingual/show_type/1

    def getJSONgame(db_type):
        base_url = "https://www.dlsite.com/pro/product/info/ajax?product_id=VJ"
        dlsite_id = "000000"

        atlasRecord = {}
        dlsiteRecord = {}
        for x in range(1001, 20000):
            # Format string
            if len(str(x)) == 4:
                dlsite_id = "00" + str(x)
            if len(str(x)) == 5:
                dlsite_id = "0" + str(x)

            print("Running for " + "VJ" + str(dlsite_id))
            request = requests.get(base_url + dlsite_id)
            if request.status_code == 200:
                page = json.loads(request.text)
                dlsiteRecord["dlsite_id"] = "7" + dlsite_id
                dlsiteRecord["circle_id"] = page["VJ" + dlsite_id]["maker_id"]
                atlasRecord["creator"] = findDlsiteMaker(
                    "dlsite_circle", dlsiteRecord["circle_id"], db_type
                )
                if atlasRecord["creator"] == 0:
                    atlasRecord["creator"] == dlsiteRecord["circle_id"]
                # print(atlasRecord["creator"])
                dlsiteRecord["site_url"] = page["VJ" + dlsite_id]["down_url"]
                atlasRecord["title"] = page["VJ" + dlsite_id]["work_name"]
                dlsiteRecord["banner_url"] = page["VJ" + dlsite_id]["work_image"]
                atlasRecord["version"] = "N/A"
                atlasRecord["short_name"] = re.sub(
                    "[\W_]+",
                    "",
                    atlasRecord["title"].strip().replace(" ", ""),
                ).upper()
                atlasRecord["id_name"] = (
                    atlasRecord["short_name"]
                    + "_"
                    + str(atlasRecord["creator"]).upper()
                )
                dlsiteRecord["work_type"] = page["VJ" + dlsite_id]["work_type"]
                dlsiteRecord["register_date"] = page["VJ" + dlsite_id]["regist_date"]

            dlsite.updateRecord("dlsite", atlasRecord, dlsiteRecord, db_type, dlsite_id)
            # print(page["VJ" + dlsite_id]["maker_id"])
            print(dlsiteRecord)

            time.sleep(1)

    def updateRecord(table, aRecord, dRecord, db_type, thread_id):
        UpdatetableDynamic("atlas", aRecord, db_type)
        # print(aRecord)
        id = findIdByTitle("atlas", aRecord["id_name"], db_type)
        # print(id)
        dRecord["atlas_id"] = id
        # print(fRecord)
        UpdatetableDynamic(table, dRecord, db_type)
        print(
            "Database update completed for dlsite_id:",
            dRecord["dlsite_id"],
            " on thread:",
            thread_id,
        )
