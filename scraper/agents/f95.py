import requests
from urllib.request import urlopen
from bs4 import BeautifulSoup
from datetime import datetime
from scraper.utils.parser import *
from scraper.utils.db import *
from datetime import datetime

# import re
import time


def baseURL():
    return "https://f95zone.to/forums/games.2/"


class f95:
    def __init__(self) -> None:
        pass

    def findGameByID(id):
        print(id)

    def getThreadPageCount():
        request = requests.get(baseURL())
        if request.status_code == 200:
            page = BeautifulSoup(request.content, "html.parser")
            tmp = page.select("div.pageNavSimple")[0].find_all("a")[0].text.strip()
            total_pages = tmp.upper().split("OF")[1]
            return int(total_pages)
        else:
            return 0

    def downloadThreadInfo(self, type, include_game_info, last_db_update, db_type):
        pages = self.getThreadPageCount()
        print(
            "Staring download from F95",
            "\nDownload type:",
            type,
            "\nInclude Game Metadata:",
            include_game_info,
            "\nLast Database update:",
            last_db_update,
            "\n",
            pages,
            "total pages",
        )

        # Get total page count and ittereate through them
        for item in range(211, self.getThreadPageCount() + 1):
            # Page manipulation
            print("---- Starting Page:", str(item), "----")
            if item > 1:
                URL = (
                    baseURL() + "page-" + str(item) + "?order=post_date&direction=desc"
                )
            else:
                URL = baseURL() + "?order=post_date&direction=desc"

            # First attempt to get url
            try:
                page = requests.get(URL)
                if page.status_code == 200:
                    html = BeautifulSoup(page.content, "html.parser")
                    elements = html.find_all("div", class_="structItem")
                    # each element is an Item thread on 1 page. Each page will have 20 items
                    for element in elements:
                        thread_items = element.select("div.structItem-title")[
                            0
                        ].find_all("a")
                        Titem = parser.ParseThreadItem(thread_items)
                        Titem["thread_publish_date"] = (
                            element.select("li.structItem-startDate")[0]
                            .find_all("a")[0]
                            .select("time")[0]["datetime"]
                            .replace("T", " ")[:-5]
                        )
                        Titem["last_thread_comment"] = parser.ParseDateTimeItem(
                            element.select("time.structItem-latestDate")
                        ).replace("T", " ")[:-5]
                        Titem["last_record_update"] = datetime.utcnow()
                        Titem["replies"] = parser.ParseReplies(element)
                        Titem["views"] = parser.ParseViews(element)
                        Titem["rating"] = parser.ParseRating(element)
                        Titem["last_db_update"] = datetime.utcnow()
                        # Assign name  + engine for each item

                        print(Titem["title"])
                        if Titem["category"] != "README":
                            UpdatetableDynamic(
                                "atlas", self.updateAtlasTable(Titem), db_type
                            )
                        # last_thread_update = datetime.strptime(Titem['last_thread_update'].replace("T"," ")[:-5], '%Y-%m-%d %H:%M:%S')
                        # print(last_thread_update ,">", last_db_update)
                        # if last_thread_update >last_db_update:
                        # print(Titem)

                    # print(Titem.keys())
                    time.sleep(2)
                    # break;
                else:
                    print("error")
            except:
                print("Error")

    def downloadLatest(self, type):
        print(type)
        # get total pages
        # get id list

    def getLatestUpdateIds():
        alpha_url = "https://f95zone.to/sam/latest_alpha/"
        page = requests.get(alpha_url)
        print(page)
        if page.status_code == 200:
            html = BeautifulSoup(page.content, "html.parser")
            print(html)
        # elements = html.find_all("script")

        # print(elements)
        # for element in elements:
        #    print(element)

    # https://f95zone.to/sam/latest_alpha/
    # <script>
    # var latestUpdates
    # Need to have an id for each item for now use f95_id. will fix later
    def updateAtlasTable(data):
        Titem = {
            key: data[key]
            for key in [
                "id_name",
                "title",
                "short_name",
                "category",
                "engine",
                "status",
                "version",
                "creator",
                "last_db_update",
            ]
        }
        # Titem["id"] = Titem.pop("f95_id")
        return Titem

    def getDataforF95(data):
        Titem = {
            key: data[key]
            for key in [
                "f95_id",
                "title",
                "short_name",
                "category",
                "engine",
                "status",
                "version",
                "creator",
                "site_url",
                "thread_publish_date",
                "last_thread_comment",
                "last_record_update",
                "replies",
                "views",
                "rating",
            ]
        }
        Titem["id"] = Titem.pop("f95_id")
        return Titem
