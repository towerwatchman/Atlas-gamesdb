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

    def createF95RefreshQueueTable(type=None):
        # Server-side work queue: the Node admin server enqueues an id to be
        # re-scraped; the Python worker (atlas-worker / f95_refresh_worker.py)
        # drains it one item / ~10s. `source` distinguishes which agent should
        # handle the row ('f95' -> f95.refresh_one, 'lc' -> lewdcorner.refresh_one,
        # more as they're added) -- see docs/ATLAS_WORKER.md. The `f95_id`
        # column keeps its historical name but holds any source's id generically
        # (an lc_id, for a source='lc' row); see migration 009 for why it wasn't
        # renamed.
        # No FK to f95_zone/lewdcorner -- a refresh can legitimately be queued
        # for an id that isn't in the DB yet (e.g. a brand-new game an admin
        # spotted). Status: pending -> processing -> done | error.
        query = """
                CREATE TABLE IF NOT EXISTS f95_refresh_queue (
                    queue_id BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
                    f95_id VARCHAR(32) NOT NULL,
                    source VARCHAR(16) NOT NULL DEFAULT 'f95',
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    priority INT NOT NULL DEFAULT 100,
                    requested_by VARCHAR(64),
                    requested_at BIGINT,
                    started_at BIGINT,
                    finished_at BIGINT,
                    attempts INT NOT NULL DEFAULT 0,
                    last_error TEXT,
                    INDEX idx_f95_refresh_status (status, priority, requested_at),
                    INDEX idx_f95_refresh_f95id (f95_id),
                    INDEX idx_f95_refresh_source_id (source, f95_id)
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