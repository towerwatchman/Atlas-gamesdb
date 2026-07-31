-- ---------------------------------------------------------------------------
-- Atlas Admin — schema migration 009 (idempotent)
--
-- f95_refresh_queue was F95-only: one numeric id column, one agent
-- (f95.refresh_one), one worker. This adds a `source` column so the SAME
-- queue and the SAME worker (atlas-worker) can carry a LewdCorner refresh
-- request too, and any future source after that -- rather than standing up a
-- parallel table/worker per source.
--
-- The `f95_id` column keeps its historical name (renaming it touches every
-- Python/Node file that already reads it, for a purely cosmetic win) but is
-- now used generically as "the id within that source" -- for a source='lc'
-- row, it holds an lc_id. See docs/ATLAS_WORKER.md.
--
-- Existing rows default to source='f95', so nothing already queued or
-- already in history changes meaning.
--
-- Run once:  mysql -u root -p games < 009_refresh_queue_source.sql
-- ---------------------------------------------------------------------------

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'f95_refresh_queue'
       AND COLUMN_NAME = 'source'
);

SET @sql := IF(@col_exists = 0,
    'ALTER TABLE f95_refresh_queue
       ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT ''f95'' AFTER f95_id',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- The existing-request dedup check (enqueue) and the worker's claim query both
-- need to scope by (source, id) together once two sources share this table --
-- otherwise an lc_id that happens to equal a pending f95_id would be reported
-- as "already queued" against the wrong source.
SET @idx_exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'f95_refresh_queue'
       AND INDEX_NAME = 'idx_f95_refresh_source_id'
);

SET @sql := IF(@idx_exists = 0,
    'ALTER TABLE f95_refresh_queue
       ADD INDEX idx_f95_refresh_source_id (source, f95_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
