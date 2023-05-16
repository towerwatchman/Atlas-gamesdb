import requests
from urllib.request import urlopen
from bs4 import BeautifulSoup
from datetime import datetime
from scraper.utils.parser import *
from scraper.utils.db import *
from scraper.datatypes.record import *
from datetime import datetime
import random

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

    def downloadThreadSummary(self, type, include_game_info, last_db_update, db_type):
        # assign records
        atlasRecord = gameRecord.atlasRecord()
        f95Record = gameRecord.f95Record()
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
        for item in range(1, self.getThreadPageCount() + 1):
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
                        parser.ParseThreadItem(thread_items)
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
                        # Get details for each thread item
                        # print(Titem["title"])

                        try:
                            if Titem["category"] != "README":
                                UpdatetableDynamic(
                                    "atlas", self.getDataAtlasTable(Titem), db_type
                                )
                                # get id from db
                                Titem["id"] = findIdByTitle(
                                    "atlas", Titem["id_name"], db_type
                                )[0][0]
                                print(Titem["id"])

                                if include_game_info:
                                    TitemDetail = self.downloadThreadDetails(
                                        self, Titem["site_url"]
                                    )
                                    Titem.update(TitemDetail)

                                    UpdatetableDynamic(
                                        "f95_zone_data",
                                        self.getDataforF95(Titem),
                                        db_type,
                                    )
                        except Exception as ex:
                            print(ex)
                            print("Error: Db Error")
                            continue
                        # last_thread_update = datetime.strptime(Titem['last_thread_update'].replace("T"," ")[:-5], '%Y-%m-%d %H:%M:%S')
                        # print(last_thread_update ,">", last_db_update)
                        # if last_thread_update >last_db_update:
                        # print(Titem)

                    # print(Titem.keys())
                    time.sleep(random.uniform(1.0, 2.2))
                    # break;
                else:
                    print("Page Timeout Error, Waiting 10 seconds")
                    time.sleep(10)
            except Exception as ex:
                print(ex)
                print("Error: Waiting 10 secs before continuning")  # the exception type
                # print(str(inst.args))  # arguments stored in .args
                time.sleep(10)
                continue

    def downloadThreadDetails(self, url):
        time.sleep(1)  # wait another sec before getting individual page info
        Titem = {
            "banner_url": "",
            "overview": "",
            "release_date": "",
            "censored": "",
            "language": "",
            "translations": "",
            "length": "",
            "vndb": "",
            "voice": "",
            "os": "",
            "tags": "",
            "screens": "",
            "likes": "",
        }

        site_url = url
        banner_url = ""
        overview = ""
        release_date = ""
        censored = ""
        language = ""
        translations = ""
        length = ""
        vndb = ""
        voice = ""
        os = ""
        tags = ""
        screens = ""
        likes = ""

        # HERE IS WHERE WE LOAD THE INDIVIDUAL PAGE TO SCRAPE ADDITIONAL DATA
        gpage = requests.get(site_url)
        if gpage.status_code == 200:
            gsoup = BeautifulSoup(gpage.content, "html.parser")
            job_elements = gsoup.find_all("div", class_="bbWrapper")
            # title = gsoup.select('h1.p-title-value')[0].text.strip()

            try:
                overview = (
                    job_elements[0]
                    .find_all("div")[0]
                    .get_text()
                    .replace("Overview:", "")
                    .strip()
                )
                if len(overview) <= 2:
                    overview = (
                        job_elements[0]
                        .find_all("div")[1]
                        .get_text()
                        .replace("Overview:", "")
                        .strip()
                    )
                overview = overview.split("\n\n\n", 1)[0]
            except:
                overview = ""

            try:
                # this is wrong change to taglist
                taglist = gsoup.select("span.js-tagList")[0].find_all("a")
                tags = ""
                for g in taglist:
                    tmp = g.text.strip()
                    if tags == "":
                        # first element
                        tags = tmp
                    else:
                        tags = tags + "," + tmp
            except:
                tags = ""
            # Likes
            try:
                userExtras = gsoup.find("div", class_="message-userExtras").find_all(
                    "dd"
                )
                likes = userExtras[2].get_text()
            except:
                likes = "error"
            # Screenshots
            alinks = job_elements[0].find_all("a")
            # skip first item since we know that it is banner image
            screens = ""
            for link in alinks:
                try:
                    img = str(link["href"])
                    if "attachments" in img:
                        if screens == "":
                            screens = link["href"]
                        else:
                            screens = screens + "," + link["href"]
                except Exception:
                    pass

                try:
                    banner_url = gsoup.find_all("img", class_="bbImage")[0]["src"]
                except:
                    banner_url = ""

                try:
                    release_date = (
                        job_elements[0]
                        .find("b", text="Release Date")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )
                except:
                    try:
                        release_date = (
                            job_elements[0]
                            .find("b", text="Year:")
                            .next_sibling.strip()
                            .replace(":", "")
                            .strip()
                        )
                    except:
                        release_date = ""

                try:
                    censored = (
                        job_elements[0]
                        .find("b", text="Censored")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )

                except:
                    try:
                        censored = (
                            job_elements[0]
                            .find("b", text="Censored:")
                            .next_sibling.strip()
                            .replace(":", "")
                            .strip()
                        )
                    except:
                        try:
                            censored = (
                                job_elements[0]
                                .find("b", text="Censorship:")
                                .next_sibling.strip()
                                .replace(":", "")
                                .strip()
                            )
                        except:
                            censored = ""

                try:
                    os = (
                        job_elements[0]
                        .find("b", text="OS")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )
                except:
                    try:
                        os = (
                            job_elements[0]
                            .find("b", text="Platforms:")
                            .next_sibling.strip()
                            .replace(":", "")
                            .strip()
                        )
                    except:
                        os = ""

                try:
                    language = (
                        job_elements[0]
                        .find("b", text="Language")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )
                except:
                    try:
                        language = (
                            job_elements[0]
                            .find("b", text="Language:")
                            .next_sibling.strip()
                            .replace(":", "")
                            .strip()
                        )
                    except:
                        language = ""

                try:
                    translations = (
                        job_elements[0]
                        .find("b", text="Translations:")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )
                except:
                    translations = ""

                try:
                    length = (
                        job_elements[0]
                        .find("b", text="Length")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )
                except:
                    try:
                        length = (
                            job_elements[0]
                            .find("b", text="Length:")
                            .next_sibling.strip()
                            .replace(":", "")
                            .strip()
                        )
                    except:
                        length = ""

                try:
                    voice = (
                        job_elements[0]
                        .find("b", text="Voice")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )
                except:
                    try:
                        voice = (
                            job_elements[0]
                            .find("b", text="Voice:")
                            .next_sibling.strip()
                            .replace(":", "")
                            .strip()
                        )
                    except:
                        voice = ""

                try:
                    vndb = (
                        job_elements[0]
                        .find("b", text="VNDB:")
                        .next_sibling.strip()
                        .replace(":", "")
                        .strip()
                    )
                except:
                    vndb = ""

            # Store data in dict and return dict
            Titem["banner_url"] = banner_url
            Titem["overview"] = overview
            Titem["release_date"] = release_date
            Titem["censored"] = censored
            Titem["language"] = language
            Titem["translations"] = translations
            Titem["length"] = length
            Titem["vndb"] = vndb
            Titem["voice"] = voice
            Titem["os"] = os
            Titem["tags"] = tags
            Titem["screens"] = screens
        return Titem

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
    def getDataAtlasTable(data):
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
                "overview",
                "censored",
                "language",
                "length",
                "voice",
                "os",
                "release_date",
                "translations",
                "tags",
                "last_db_update",
            ]
        }
        return Titem

    def getDataforF95(data):
        Titem = {
            key: data[key]
            for key in [
                "id",
                "f95_id",
                "banner_url",
                "site_url",
                "last_thread_comment",
                "views",
                "likes",
                "tags",
                "rating",
                "screens",
                "replies",
            ]
        }
        return Titem
