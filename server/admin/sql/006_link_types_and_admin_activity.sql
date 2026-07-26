-- ---------------------------------------------------------------------------
-- 006 — external-link typing/labelling, DLC parents, and admin-activity index
--
-- 1. atlas_manual_links gains:
--      entry_type        'game' | 'dlc'      (store links only: steam/gog/itch)
--      parent_kind       which thing a DLC hangs off
--      parent_link_id    set when parent_kind = 'manual'
--      parent_source_id  set when parent_kind is a source table
--
--    The parent is polymorphic because a DLC can be tied either to another
--    manual store link OR to an F95 / LewdCorner / DLsite / SXS mapping. Two
--    explicit columns rather than one opaque pair, so a manual parent still
--    gets real referential integrity from a foreign key while a source parent
--    (whose id lives in a table this migration doesn't own) is validated in
--    application code.
--
--    Only 'dlc' rows may carry a parent, the parent must belong to the same
--    atlas row, and a DLC cannot parent another DLC. Those rules are enforced
--    in lib/manualLinks.js — CHECK constraints can't express the cross-row
--    parts, and a trigger would fire for the scraper too.
--
-- 2. An index on (admin_user, ts) for the Admin activity page, which groups
--    atlas_audit by admin over a time window.
--
-- Safe to re-run.
-- ---------------------------------------------------------------------------

-- --- 1. Guarded column adds ------------------------------------------------
DROP PROCEDURE IF EXISTS _admin_add_col6;
DELIMITER //
CREATE PROCEDURE _admin_add_col6(
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

-- Existing rows are all plain entries, so 'game' is the right backfill.
CALL _admin_add_col6('atlas_manual_links', 'entry_type',
    "entry_type VARCHAR(16) NOT NULL DEFAULT 'game'");
CALL _admin_add_col6('atlas_manual_links', 'parent_kind',
    'parent_kind VARCHAR(32) NULL');
CALL _admin_add_col6('atlas_manual_links', 'parent_link_id',
    'parent_link_id BIGINT NULL');
CALL _admin_add_col6('atlas_manual_links', 'parent_source_id',
    'parent_source_id VARCHAR(64) NULL');

DROP PROCEDURE IF EXISTS _admin_add_col6;

-- --- 2. Guarded index adds -------------------------------------------------
DROP PROCEDURE IF EXISTS _admin_add_idx6;
DELIMITER //
CREATE PROCEDURE _admin_add_idx6(
    IN tbl VARCHAR(64), IN idx VARCHAR(64), IN cols VARCHAR(255))
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND INDEX_NAME = idx
    ) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD INDEX `', idx, '` (', cols, ')');
        PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;
END//
DELIMITER ;

CALL _admin_add_idx6('atlas_manual_links', 'idx_manual_parent_link',
    'parent_link_id');
CALL _admin_add_idx6('atlas_manual_links', 'idx_manual_atlas_type',
    'atlas_id, entry_type');
-- Admin activity groups by admin over a date range; without this it's a full
-- scan of atlas_audit every time the page loads.
CALL _admin_add_idx6('atlas_audit', 'idx_audit_user_ts', 'admin_user, ts');

DROP PROCEDURE IF EXISTS _admin_add_idx6;

-- --- 3. Guarded foreign key ------------------------------------------------
-- ON DELETE SET NULL, not CASCADE: deleting the base game's link should orphan
-- its DLC rows, not silently delete them. The UI then shows them as unparented
-- so somebody can re-tie or remove them deliberately.
DROP PROCEDURE IF EXISTS _admin_add_fk6;
DELIMITER //
CREATE PROCEDURE _admin_add_fk6()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'atlas_manual_links'
          AND CONSTRAINT_NAME = 'fk_manual_links_parent'
    ) THEN
        ALTER TABLE atlas_manual_links
            ADD CONSTRAINT fk_manual_links_parent
            FOREIGN KEY (parent_link_id) REFERENCES atlas_manual_links(link_id)
            ON DELETE SET NULL;
    END IF;
END//
DELIMITER ;

CALL _admin_add_fk6();
DROP PROCEDURE IF EXISTS _admin_add_fk6;
