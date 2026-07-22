-- ---------------------------------------------------------------------------
-- Atlas Admin — schema migration 005 (idempotent)
--
-- f95_refresh_queue: a server-side work queue for on-demand F95 game
-- refreshes (requirement 4). The Node admin server INSERTs a pending row
-- (an f95_id to re-scrape); the Python cron worker (f95_refresh_worker.py)
-- claims one row at a time, oldest / lowest-priority first, refreshes that
-- game, and flips the row to done/error. Paced at one game every ~10s by
-- the worker itself, not enforced here.
--
-- Status lifecycle: pending -> processing -> done | error
--
-- No FK to f95_zone on purpose: an admin can legitimately queue a refresh
-- for a brand-new thread id that isn't in the DB yet (the refresh will
-- create it). The Python schema builder (scraper/tables/base.py ->
-- createF95RefreshQueueTable) creates the same table; this migration exists
-- so a DB that's only ever managed by the Node side can be brought up to
-- date without running the Python schema step.
--
-- Run once:  mysql -u root -p games < 005_f95_refresh_queue.sql
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS f95_refresh_queue (
    queue_id     BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    f95_id       VARCHAR(32) NOT NULL,
    status       VARCHAR(16) NOT NULL DEFAULT 'pending',
    priority     INT NOT NULL DEFAULT 100,
    requested_by VARCHAR(64),
    requested_at BIGINT,
    started_at   BIGINT,
    finished_at  BIGINT,
    attempts     INT NOT NULL DEFAULT 0,
    last_error   TEXT,
    INDEX idx_f95_refresh_status (status, priority, requested_at),
    INDEX idx_f95_refresh_f95id (f95_id)
);
