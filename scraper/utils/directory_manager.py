import os
from scraper.types.eTypes import *


def createDirectories(type):
    if type == database.LOCAL:
        if not os.path.exists("C:\packages"):
            os.makedirs("C:\packages")
