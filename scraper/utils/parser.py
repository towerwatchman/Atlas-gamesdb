import collections
import re
from scraper.datatypes.data import *


class parser:
    def __init__(self) -> None:
        pass

    def ParseThreadItem(thread_items, atlasRecord, f95Record):
        for thread_item in thread_items:
            f95Record["site_url"] = "https://f95zone.to" + thread_item["href"]
            item = thread_item.text
            # print(item)
            if item.upper() in data.Tcategory():
                atlasRecord["category"] = item.replace("[", "").replace("]", "")
            elif item.upper() in data.Tengine():
                atlasRecord["engine"] = item.replace("[", "").replace("]", "")
            elif item.upper() in data.Tstaus():
                atlasRecord["status"] = item.replace("[", "").replace("]", "")
            else:  # Parse Game Name
                strings = item.split("[")
                atlasRecord["title"] = strings[0].replace("[", "").replace("]", "")
                if len(strings) == 2:
                    tmp = re.sub(
                        "[\W_]+",
                        "",
                        strings[1].strip().replace("[", "").replace("]", ""),
                    ).upper()
                    if tmp in data.Tversion():  # check if this is version or dev
                        atlasRecord["version"] = (
                            strings[1].replace("[", "").replace("]", "").strip()
                        )
                    else:
                        atlasRecord["creator"] = (
                            strings[1].replace("[", "").replace("]", "").strip()
                        )
                elif len(strings) == 3:
                    atlasRecord["version"] = (
                        strings[1].replace("[", "").replace("]", "").strip()
                    )
                    atlasRecord["creator"] = (
                        strings[2].replace("[", "").replace("]", "").strip()
                    )

                f95Record["f95_id"] = re.sub(
                    "[\W_]+",
                    "",
                    f95Record["site_url"].split(".")[
                        len(f95Record["site_url"].split(".")) - 1
                    ],
                )
                atlasRecord["short_name"] = re.sub(
                    "[\W_]+",
                    "",
                    atlasRecord["title"].strip().replace(" ", ""),
                ).upper()

            atlasRecord["id_name"] = (
                atlasRecord["short_name"] + "_" + atlasRecord["creator"].upper()
            )
        # return Titem

    def ParseDateTimeItem(item):
        if len(item) <= 0:
            return ""
        else:
            return (item[0]["datetime"]).replace("T", " ")[:-5]

    def ParseRating(element):
        try:
            return (
                element.select("span.ratingStars")[0]
                .text.strip()
                .replace("star(s)", "")
                .strip()
            )
        except:
            return 0.0

    def ParseViews(element):
        try:
            #init count
            count = 0    
            tmp = element.select("div.structItem-cell--meta")[0].find_all("dl")[1].select("dd")[0].text
            count = re.sub('\D', '', tmp) #remove all chars
            if "k" in tmp:
                count = count * 1000
            if "m" in tmp:
                count = count * 100000000
            return count
           
        except:
            return 0

    def ParseReplies(element):
        try:     
            #init count
            count = 0       
            tmp = element.select("div.structItem-cell--meta")[0].find_all("dl")[0].select("dd")[0].text
            count = re.sub('\D', '', tmp) #remove all chars
            if "k" in tmp:
                count = count * 1000
            if "m" in tmp:
                count = count * 100000000
            return count
            
        except:
            return 0
