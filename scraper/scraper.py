from agents.f95 import *
from utils.db import *

# from types.dTypes import *

# TEST URL: https://f95zone.to/threads/the-necromancer-arises-prologue-whiteleaf-studio.154250/
# TEST JSON: https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=list&cat=games&page=1&sort=date&rows=90

# CreateLocalDatabase();
# f95.downloadThreadInfo(f95, "new", False, GetLastDbUpdate())

# f95.downloadLatest(f95, True) #(self, Full or Partial)
# f95.getLatestUpdateIds();

# Create Remote Database for Atlas
# CreateRemoteDatabase();
# DeleteLocalDatabase()
CreateLocalDatabase()

f95.downloadThreadInfo(f95, "new", False, 1)
