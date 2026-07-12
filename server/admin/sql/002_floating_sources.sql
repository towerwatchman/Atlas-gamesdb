-- ---------------------------------------------------------------------------
-- Atlas Admin — schema migration 002 (idempotent)
--
-- Enables the "floating source game" and "many source rows -> one atlas_id"
-- model used by the admin tool's duplicate handling:
--
--   * atlas_id on each source table becomes NULLable  -> a source row can be
--     "floating" (linked to no atlas game).
--   * the UNIQUE constraint on atlas_id is dropped     -> multiple f95/lc rows
--     may share one atlas_id.
--   * a `floating` flag column is added                -> explicit, queryable
--     marker that a human intentionally unlinked the row.
--   * the FOREIGN KEY on atlas_id is kept              -> still prevents
--     deleting an atlas row that a source still references, and prevents
--     pointing a source row at a non-existent atlas_id.
--
-- VERIFIED SAFE FOR THE SCRAPER: the scraper resolves existing rows by primary
-- key (f95_id / lc_id), always writes a concrete atlas_id, and its
-- ON DUPLICATE KEY UPDATE fires on the primary key — it never relies on
-- atlas_id being NOT NULL or UNIQUE. See f95.py / lewdcorner.py write paths.
--
-- Applies to f95_zone and lewdcorner (the live sources). dlsite / sxs are
-- left unchanged for now; add them here later with the same pattern if needed.
--
-- Run once:  mysql -u root -p games < 002_floating_sources.sql
-- ---------------------------------------------------------------------------

-- --- helper: add a column only if missing ---------------------------------
DROP PROCEDURE IF EXISTS _admin_add_col2;
DELIMITER //
CREATE PROCEDURE _admin_add_col2(
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

-- --- helper: drop an index only if present --------------------------------
DROP PROCEDURE IF EXISTS _admin_drop_idx;
DELIMITER //
CREATE PROCEDURE _admin_drop_idx(IN tbl VARCHAR(64), IN idx VARCHAR(64))
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND INDEX_NAME = idx
    ) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` DROP INDEX `', idx, '`');
        PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;
END//
DELIMITER ;

-- ---------------------------------------------------------------------------
-- IMPORTANT: the UNIQUE key on atlas_id is backed by an index the FOREIGN KEY
-- also uses. MySQL will not drop that index while the FK needs it, so we drop
-- the FK first, drop the unique index, relax the column, then re-add the FK
-- (which recreates a plain non-unique index automatically).
-- FK names are auto-generated; these procedures discover them at runtime.
-- ---------------------------------------------------------------------------

DROP PROCEDURE IF EXISTS _admin_relax_atlas_fk;
DELIMITER //
CREATE PROCEDURE _admin_relax_atlas_fk(IN tbl VARCHAR(64))
BEGIN
    DECLARE fk VARCHAR(64);
    DECLARE uq VARCHAR(64);

    -- 1. find and drop the FK on atlas_id (if any)
    SELECT CONSTRAINT_NAME INTO fk FROM information_schema.KEY_COLUMN_USAGE
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl
        AND COLUMN_NAME = 'atlas_id' AND REFERENCED_TABLE_NAME = 'atlas' LIMIT 1;
    IF fk IS NOT NULL THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` DROP FOREIGN KEY `', fk, '`');
        PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;

    -- 2. drop the UNIQUE index on atlas_id (if still present)
    SELECT INDEX_NAME INTO uq FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl
        AND COLUMN_NAME = 'atlas_id' AND NON_UNIQUE = 0 LIMIT 1;
    IF uq IS NOT NULL THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` DROP INDEX `', uq, '`');
        PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;

    -- 3. make atlas_id NULLable
    SET @s = CONCAT('ALTER TABLE `', tbl, '` MODIFY atlas_id INT NULL');
    PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;

    -- 4. re-add the FK (creates a plain non-unique index; NULLs allowed)
    SET @s = CONCAT('ALTER TABLE `', tbl,
        '` ADD CONSTRAINT `fk_', tbl, '_atlas` FOREIGN KEY (atlas_id) ',
        'REFERENCES atlas(atlas_id)');
    PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
END//
DELIMITER ;

-- --- apply to f95_zone -----------------------------------------------------
CALL _admin_relax_atlas_fk('f95_zone');
CALL _admin_add_col2('f95_zone', 'floating', 'floating TINYINT(1) NOT NULL DEFAULT 0');

-- --- apply to lewdcorner ---------------------------------------------------
CALL _admin_relax_atlas_fk('lewdcorner');
CALL _admin_add_col2('lewdcorner', 'floating', 'floating TINYINT(1) NOT NULL DEFAULT 0');

-- --- cleanup ---------------------------------------------------------------
DROP PROCEDURE IF EXISTS _admin_add_col2;
DROP PROCEDURE IF EXISTS _admin_drop_idx;
DROP PROCEDURE IF EXISTS _admin_relax_atlas_fk;
