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
                    atlas_id INT PRIMARY KEY AUTO"""
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
                    release_date BIGINT,
                    length TINYTEXT,
                    banner LONGTEXT,
                    banner_wide LONGTEXT,
                    cover LONGTEXT,
                    logo LONGTEXT,
                    wallpaper LONGTEXT,
                    previews LONGTEXT,
                    last_db_update BIGINT
                );
            """
        )
        return query

    def createF95Table(type):
        query = """
                CREATE TABLE IF NOT EXISTS f95_zone (
                    f95_id INT NOT NULL UNIQUE PRIMARY KEY,
                    atlas_id INT NOT NULL UNIQUE,
                    banner_url LONGTEXT, 
                    site_url LONGTEXT,
                    last_thread_comment BIGINT,
                    thread_publish_date BIGINT,
                    last_record_update BIGINT,
                    views INT,
                    likes INT,
                    tags LONGTEXT,
                    rating DOUBLE,
                    screens LONGTEXT,
                    replies INT,
                    FOREIGN KEY (atlas_id) REFERENCES atlas(atlas_id)
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
        query = """
                CREATE TABLE IF NOT EXISTS updates (
                    date BIGINT PRIMARY KEY NOT NULL,
                    name TINYTEXT NOT NULL,
                    md5 LONGTEXT
                );
            """
        return query

    def createDlsiteCircleTable(type):
        us = ""
        if type == database.REMOTE:
            us = "_"
        query = """
                CREATE TABLE IF NOT EXISTS dlsite_circle (
                    circle_id INT PRIMARY KEY NOT NULL UNIQUE,
                    name TINYTEXT NOT NULL,
                    url LONGTEXT NOT NULL,
                    img LONGTEXT NOT NULL
                );
            """
        return query

    def createDlsiteTable(type):
        query = """
            CREATE TABLE IF NOT EXISTS dlsite (
                dlsite_id INT NOT NULL UNIQUE PRIMARY KEY,
                atlas_id INT NOT NULL UNIQUE,
                circle_id INT NOT NULL,
                banner_url LONGTEXT, 
                site_url LONGTEXT,
                register_date BIGINT,
                views INT,
                likes INT,
                tags LONGTEXT,
                rating DOUBLE,
                screens LONGTEXT,
                FOREIGN KEY (atlas_id) REFERENCES atlas(atlas_id),
                FOREIGN KEY (circle_id) REFERENCES dlsite_circle(circle_id)                
            );
        """
        return query

    def createLewdcornereTable(type):
        query = """
            CREATE TABLE IF NOT EXISTS lewdcorner (
                lc_id INT NOT NULL UNIQUE PRIMARY KEY,
                atlas_id INT NOT NULL UNIQUE,
                banner_url LONGTEXT, 
                site_url LONGTEXT,
                register_date BIGINT,
                views INT,
                likes INT,
                tags LONGTEXT,
                rating DOUBLE,
                screens LONGTEXT,
                FOREIGN KEY (atlas_id) REFERENCES atlas(atlas_id)              
            );
        """
        return query
    
    def createSxsTable(type):
        query = """
            CREATE TABLE IF NOT EXISTS sxs (
                sxs_id INT NOT NULL UNIQUE PRIMARY KEY,
                atlas_id INT NOT NULL UNIQUE,
                banner_url LONGTEXT, 
                site_url LONGTEXT,
                register_date BIGINT,
                views INT,
                likes INT,
                tags LONGTEXT,
                rating DOUBLE,
                screens LONGTEXT,
                FOREIGN KEY (atlas_id) REFERENCES atlas(atlas_id)              
            );
        """
        return query