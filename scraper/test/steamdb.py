import os
import requests
from urllib.request import urlopen
import re
import time
import json
import shutil
from datetime import datetime

#Insert Steam IDS here
steam_dict = [
    [1774580, "Unknown", "Jedi Survivor"],
    [1085660, "Unknown", "Destiny 2"],
    [367520, "Unity", "Hollow Knight"],
    [1938090, "Unknown", "COD MW2"],
    [205100, "Unreal", "Dishonored"],
    [257850, "GameMaker", "Hyper Light Drifter"],
    [1737100, "RPGMaker", "Treasure of Nadia" ],
    [1045520, "RenPy", "Acting Lessons"],
    [1731730, "Godot", "Snowy Land"],
    [413150, "XNA", "Stardew Valley"],
    [366250, "Cocos", "Metal Slug"],
    [995460, "Adobe_AIR", "Miracle Snack Shop"],
    [504230, "MonoGame", "Celeste"],
    [1277930, "KiriKiri", "Riddle Joker"]

    ]

#Set base folder directory.
base_dir = 'C:\games_test'

if not os.path.exists(base_dir):
    os.mkdir(base_dir)


for steam_id in steam_dict:
    id = steam_id[0]
    
    game_url = 'https://store.steampowered.com/api/appdetails?appids=' + str(id)
    headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    }
    result = urlopen(game_url).read()
    data = json.loads(result)
    name = re.sub("\W\s", "", data[str(id)]["data"]["name"])
    developers = data[str(id)]["data"]["developers"][0]
    previews = data[str(id)]["data"]["screenshots"]

    print("--- Downloading Data for Game:" + name + " ---")
    p_root = os.path.join(base_dir, developers)
    p_game = os.path.join(p_root, name)
    p_version = os.path.join(p_game, str(id))
    p_previews = os.path.join(p_version, "previews")
    
    print(str(datetime.now()) +  ": Creating folder for game: "+ name)
    if not os.path.exists(p_root):
        os.mkdir(p_root);
    if not os.path.exists(p_game):
        os.mkdir(p_game);
    if not os.path.exists(p_version):
        os.mkdir(p_version);
    if not os.path.exists(p_previews):
        os.mkdir(p_previews);
    
    #download previews
    for preview in previews:
        uri = preview['path_full']
        pid = preview['id']
        print(str(datetime.now()) +  ": Downloading preview: " + uri)
        image = requests.get(uri, stream=True)
        if image.status_code == 200:
            with open(os.path.join(p_previews, str(pid) + ".jpg"),'wb') as f:
                shutil.copyfileobj(image.raw, f)
            print(str(datetime.now()) +  ": Image sucessfully Downloaded")
        else:
            print(str(datetime.now()) +  ": Image Couldn\'t be retrieved")
    
    #Download All other images
    banner_url = 'https://cdn.cloudflare.steamstatic.com/steam/apps/'+str(id)+'/header.jpg'
    cover_url = 'https://cdn.cloudflare.steamstatic.com/steam/apps/'+str(id)+'/library_600x900.jpg'
    banner_w_url = 'https://cdn.cloudflare.steamstatic.com/steam/apps/'+str(id)+'/library_hero.jpg'
    logo_url = 'https://cdn.cloudflare.steamstatic.com/steam/apps/'+str(id)+'/logo.png'
    
    #Banner
    print(str(datetime.now()) +  ": Downloading Banner Image")
    image = requests.get(banner_url, stream=True)
    if image.status_code == 200:
        with open(os.path.join(p_version, "banner.jpg"),'wb') as f:
            shutil.copyfileobj(image.raw, f)
    #cover
    print(str(datetime.now()) +  ": Downloading Cover Image")
    image = requests.get(cover_url, stream=True)
    if image.status_code == 200:
        with open(os.path.join(p_version, "cover.jpg"),'wb') as f:
            shutil.copyfileobj(image.raw, f)
    #Banner Wide
    print(str(datetime.now()) +  ": Downloading Wide Banner Image")
    image = requests.get(banner_w_url, stream=True)
    if image.status_code == 200:
        with open(os.path.join(p_version, "banner_w.jpg"),'wb') as f:
            shutil.copyfileobj(image.raw, f)

    print(str(datetime.now()) +  ": Downloading Logo Image")
    image = requests.get(logo_url, stream=True)
    if image.status_code == 200:
        with open(os.path.join(p_version, "logo.jpg"),'wb') as f:
            shutil.copyfileobj(image.raw, f)
    
    #Adding Exe
    print(str(datetime.now()) +  ": Adding Blank Exe")
    shutil.copyfile(os.path.join(os.getcwd(), "blank.exe"), os.path.join(p_version, "blank.exe"))

    #Create folders based on engine
    engine_dir = os.path.join(os.getcwd(),"engines")
    for engine in os.listdir(engine_dir):
        engine_name = engine.replace("Engine.", "").replace(".txt","")
        if(engine_name == str(steam_id[1])):
            print(str(datetime.now()) +  ": Creating Folder Structure for Engine: " + engine_name)
            folder_structure = open(os.path.join(engine_dir, engine),'r').readlines()
            for item in folder_structure:
                #Remove / from begining of string. Not sure why it is there.....
                if(item[0] == '/'):
                    item = item[1:]
                #Remove newline and replace fwd slash
                item = item.replace('/', '\\').replace('\n', '')
                #assume if there is a '.' it is a file and not a folder
                if(item.__contains__('.')):
                    #Get path if it exist and create all folders
                    folder = os.path.dirname(item)
                    new_folder = os.path.join(p_version, folder)
                    if(folder != ""):
                        if not os.path.exists(new_folder):
                            os.makedirs(new_folder)
                    #create blank files
                    try:
                        open(os.path.join(new_folder,os.path.basename(item)), 'a')
                    except:
                        continue
                else:
                    new_dir = os.path.join(p_version, item)
                    if not os.path.exists(new_dir):
                        os.makedirs(new_dir)
    time.sleep(1) #pause for 1 second