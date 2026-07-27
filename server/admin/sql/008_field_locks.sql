-- ---------------------------------------------------------------------------
-- 008 — per-field locks, so admin edits survive a re-scrape
--
-- The `edited` flag has existed since 001, but nothing ever read it. The
-- scraper's updateAtlasById() writes whatever columns the crawl produced
-- straight over the row, so every admin edit to a scraper-owned field (version,
-- title, developer, overview, tags, ...) was silently reverted the next time
-- that thread was crawled. Editing "worked" and then quietly undid itself.
--
-- `locked_fields` is a JSON array of column names the scraper must not touch on
-- this row, e.g. ["version","title"]. It is maintained by the admin API — a
-- field is locked automatically when a human edits it — and read by
-- scraper/utils/db.py::updateAtlasById, which drops those keys before the
-- UPDATE.
--
-- An array rather than a table because the scraper reads it for every game it
-- updates; one small column on a row it is already touching beats a join. Who
-- locked what and when is already in atlas_audit.
--
-- NOT lockable: last_record_update. That is export bookkeeping, not content —
-- the delta packager uses it to decide what changed. Locking it would freeze a
-- row out of every future package. Admins can still set it by hand (one-off);
-- the scraper stays free to bump it afterwards.
--
-- Safe to re-run.
-- ---------------------------------------------------------------------------
DROP PROCEDURE IF EXISTS _admin_add_col8;
DELIMITER //
CREATE PROCEDURE _admin_add_col8(
    IN tbl VARCHAR(64), IN col VARCHAR(64), IN ddl VARCHAR(255))
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND COLUMN_NAME = col
    ) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN ', ddl);
        PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;
END//
DELIMITER ;

CALL _admin_add_col8('atlas', 'locked_fields', 'locked_fields TEXT NULL');

DROP PROCEDURE IF EXISTS _admin_add_col8;
