from enum import Enum


class download(Enum):
    FULL = 0
    NEW = 1


class database(Enum):
    LOCAL = 0
    REMOTE = 1


class record(Enum):
    FOUND = True
    NOT_FOUND = False
