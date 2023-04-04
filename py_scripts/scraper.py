from agents.f95agent import *
from utils.db import *

# TEST URL: https://f95zone.to/threads/the-necromancer-arises-prologue-whiteleaf-studio.154250/

CreateLocalDatabase();
f95.downloadThreadInfo(f95, "new", False, GetLastDbUpdate())
