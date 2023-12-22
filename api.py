import asyncio
import sys
from sys import platform
from scraper.agents.f95 import *
from scraper.utils.directory_manager import *
from scraper.types.eTypes import *
from scraper.utils.packager import *
from scraper.agents.dlsite import *

#Vars
f95_enable = False
f95_full_download = False
dlsite_enable = False
create_package = False
#Check for input arguments and continue
if len(sys.argv) > 1:
    if sys.argv[1] == 'true':
        f95_enable = True
if len(sys.argv) > 2:
    if sys.argv[2] == 'true':
        f95_full_download = True
if len(sys.argv) > 3:
    if sys.argv[3] == 'true':
        dlsite_enable = True
if len(sys.argv) > 4:
    if sys.argv[4] == 'true':
        create_package = True


# Set database type: local is pc (Windows), remote is server (Linux)
# Will need to change eventually to check db type as well. This will be a function
if platform == "win32":
    database_connection = database.LOCAL
    print("Running Local")
else:
    database_connection = database.REMOTE
    print("Running Remote")

# Create folders: local is windows, remote is linux
createDirectories(database_connection)

# Create Database for Atlas: db will create based on sytem
CreateDatabase(database_connection)


# Download from sources
# F95 : 1st Source
if f95_enable:
    print("Downloading from F95")
    f95.downloadThreadSummary(f95, download.NEW, f95_full_download, database_connection)

if dlsite_enable:
    print("Downloading from DLSITE")
    dlsite.updateCircleID(database_connection, "pro")
    dlsite.updateCircleID(database_connection, "maniax")
    dlsite.updateCircleID(database_connection, "pro")
# dlsite.getIDs(type, database_connection)
#dlsite.getJSONgame(database_connection, "maniax", "RE") # 1704
#dlsite.getJSONgame(database_connection, "maniax", "RJ", 5728, 20000) #5727
# print(asyncio.run(dlsite.getTitleID("RJ303564")))
# Package data based on date. As of right now it will output a full db dump.
if create_package:
    print("Creating Package")
    packager.createPackage(database_connection)

print("All Updates Compelte")
sys.exit()

