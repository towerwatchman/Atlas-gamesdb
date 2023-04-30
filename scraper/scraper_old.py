import requests
from urllib.request import urlopen
from bs4 import BeautifulSoup
from datetime import datetime
from db import *
import re
import time
#import ctypes for msg.box

#Delete all vales in table. Used for Debugging
#truncateF95Table()
#deleteDatabase()
#createDatabase()

for c in range(679,683):
    #time.sleep(1) # do not overload thread or website
    #URL will be updated if changes are needed. The URL Below is only the first page
    URL = "https://f95zone.to/forums/games.2/?order=title&direction=asc"
    if(c > 1):  
        URL = "https://f95zone.to/forums/games.2/page-"+str(c)+"?order=title&direction=asc" #alphabetical
        print("---- Starting Page:",str(c),"----")
    page = requests.get(URL)
    if(page.status_code == 200):   
        soup = BeautifulSoup(page.content, "html.parser")
        job_elements = soup.find_all("div", class_="structItem-title")
        
        verArr = ['V0','V1','FINAL', 'PROLOGUE', 'ALPHA', 'BETA', 'DEMO', 'CH.', 'CHAPTER', 'UPDATE', 'EPISODE', 'EP.']
        otherArr = ['[READ ME]', '[SITERIP]', '[COLLECTION]', '[VN]']
        engineArr = ['[OTHERS]', '[RAGS]', '[RPGM]', '[WEBGL]', '[UNITY]', '[HTML]', '[QSP]', '[JAVA]', '[REN\'PY]',
                     '[UNREAL ENGINE]', '[WOLF RPG]', '[FLASH]', '[ADRIFT]', '[TADS]']
        statusArr = ['[COMPLETED]', '[ONHOLD]', '[ABANDONED]']

        for job_element in job_elements:            
            print("-------")
            f95_id=""
            short_name = ""
            other=""
            engine=""
            banner_url=""
            title=""
            status=""
            version=""
            developer=""
            site_url=""
            overview = ""
            thread_update = ""
            release_date = ""
            censored = ""      
            language = ""
            translations=""
            length=""
            vndb=""
            genre = ""
            voice = ""
            os = ""
            other_games = ""
            views = ""
            likes = ""
            tags = ""
            rating = ""
            screens = ""
            
            links = job_element.find_all("a")
            for link in links:
                prefix = link.text            
                #verify engine is not null and we are not trying to store sticky threads
                if(prefix != "" and prefix != "[READ ME]"):
                    href = link['href']
                    if(prefix.upper() in otherArr):
                        other = prefix.replace('[',"").replace(']',"")
                        #print("Other:", other)
                    elif(prefix.upper() in engineArr):
                        engine = prefix.replace('[',"").replace(']',"")
                        #print("Engine:",engine)
                    elif(prefix.upper() in statusArr):
                        status = prefix.replace('[',"").replace(']',"")
                        #print("Status:",status)
                    else: # game name parse
                        strings = prefix.split('[')
                        title = strings[0].replace('[',"").replace(']',"")
                        if len(strings) == 2:
                            #ctypes.windll.user32.MessageBoxW(0, ("Error " + strings[1] ), "Your title", 1)
                            tmp = re.sub('[\W_]+', '',strings[1].strip().replace('[',"").replace(']',"")).upper()                           
                            if(tmp in verArr): #check if this is version or dev
                                version = strings[1].replace('[',"").replace(']',"")
                            else:
                                developer = strings[1].replace('[',"").replace(']',"")
                        elif len(strings) == 3:
                            version = strings[1].replace('[',"").replace(']',"")
                            developer = strings[2].replace('[',"").replace(']',"")
                            
                        f95_id = re.sub('[\W_]+', '',href.split(".")[len(href.split(".")) - 1])
                        short_name = re.sub('[\W_]+', '',title.strip().replace(" ","")).upper()
                       
                        #print("Version:", version)
                        #print("Developer:", developer)
                    
                    if('/forums/games.2/' not in href):
                        time.sleep(1) # wait another sec before getting individual page info
                        site_url = "https://f95zone.to" + href
                        #print("site_url:", site_url)
                        #HERE IS WHERE WE LOAD THE INDIVIDUAL PAGE TO SCRAPE ADDITIONAL DATA
                        gpage = requests.get(site_url)
                        if(gpage.status_code == 200):   
                            gsoup = BeautifulSoup(gpage.content, "html.parser")
                            job_elements = gsoup.find_all("div", class_="bbWrapper")
                            #title = gsoup.select('h1.p-title-value')[0].text.strip()
                            try:
                                rating = gsoup.select('span.ratingStars')[0].text.strip().replace("star(s)","").strip()
                            except:
                                rating = ""

                            try:
                                overview = job_elements[0].find_all("div")[0].get_text().replace("Overview:","").strip()
                                if len(overview) <= 2:
                                    overview = job_elements[0].find_all("div")[1].get_text().replace("Overview:","").strip()
                                overview = overview.split("\n\n\n", 1)[0]
                                
                            except:
                                overview=""

                            try:
                                #this is wrong change to taglist 
                                genrelist = gsoup.select('span.js-tagList')[0].find_all('a')
                                genre = ""
                                for g in genrelist:
                                    tmp = g.text.strip()
                                    if genre == "":
                                        #first element
                                        genre = tmp
                                    else:
                                        genre = genre + "," + tmp
                            except:
                                genre=""

                            #Likes
                            try:
                                userExtras = gsoup.find("div", class_="message-userExtras").find_all("dd")
                                likes = userExtras[2].get_text()
                            except:
                                likes="error"

                            alinks = job_elements[0].find_all("a")
                            #skip first item since we know that it is banner image
                            screens = ""
                            for link in alinks:
                                try:
                                    img = str(link['href'])
                                    if "attachments" in img:
                                        if screens == "":
                                            screens = link['href']
                                        else:
                                            screens = screens +"," + link['href']
                                except Exception:
                                    pass

                                try:
                                    banner_url = gsoup.find_all("img", class_="bbImage")[0]['src']       
                                except:
                                    banner_url = ""
                                    
                                try:
                                    thread_update = job_elements[0].find('b', text="Thread Updated").next_sibling.strip().replace(":","").strip()
                                except:
                                    try:
                                        thread_update = job_elements[0].find('b', text="Updated").next_sibling.strip().replace(":","").strip()
                                    except:
                                        thread_update = ""
                                    
                                try:
                                    release_date = job_elements[0].find('b', text="Release Date").next_sibling.strip().replace(":","").strip()
                                except:
                                    try:
                                        release_date = job_elements[0].find('b', text="Year:").next_sibling.strip().replace(":","").strip()
                                    except:
                                        release_date = ""
                                    
                                try:
                                    censored = job_elements[0].find('b', text="Censored").next_sibling.strip().replace(":","").strip()
                                        
                                except:
                                    try:
                                        censored = job_elements[0].find('b', text="Censored:").next_sibling.strip().replace(":","").strip()
                                    except:
                                        try:
                                            censored = job_elements[0].find('b', text="Censorship:").next_sibling.strip().replace(":","").strip()                    
                                        except:
                                            censored = ""

                                try:
                                    os = job_elements[0].find('b', text="OS").next_sibling.strip().replace(":","").strip()
                                except:
                                    try:
                                        os = job_elements[0].find('b', text="Platforms:").next_sibling.strip().replace(":","").strip()
                                    except:
                                        os = ""
                                    
                                try:
                                    language = job_elements[0].find('b', text="Language").next_sibling.strip().replace(":","").strip()
                                except:
                                    try:
                                        language = job_elements[0].find('b', text="Language:").next_sibling.strip().replace(":","").strip()
                                    except:
                                        language = ""

                                try:
                                    translations = job_elements[0].find('b', text="Translations:").next_sibling.strip().replace(":","").strip()
                                except:
                                    translations = ""

                                try:
                                    length = job_elements[0].find('b', text="Length").next_sibling.strip().replace(":","").strip()
                                except:
                                    try:
                                        length = job_elements[0].find('b', text="Length:").next_sibling.strip().replace(":","").strip()
                                    except:
                                        length = ""

                                try:
                                    voice = job_elements[0].find('b', text="Voice").next_sibling.strip().replace(":","").strip()
                                except:
                                    try:
                                        voice = job_elements[0].find('b', text="Voice:").next_sibling.strip().replace(":","").strip()
                                    except:
                                        voice = ""

                                try:
                                    vndb = job_elements[0].find('b', text="VNDB:").next_sibling.strip().replace(":","").strip()
                                except:
                                    vndb = ""

                            print("ID:",f95_id)
                            print("Title:", title)

                        
                else: break
            #if(f95_id != "" ): #make sure we have data otherwise we are putting blank rows in db
            #    updateF95zoneTableFull(f95_id, short_name, other, engine, banner_url, title, status,
            #                   version, developer, site_url, overview, thread_update,
            #                   release_date, censored, language, translations,length,
            #                   vndb, genre, voice, os, views, likes, tags, rating, screens, datetime.now())
    else:
        break
