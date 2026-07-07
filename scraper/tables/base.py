from scraper.types.eTypes import *


class query:
    def __init__(self) -> None:
        pass

    def createAtlasTable(type=None):
        query = (
            """
               CREATE TABLE IF NOT EXISTS atlas (
                    atlas_id INTEGER NOT NULL PRIMARY KEY AUTO_INCREMENT,
                    title TINYTEXT NOT NULL, 
                    id_name VARCHAR(255) NOT NULL,
                    short_name TINYTEXT NOT NULL,
                    original_name TINYTEXT,
                    category TINYTEXT,
                    engine TINYTEXT,
                    status TINYTEXT,
                    version TINYTEXT,
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
                    external_ids LONGTEXT,
                    banner LONGTEXT,
                    banner_wide LONGTEXT,
                    cover LONGTEXT,
                    logo LONGTEXT,
                    wallpaper LONGTEXT,
                    previews LONGTEXT,
                    last_record_update BIGINT
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
                    thread_updated BIGINT,
                    last_record_update BIGINT,
                    views INT,
                    likes INT,
                    tags LONGTEXT,
                    rating DOUBLE,
                    screens LONGTEXT,
                    downloads LONGTEXT,
                    patches LONGTEXT,
                    extras LONGTEXT,
                    translations LONGTEXT,
                    replies INT,
                    FOREIGN KEY (atlas_id) REFERENCES atlas(atlas_id)
                );
            """
        return query

    def deleteTable(table):
        query = "DROP TABLE IF EXISTS `" + table + "`;"
        return query

    def createUpdateTable(type=None):
        query = """
                CREATE TABLE IF NOT EXISTS updates (
                    date BIGINT PRIMARY KEY NOT NULL,
                    name TINYTEXT NOT NULL,
                    md5 LONGTEXT,
                    is_full TINYINT(1) NOT NULL DEFAULT 0
                );
            """
        return query

    def createDlsiteCircleTable(type=None):
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
                work_type TINYTEXT,
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
                thread_updated BIGINT,
                last_record_update BIGINT,
                tier TINYTEXT,
                prefixes TINYTEXT,
                views INT,
                likes INT,
                tags LONGTEXT,
                rating DOUBLE,
                screens LONGTEXT,
                downloads LONGTEXT,
                FOREIGN KEY (atlas_id) REFERENCES atlas(atlas_id)              
            );
        """
        return query

    def createLcReviewQueueTable(type=None):
        # Holds LewdCorner feed items that could NOT be unambiguously linked
        # to an atlas game: either the computed id_name matched more than one
        # atlas row (exact multi-match), or it matched none but fuzzy
        # candidates exist (near-miss). These rows are NOT written into the
        # `lewdcorner` table (whose atlas_id is NOT NULL UNIQUE) until a human
        # resolves them via the reconciler CLI. keyed by lc_id so re-scrapes
        # upsert the same pending row rather than piling up duplicates.
        query = """
            CREATE TABLE IF NOT EXISTS lc_review_queue (
                lc_id INT NOT NULL UNIQUE PRIMARY KEY,
                title TINYTEXT NOT NULL,
                creator TINYTEXT,
                version TINYTEXT,
                id_name VARCHAR(255) NOT NULL,
                short_name TINYTEXT,
                site_url LONGTEXT,
                banner_url LONGTEXT,
                match_kind TINYTEXT,
                candidate_ids LONGTEXT,
                lc_payload LONGTEXT,
                atlas_payload LONGTEXT,
                first_seen BIGINT,
                last_seen BIGINT
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