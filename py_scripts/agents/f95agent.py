import requests
from urllib.request import urlopen
from bs4 import BeautifulSoup
#from datetime import datetime
#from db import *
#import re
#import time

class f95:
    def __init__(self) -> None:
        pass

    def findGameByID(id):
        print(id)

    def getThreadPageCount():
        URL = "https://f95zone.to/forums/games.2/"
        request = requests.get(URL)
        if(request.status_code == 200):   
            page = BeautifulSoup(request.content, "html.parser")
            tmp = page.select('div.pageNavSimple')[0].find_all('a')[0].text.strip()
            total_pages = tmp.upper().split("OF")[1]
            return total_pages
        else:
            return 0
    
    def updateThreadInfo(self, type, includeGameInfo):
        #type new full
        #includeGameInfo bool 
        print("Downloading thread info")