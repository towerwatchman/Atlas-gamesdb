import collections
import re
from datatypes.data import *


class parser:
    def __init__(self) -> None:
        pass

    def ParseThreadItem(thread_items):
        Titem = {
            "f95_id": "",
            "short_name": "",
            "category": "",
            "engine": "",
            "status": "",
            "title": "",
            "creator": "",
            "version": "",
            "site_url": "",
        }

        for thread_item in thread_items:
            Titem["site_url"] = "https://f95zone.to" + thread_item["href"]
            item = thread_item.text
            # print(item)
            if item.upper() in data.Tcategory():
                Titem["category"] = item.replace("[", "").replace("]", "")
            elif item.upper() in data.Tengine():
                Titem["engine"] = item.replace("[", "").replace("]", "")
            elif item.upper() in data.Tstaus():
                Titem["status"] = item.replace("[", "").replace("]", "")
            else:  # Parse Game Name
                strings = item.split("[")
                Titem["title"] = strings[0].replace("[", "").replace("]", "")
                if len(strings) == 2:
                    tmp = re.sub(
                        "[\W_]+",
                        "",
                        strings[1].strip().replace("[", "").replace("]", ""),
                    ).upper()
                    if tmp in data.Tversion():  # check if this is version or dev
                        Titem["version"] = (
                            strings[1].replace("[", "").replace("]", "").strip()
                        )
                    else:
                        Titem["creator"] = (
                            strings[1].replace("[", "").replace("]", "").strip()
                        )
                elif len(strings) == 3:
                    Titem["version"] = (
                        strings[1].replace("[", "").replace("]", "").strip()
                    )
                    Titem["creator"] = (
                        strings[2].replace("[", "").replace("]", "").strip()
                    )

                Titem["f95_id"] = re.sub(
                    "[\W_]+",
                    "",
                    Titem["site_url"].split(".")[len(Titem["site_url"].split(".")) - 1],
                )
                Titem["short_name"] = re.sub(
                    "[\W_]+", "", Titem["title"].strip().replace(" ", "")
                ).upper()

        return Titem

    def ParseDateTimeItem(item):
        if len(item) <= 0:
            return ""
        else:
            return item[0]["datetime"]

    def ParseRating(element):
        try:
            return (
                element.select("span.ratingStars")[0]
                .text.strip()
                .replace("star(s)", "")
                .strip()
            )
        except:
            return ""

    def ParseViews(element):
        try:
            return (
                element.select("div.structItem-cell--meta")[0]
                .find_all("dl")[1]
                .select("dd")[0]
                .text
            )
        except:
            return ""

    def ParseReplies(element):
        try:
            return (
                element.select("div.structItem-cell--meta")[0]
                .find_all("dl")[0]
                .select("dd")[0]
                .text
            )
        except:
            return ""
