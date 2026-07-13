-- ---------------------------------------------------------------------------
-- Atlas Admin — schema migration 003 (idempotent)
--
-- Adds one-time invite codes for self-service admin registration.
--
--   * An admin generates a code from the Admins tab. The RAW code is shown
--     once; only its bcrypt HASH is stored here (like passwords), so someone
--     with DB access still can't use existing codes.
--   * A new user redeems a code on the login page's "Create account" form to
--     create their own username + password. Codes are single-use and expire
--     7 days after creation if unredeemed.
--
-- Run once:  mysql -u root -p games < 003_invite_codes.sql
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS invite_codes (
    invite_id   INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    code_hash   VARCHAR(255) NOT NULL,         -- bcrypt hash of the raw code
    created_by  VARCHAR(64) NOT NULL,          -- admin username who generated it
    created_at  BIGINT NOT NULL,               -- epoch seconds
    expires_at  BIGINT NOT NULL,               -- epoch seconds (created_at + 7d)
    used_at     BIGINT NULL,                   -- epoch seconds when redeemed
    used_by     VARCHAR(64) NULL,              -- username created with this code
    INDEX idx_invite_used (used_at),
    INDEX idx_invite_expires (expires_at)
);
