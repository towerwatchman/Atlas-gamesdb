import os
from scraper.types.eTypes import *


class DirectoryManager:
    def __init__(self, folder=""):
        self._folder = folder


def createDirectories(type):
    if type == database.LOCAL:
        if not os.path.exists("C:/packages"):
            os.makedirs("C:/packages")
        if not os.path.exists("C:/packages/backup"):
            os.makedirs("C:/packages/backup")
    if type == database.REMOTE:
        if not os.path.exists("/var/www/html/packages"):
            os.makedirs("/var/www/html/packages")
        if not os.path.exists("/var/www/html/packages/backup"):
            os.makedirs("/var/www/html/packages/backup")


def set_folder(self, x):
    self._folder = x


def get_folder(self):
    return self._folder
