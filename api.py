from scraper.agents.f95 import *
from scraper.utils.directory_manager import *
from scraper.types.eTypes import *
from scraper.utils.packager import *

# Set database type: local is pc, remote is server
database_connection = database.LOCAL

# Create folders: local is windows, remote is linux
createDirectories(database_connection)

# Create Database for Atlas
CreateDatabase(database_connection)

# Download data from f95
#f95.downloadThreadSummary(f95, download.NEW, False, database_connection)

# Package data. if new then create small update
packager.createPackage(database_connection)