-- ---------------------------------------------------------------------------
-- Atlas Admin — schema migration 004 (idempotent)
--
-- Two additions, both scraper-safe:
--
--   1. atlas_manual_links
--      Admin-attached external links (Steam / GOG / Itch.io / custom) that the
--      SCRAPER NEVER TOUCHES. These survive re-scrapes because they live in
--      their own table, not in a source column the scraper overwrites. Each
--      link stores an optional external id AND an optional url (per requirement
--      4a). Many links may hang off one atlas_id.
--
--   2. lc_review_queue.deferred_at
--      A nullable epoch marker so an admin can "send a queue item to the
--      bottom" (requirement 6). Deferred items sort AFTER non-deferred ones,
--      then by their defer time, so repeatedly deferring keeps cycling the
--      list without ever losing an item. NULL = not deferred (normal order).
--
-- Run once:  mysql -u root -p games < 004_manual_links_and_queue_defer.sql
-- ---------------------------------------------------------------------------

-- --- 1. Manual external links ----------------------------------------------
-- `kind`  : 'steam' | 'gog' | 'itch' | 'custom' (free text; UI constrains it).
-- `label` : display label, mainly for 'custom' (e.g. "Patreon"). NULL for the
--           known stores, which the UI labels itself.
-- `ext_id`: the store/app id, e.g. a Steam appid. Optional.
-- `url`   : the full link. Optional. At least one of ext_id / url is expected,
--           enforced in the app layer (kept lenient here for easy migration).
--
-- The FK is intentionally ON DELETE CASCADE: if an atlas row is ever deleted
-- (only happens for orphaned duplicates), its manual links go with it.
CREATE TABLE IF NOT EXISTS atlas_manual_links (
    link_id   BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    atlas_id  INT NOT NULL,
    kind      VARCHAR(32) NOT NULL,
    label     VARCHAR(128) NULL,
    ext_id    VARCHAR(255) NULL,
    url       VARCHAR(1024) NULL,
    added_by  VARCHAR(64) NOT NULL,
    added_at  BIGINT NOT NULL,
    INDEX idx_manual_atlas (atlas_id),
    CONSTRAINT fk_manual_links_atlas
        FOREIGN KEY (atlas_id) REFERENCES atlas(atlas_id) ON DELETE CASCADE
);

-- --- 2. Queue defer marker -------------------------------------------------
-- Guarded add so the file is safe on MySQL/MariaDB versions without
-- "ADD COLUMN IF NOT EXISTS".
DROP PROCEDURE IF EXISTS _admin_add_col4;
DELIMITER //
CREATE PROCEDURE _admin_add_col4(
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

CALL _admin_add_col4('lc_review_queue', 'deferred_at', 'deferred_at BIGINT NULL');

DROP PROCEDURE IF EXISTS _admin_add_col4;
