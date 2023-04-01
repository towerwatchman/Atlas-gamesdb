import requests
from urllib.request import urlopen
from bs4 import BeautifulSoup
from utils.parser import *
from datetime import datetime
from utils.db import *
#import re
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
        if(request.status_code == 200):   
            page = BeautifulSoup(request.content, "html.parser")
            tmp = page.select('div.pageNavSimple')[0].find_all('a')[0].text.strip()
            total_pages = tmp.upper().split("OF")[1]
            return int(total_pages)
        else:
            return 0
    
    def downloadThreadInfo(self, type, include_game_info, last_db_update):
        pages = self.getThreadPageCount()
        print(
            "Staring download from F95",
            "\nDownload type:",type,
            "\nInclude Game Metadata:", include_game_info,
            "\nLast Database update:", last_db_update,
            "\n", pages, "total pages"
            )
        
        #Get total page count and ittereate through them
        for item in range(1 , self.getThreadPageCount()):
            #Page manipulation            
            print("---- Starting Page:",str(item),"----")
            if(item > 1):  
                URL = baseURL() + "page-" + str(item)+ "?order=post_date&direction=desc"             
            else:
                URL = baseURL() + "?order=post_date&direction=desc"               

            #First attempt to get url
            page = requests.get(URL)
            if(page.status_code == 200):   
                html = BeautifulSoup(page.content, "html.parser")
                elements = html.find_all("div", class_="structItem")
                #each element is an Item thread on 1 page. Each page will have 20 items
                for element in elements:
                    thread_items = element.select('div.structItem-title')[0].find_all('a')    
                    Titem = parser.ParseThreadItem(thread_items)  
                    Titem['thread_publish_date'] = element.select('li.structItem-startDate')[0].find_all('a')[0].select('time')[0]['datetime'].replace("T"," ")[:-5]
                    Titem['last_thread_comment'] = parser.ParseDateTimeItem(element.select('time.structItem-latestDate')).replace("T"," ")[:-5]
                    Titem['last_record_update'] = datetime.utcnow()
                    Titem['replies'] = parser.ParseReplies(element)
                    Titem['views'] = parser.ParseViews(element)
                    Titem['rating'] = parser.ParseRating(element)
                    #print(Titem['category'])
                    if Titem['category'] != "README":
                        UpdatetableDynamic("f95zone_data", Titem, True)
                        #last_thread_update = datetime.strptime(Titem['last_thread_update'].replace("T"," ")[:-5], '%Y-%m-%d %H:%M:%S')
                        #print(last_thread_update ,">", last_db_update)
                        #if last_thread_update >last_db_update:
                        #print(Titem)
                        
                #print(Titem.keys())
                time.sleep(1)   
                #break;
            else:
                print("error")

