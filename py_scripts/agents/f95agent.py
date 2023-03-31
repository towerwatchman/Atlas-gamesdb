import requests
from urllib.request import urlopen
from bs4 import BeautifulSoup
from utils.parser import *
#from datetime import datetime
#from db import *
#import re
#import time

def baseURL():
    return "https://f95zone.to/forums/games.2/"

def Tversion():
    return ['V0','V1','FINAL', 'PROLOGUE', 'ALPHA', 'BETA', 'DEMO', 'CH.', 'CHAPTER', 'UPDATE', 'EPISODE', 'EP.']
def Tcategory():
    return ['[READ ME]', '[SITERIP]', '[COLLECTION]', '[VN]']
def Tengine():
    return ['[OTHERS]', '[RAGS]', '[RPGM]', '[WEBGL]', '[UNITY]', '[HTML]', '[QSP]', '[JAVA]', '[REN\'PY]',
                    '[UNREAL ENGINE]', '[WOLF RPG]', '[FLASH]', '[ADRIFT]', '[TADS]']
def Tstaus():
    return ['[COMPLETED]', '[ONHOLD]', '[ABANDONED]']

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
        print(
            "Staring download from F95",
            "\nDownload type:",type,
            "\nInclude Game Metadata:", include_game_info,
            "\nLast Database update:", last_db_update
            )
        #print(type, include_game_info, last_db_update)
        
        for item in range(1 , self.getThreadPageCount()):
            #Page manipulation            
            print("---- Starting Page:",str(item),"----")
            if(item > 1):  
                URL = baseURL() + "page-" + str(item)             
            else:
                URL = baseURL()               

            #First attempt to get url
            page = requests.get(URL)
            if(page.status_code == 200):   
                html = BeautifulSoup(page.content, "html.parser")
                elements = html.find_all("div", class_="structItem")
                #each element is a Item thread on 1 page. Each page will have 25-30 items
                for element in elements:
                    prefixes = element.select('div.structItem-title')[0].find_all('a')
                    for prefix in prefixes:
                        parser.ParsePrefix(prefix)
                break;
                    #try getting first page
            else:
                print("error")

