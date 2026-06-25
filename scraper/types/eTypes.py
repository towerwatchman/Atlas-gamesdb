from enum import Enum


class download(Enum):
    FULL = 0
    NEW = 1


class database(Enum):
    # SQLite/local support has been removed -- every run uses the same
    # MySQL database. REMOTE is kept (rather than collapsing the enum
    # entirely) so existing call sites that pass a db_type around don't all
    # need to change.
    REMOTE = 1


class record(Enum):
    FOUND = True
    NOT_FOUND = False
