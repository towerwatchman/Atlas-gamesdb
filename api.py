from scraper.agents.f95 import *
from scraper.utils.db import *
from scraper.types.eTypes import *
from scraper.utils.db import *
import json

# TEST URL: https://f95zone.to/threads/the-necromancer-arises-prologue-whiteleaf-studio.154250/
# TEST JSON: https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=list&cat=games&page=1&sort=date&rows=90
database_connection = database.REMOTE
# Create Database for Atlas
# CreateDatabase(database_connection)

# Serializing json
json_object = json.dumps(downloadBase(database_connection))

# Writing to sample.json
with open("sample.json", "w") as outfile:
    outfile.write(json_object)

# f95.downloadThreadSummary(f95, download.NEW, False, database_connection)

# Create bin object with latest data
