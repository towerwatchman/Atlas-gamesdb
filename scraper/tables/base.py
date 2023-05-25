from scraper.types.eTypes import *


class query:
    def __init__(self) -> None:
        pass

    def createAtlasTable(type):
        us = ""
        if type == database.REMOTE:
            us = "_"
        query = (
            """
               CREATE TABLE IF NOT EXISTS atlas (
                    id INTEGER PRIMARY KEY AUTO"""
            + us
            + """INCREMENT,
                    id_name LONGTEXT NOT NULL UNIQUE,
                    short_name TINYTEXT NOT NULL,
                    title TINYTEXT NOT NULL, 
                    original_name TINYTEXT,
                    category TINYTEXT,
                    engine TINYTEXT,
                    status TINYTEXT,
                    version TINYTEXT NOT NULL,
                    developer TINYTEXT,
                    creator TINYTEXT,
                    overview LONGTEXT,
                    censored TINYTEXT,
                    language TINYTEXT,
                    translations TINYTEXT,
                    genre TINYTEXT,
                    tags LONGTEXT,
                    voice TINYTEXT,
                    os TINYTEXT,
                    release_date DATE,
                    length TINYTEXT,
                    banner LONGTEXT,
                    banner_wide LONGTEXT,
                    cover LONGTEXT,
                    logo LONGTEXT,
                    wallpaper LONGTEXT,
                    previews LONGTEXT,
                    last_db_update DATETIME
                );
            """
        )
        return query

    def createF95Table(type):
        query = """
                CREATE TABLE IF NOT EXISTS f95_zone_data (
                    f95_id INT NOT NULL UNIQUE PRIMARY KEY,
                    id INT NOT NULL UNIQUE,
                    banner_url LONGTEXT, 
                    site_url LONGTEXT,
                    last_thread_comment DATETIME,
                    thread_publish_date DATETIME,
                    last_record_update DATETIME,
                    views TINYTEXT,
                    likes TINYTEXT,
                    tags LONGTEXT,
                    rating TINYTEXT,
                    screens LONGTEXT,
                    replies TINYTEXT
                );
            """
        return query

    def createIdSequence(type):
        query = """
                CREATE TABLE IF NOT EXISTS id_sequence (
                    tbl TINYTEXT NOT NULL,
                    id INT NOT NULL
                );
            """
        return query

    def deleteTable(table):
        query = "DROP TABLE IF EXISTS `" + table + "`;"
        return query

    def createUpdateTable(type):
        us = ""
        if type == database.REMOTE:
            us = "_"
        query = (
            """
                CREATE TABLE IF NOT EXISTS updates (
                    id INTEGER PRIMARY KEY AUTO"""
            + us
            + """INCREMENT,
                    file_name TINYTEXT NOT NULL,
                    type TINYTEXT NOT NULL,
                    hash LONGTEXT,
                    last_update DATETIME NOT NULL
                );
            """
        )
        return query
