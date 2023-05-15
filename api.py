from scraper.agents.f95 import *
from scraper.utils.db import *
from scraper.types.eTypes import *

# from types.dTypes import *

# TEST URL: https://f95zone.to/threads/the-necromancer-arises-prologue-whiteleaf-studio.154250/
# TEST JSON: https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=list&cat=games&page=1&sort=date&rows=90
database_connection = database.LOCAL
# Create Remote Database for Atlas
CreateDatabase(database_connection)
f95.downloadThreadInfo(f95, "new", False, 1, database_connection)
# CreateRemoteDatabase()
#  DeleteLocalDatabase()
# CreateDatabase(database.LOCAL)
# DeleteTables(database.REMOTE)

# f95.downloadThreadInfo(f95, "new", False, GetLastDbUpdate())

# f95.downloadLatest(f95, True) #(self, Full or Partial)
# f95.getLatestUpdateIds();
# f95.downloadThreadInfo(f95, "new", False, 1)
