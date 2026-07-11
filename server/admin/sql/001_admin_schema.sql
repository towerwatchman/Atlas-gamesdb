-- ---------------------------------------------------------------------------
-- Atlas Admin — schema migration (idempotent)
--
-- This ONLY adds new columns/tables used by the admin tool. It never touches
-- the scraper's existing columns or logic. Safe to run repeatedly.
--
-- Run once against the `games` database, e.g.:
--     mysql -u root -p games < 001_admin_schema.sql
--
-- The admin app connects as a read/write MySQL user (see .env.example) that is
-- SEPARATE from the read-only `apireader` used by updates.php.
-- ---------------------------------------------------------------------------

-- --- 1. Edit-tracking columns on atlas -------------------------------------
-- `edited`     : 1 once a human has changed the row through the admin tool.
-- `edited_at`  : epoch seconds of the most recent human edit.
-- `edited_by`  : username (admin_users.username) of the last human editor.
--
-- MySQL has no "ADD COLUMN IF NOT EXISTS" before 8.0.29, so we guard with a
-- stored procedure that checks information_schema first. This keeps the file
-- runnable on the widest range of MySQL/MariaDB versions.

DROP PROCEDURE IF EXISTS _admin_add_col;
DELIMITER //
CREATE PROCEDURE _admin_add_col(
    IN tbl VARCHAR(64), IN col VARCHAR(64), IN ddl VARCHAR(255))
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = tbl
          AND COLUMN_NAME = col
    ) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN ', ddl);
        PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;
END//
DELIMITER ;

CALL _admin_add_col('atlas', 'edited',    'edited TINYINT(1) NOT NULL DEFAULT 0');
CALL _admin_add_col('atlas', 'edited_at', 'edited_at BIGINT NULL');
CALL _admin_add_col('atlas', 'edited_by', 'edited_by VARCHAR(64) NULL');

DROP PROCEDURE IF EXISTS _admin_add_col;

-- --- 2. Per-field audit log -------------------------------------------------
-- One row per changed field per save. `field` = 'atlas.<column>' for edits,
-- or an action verb ('merge.relink', 'merge.delete', 'lc.link', 'lc.new',
-- 'lc.dismiss') for structural changes, so the log is a single timeline of
-- everything a human did.
CREATE TABLE IF NOT EXISTS atlas_audit (
    audit_id   BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    atlas_id   INT NULL,
    field      VARCHAR(128) NOT NULL,
    old_value  LONGTEXT NULL,
    new_value  LONGTEXT NULL,
    admin_user VARCHAR(64) NOT NULL,
    ts         BIGINT NOT NULL,
    INDEX idx_audit_atlas (atlas_id),
    INDEX idx_audit_ts (ts)
);

-- --- 3. Admin users ---------------------------------------------------------
-- Passwords are bcrypt hashes (never plaintext). Seed the first admin with
-- `npm run seed` in server/admin/server; further admins are added in the UI.
CREATE TABLE IF NOT EXISTS admin_users (
    user_id       INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    username      VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at    BIGINT NOT NULL,
    last_login    BIGINT NULL
);
