-- ---------------------------------------------------------------------------
-- 007 — make actions revertible
--
-- atlas_audit records what changed, but not always enough to put it back:
--
--   * `merge.delete` stored the string "atlas_id 123 (duplicate merged into
--     456)" and then DELETEd the row. Every field value was gone.
--   * `merge.relink` stored "f95_zone atlas_id 123" without saying WHICH source
--     rows moved, so an undo couldn't tell them from rows the survivor already
--     owned.
--   * `manual_link.remove` stored a human-readable description, not the row.
--
-- Three columns fix that:
--
--   snapshot   JSON holding exactly what an undo needs. Written at the point of
--              the change, because that is the only moment the old state still
--              exists.
--   batch_id   Groups the audit rows produced by one logical operation. A merge
--              emits several relinks plus a delete; undoing them piecemeal, or
--              in the wrong order, would leave source rows pointing at an atlas
--              row that doesn't exist yet. Reverting works on the batch.
--   revert_of  Set on the audit rows a revert itself writes, so an undo is
--              auditable and shows up as normal history rather than appearing
--              to be a mysterious edit.
--
-- reverted_at / reverted_by mark a row as already undone, so the UI can grey it
-- out and the API can refuse to apply it twice.
--
-- IMPORTANT: this is not retroactive. Rows written before this migration have
-- no snapshot, so anything lossy that already happened stays un-revertible. The
-- API reports that per row with a reason rather than failing halfway through.
--
-- Safe to re-run.
-- ---------------------------------------------------------------------------

DROP PROCEDURE IF EXISTS _admin_add_col7;
DELIMITER //
CREATE PROCEDURE _admin_add_col7(
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

CALL _admin_add_col7('atlas_audit', 'snapshot',    'snapshot LONGTEXT NULL');
CALL _admin_add_col7('atlas_audit', 'batch_id',    'batch_id VARCHAR(40) NULL');
CALL _admin_add_col7('atlas_audit', 'revert_of',   'revert_of BIGINT NULL');
CALL _admin_add_col7('atlas_audit', 'reverted_at', 'reverted_at BIGINT NULL');
CALL _admin_add_col7('atlas_audit', 'reverted_by', 'reverted_by VARCHAR(64) NULL');

DROP PROCEDURE IF EXISTS _admin_add_col7;

DROP PROCEDURE IF EXISTS _admin_add_idx7;
DELIMITER //
CREATE PROCEDURE _admin_add_idx7(
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

-- Reverting works batch-at-a-time, and the history view filters out rows that
-- have already been undone.
CALL _admin_add_idx7('atlas_audit', 'idx_audit_batch', 'batch_id');
CALL _admin_add_idx7('atlas_audit', 'idx_audit_revert_of', 'revert_of');

DROP PROCEDURE IF EXISTS _admin_add_idx7;
