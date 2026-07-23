// ---------------------------------------------------------------------------
// Database access layer for the admin tool. MySQL only, connection pooled.
//
// This is a SEPARATE connection from the Python scraper. It uses a read/write
// user so the admin can edit rows; the scraper and the read-only updates.php
// endpoint are untouched.
//
// Table names that ever get interpolated into SQL are whitelisted, mirroring
// the guard in the Python db layer.
// ---------------------------------------------------------------------------
import mysql from 'mysql2/promise';
import { env } from './env.js';

export const ALLOWED_TABLES = new Set([
  'atlas', 'f95_zone', 'updates', 'dlsite', 'dlsite_circle',
  'lewdcorner', 'sxs', 'lc_review_queue', 'atlas_audit', 'admin_users',
  'atlas_manual_links',
]);

export function checkTable(table) {
  if (!ALLOWED_TABLES.has(table)) {
    throw new Error(`Refusing to use non-whitelisted table name: ${table}`);
  }
  return table;
}

const pool = mysql.createPool({
  host: env.DB_HOST,
  port: env.DB_PORT,
  user: env.DB_USER,
  password: env.DB_PASSWORD,
  database: env.DB_NAME,
  waitForConnections: true,
  connectionLimit: 10,
  namedPlaceholders: false,
});

/** Run a query, return rows (array). */
export async function q(sql, params = []) {
  const [rows] = await pool.execute(sql, params);
  return rows;
}

/** Run a query, return the first row or null. */
export async function q1(sql, params = []) {
  const rows = await q(sql, params);
  return rows.length ? rows[0] : null;
}

/** Run a write, return { insertId, affectedRows }. */
export async function write(sql, params = []) {
  const [result] = await pool.execute(sql, params);
  return result;
}

/** Run fn inside a transaction with its own connection. */
export async function tx(fn) {
  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();
    const out = await fn(conn);
    await conn.commit();
    return out;
  } catch (err) {
    await conn.rollback();
    throw err;
  } finally {
    conn.release();
  }
}

export { pool };

/**
 * Bump an atlas row's last_record_update so the daily/base packager
 * (WHERE last_record_update > start_time) actually re-exports it.
 *
 * Any admin-portal action that writes or links an atlas row must call this (or
 * set last_record_update inline), or the change silently fails to reach clients.
 * Accepts a transaction connection so it participates in the caller's tx.
 */
export async function touchAtlas(conn, atlasId, ts = null) {
  if (atlasId == null) return;
  const stamp = ts == null ? Math.floor(Date.now() / 1000) : ts;
  await conn.execute(
    'UPDATE atlas SET last_record_update = ? WHERE atlas_id = ?',
    [stamp, atlasId],
  );
}
