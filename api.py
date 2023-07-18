import asyncio
from sys import platform
from scraper.agents.f95 import *
from scraper.utils.directory_manager import *
from scraper.types.eTypes import *
from scraper.utils.packager import *
from scraper.agents.dlsite import *

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
# f95.downloadThreadSummary(f95, download.NEW, True, database_connection)
dlsite.updateCircleID(database_connection)
# print(asyncio.run(dlsite.getTitleID("RJ303564")))
# Package data based on date. As of right now it will output a full db dump.
# packager.createPackage(database_connection)
