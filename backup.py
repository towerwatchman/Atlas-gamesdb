import asyncio
import sys
from sys import platform
from scraper.types.eTypes import *
from scraper.utils.packager import *
from scraper.utils.db import *

start_time = time.time()
if platform == "win32":
    database_connection = database.LOCAL
    print("Running Local")
else:
    database_connection = database.REMOTE
    print("Running Remote")

#Delete all previous updates
TruncateLocalUpdatesTable()
#Create master update
packager.createPackage(database_connection, 0)