// ---------------------------------------------------------------------------
// Refresh queue (requirement 4).
//
// The admin server ENQUEUES an id here; the Python worker (atlas-worker /
// f95_refresh_worker.py) drains it one item every ~10s, dispatching to
// whichever agent matches a row's `source` ('f95' or 'lc'; see
// docs/ATLAS_WORKER.md for what adding a third looks like). This module is the
// server's view of that queue: enqueue, list, summarise, retry, cancel.
//
// It deliberately does NOT run the refresh itself -- Python owns scraping.
// Node only writes intent into f95_refresh_queue and reads status back so
// the admin UI can watch progress. Status: pending -> processing -> done |
// error.
//
// `source` defaults to 'f95' everywhere below so every existing caller (the
// F95 Refresh page) keeps working unchanged without passing it.
// ---------------------------------------------------------------------------
import { q, q1, write } from './db.js';

const ACTIVE = ['pending', 'processing'];
export const REFRESH_SOURCES = ['f95', 'lc'];
const SOURCE_SET = new Set(REFRESH_SOURCES);

function normaliseSource(source) {
  const s = String(source || 'f95').toLowerCase().trim();
  if (!SOURCE_SET.has(s)) {
    throw Object.assign(
      new Error(`Unknown refresh source "${source}". Expected one of: ${REFRESH_SOURCES.join(', ')}.`),
      { status: 400 });
  }
  return s;
}

/** Enqueue an id for refresh under `source`. If an unfinished request for the
 *  same (source, id) already exists we reuse it (no duplicate work), returning
 *  { reused:true }. Scoped by source together with id: an lc_id and an f95_id
 *  that happen to share a numeric value must not collide.
 */
export async function enqueue(itemId, user, priority = 100, source = 'f95') {
  const src = normaliseSource(source);
  const id = String(itemId).trim();
  if (!/^\d+$/.test(id)) {
    throw Object.assign(new Error('id must be numeric.'), { status: 400 });
  }
  const existing = await q1(
    `SELECT queue_id FROM f95_refresh_queue
      WHERE source = ? AND f95_id = ? AND status IN ('pending','processing')
      ORDER BY queue_id LIMIT 1`,
    [src, id],
  );
  if (existing) {
    return { queued: true, reused: true, queue_id: existing.queue_id, f95_id: id, source: src };
  }
  const now = Math.floor(Date.now() / 1000);
  const res = await write(
    `INSERT INTO f95_refresh_queue
        (f95_id, source, status, priority, requested_by, requested_at, attempts)
     VALUES (?, ?, 'pending', ?, ?, ?, 0)`,
    [id, src, Number(priority) || 100, user || 'admin', now],
  );
  return { queued: true, reused: false, queue_id: res.insertId, f95_id: id, source: src };
}

/** Enqueue many ids at once (all the same source); returns per-id results. */
export async function enqueueMany(itemIds, user, priority = 100, source = 'f95') {
  const out = [];
  for (const raw of itemIds || []) {
    try {
      out.push(await enqueue(raw, user, priority, source));
    } catch (err) {
      out.push({ queued: false, f95_id: String(raw), source, error: err.message });
    }
  }
  return out;
}

/** List queue rows, newest first, optionally filtered by status and/or source. Capped. */
export async function list({ status, source, limit = 100, offset = 0 } = {}) {
  const where = [];
  const params = [];
  if (status) { where.push('status = ?'); params.push(status); }
  if (source) { where.push('source = ?'); params.push(normaliseSource(source)); }
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const lim = Math.min(Math.max(parseInt(limit, 10) || 100, 1), 500);
  const off = Math.max(parseInt(offset, 10) || 0, 0);
  const rows = await q(
    `SELECT * FROM f95_refresh_queue
       ${whereSql}
       ORDER BY (status = 'processing') DESC,
                (status = 'pending') DESC,
                COALESCE(finished_at, started_at, requested_at) DESC,
                queue_id DESC
       LIMIT ${lim} OFFSET ${off}`,
    params,
  );
  const countRow = await q1(
    `SELECT COUNT(*) AS n FROM f95_refresh_queue ${whereSql}`, params);
  return { rows, total: countRow ? countRow.n : 0, limit: lim, offset: off };
}

/** Counts by status, for the little dashboard header, plus a breakdown by
 *  source now that the queue can carry more than one. */
export async function summary() {
  const rows = await q(
    `SELECT status, COUNT(*) AS n FROM f95_refresh_queue GROUP BY status`);
  const out = { pending: 0, processing: 0, done: 0, error: 0 };
  for (const r of rows) out[r.status] = Number(r.n);
  // Rough ETA to drain the backlog at 1 job / 10s (worker's default pace),
  // shared across all sources -- they're the same queue on the same worker.
  out.eta_seconds = (out.pending + out.processing) * 10;

  const bySourceRows = await q(
    `SELECT source, COUNT(*) AS n FROM f95_refresh_queue
      WHERE status IN ('pending','processing') GROUP BY source`);
  out.by_source = Object.fromEntries(REFRESH_SOURCES.map((s) => [s, 0]));
  for (const r of bySourceRows) out.by_source[r.source] = Number(r.n);
  return out;
}

/** Requeue a finished/errored/stuck item (back to pending). */
export async function retry(queueId, user) {
  const row = await q1(
    'SELECT * FROM f95_refresh_queue WHERE queue_id = ? LIMIT 1', [queueId]);
  if (!row) throw Object.assign(new Error('Queue item not found.'), { status: 404 });
  const now = Math.floor(Date.now() / 1000);
  await write(
    `UPDATE f95_refresh_queue
        SET status = 'pending', requested_by = ?, requested_at = ?,
            started_at = NULL, finished_at = NULL, last_error = NULL
      WHERE queue_id = ?`,
    [user || row.requested_by || 'admin', now, queueId],
  );
  return { retried: true, queue_id: Number(queueId) };
}

/** Cancel a pending item (can't cancel one already processing/done). */
export async function cancel(queueId) {
  const row = await q1(
    'SELECT status FROM f95_refresh_queue WHERE queue_id = ? LIMIT 1', [queueId]);
  if (!row) throw Object.assign(new Error('Queue item not found.'), { status: 404 });
  if (!ACTIVE.includes(row.status)) {
    // done/error rows are just deleted (clearing history); pending is a cancel.
    await write('DELETE FROM f95_refresh_queue WHERE queue_id = ?', [queueId]);
    return { removed: true, queue_id: Number(queueId) };
  }
  if (row.status === 'processing') {
    throw Object.assign(
      new Error('That item is being processed right now; try again shortly.'),
      { status: 409 });
  }
  await write('DELETE FROM f95_refresh_queue WHERE queue_id = ?', [queueId]);
  return { cancelled: true, queue_id: Number(queueId) };
}

/** Clear all finished (done + error) rows -- housekeeping. */
export async function clearFinished() {
  const res = await write(
    `DELETE FROM f95_refresh_queue WHERE status IN ('done','error')`);
  return { cleared: res.affectedRows };
}
