// ---------------------------------------------------------------------------
// F95 refresh queue (requirement 4).
//
// The admin server ENQUEUES an f95_id here; the Python cron worker
// (f95_refresh_worker.py) drains it one game every ~10s. This module is the
// server's view of that queue: enqueue, list, summarise, retry, cancel.
//
// It deliberately does NOT run the refresh itself -- Python owns scraping.
// Node only writes intent into f95_refresh_queue and reads status back so
// the admin UI can watch progress. Status: pending -> processing -> done |
// error.
// ---------------------------------------------------------------------------
import { q, q1, write } from './db.js';

const ACTIVE = ['pending', 'processing'];

/** Enqueue an f95_id for refresh. If an unfinished request for the same id
 *  already exists we reuse it (no duplicate work), returning { reused:true }.
 */
export async function enqueue(f95Id, user, priority = 100) {
  const id = String(f95Id).trim();
  if (!/^\d+$/.test(id)) {
    throw Object.assign(new Error('f95_id must be numeric.'), { status: 400 });
  }
  const existing = await q1(
    `SELECT queue_id FROM f95_refresh_queue
      WHERE f95_id = ? AND status IN ('pending','processing')
      ORDER BY queue_id LIMIT 1`,
    [id],
  );
  if (existing) {
    return { queued: true, reused: true, queue_id: existing.queue_id, f95_id: id };
  }
  const now = Math.floor(Date.now() / 1000);
  const res = await write(
    `INSERT INTO f95_refresh_queue
        (f95_id, status, priority, requested_by, requested_at, attempts)
     VALUES (?, 'pending', ?, ?, ?, 0)`,
    [id, Number(priority) || 100, user || 'admin', now],
  );
  return { queued: true, reused: false, queue_id: res.insertId, f95_id: id };
}

/** Enqueue many ids at once; returns per-id results. */
export async function enqueueMany(f95Ids, user, priority = 100) {
  const out = [];
  for (const raw of f95Ids || []) {
    try {
      out.push(await enqueue(raw, user, priority));
    } catch (err) {
      out.push({ queued: false, f95_id: String(raw), error: err.message });
    }
  }
  return out;
}

/** List queue rows, newest first, optionally filtered by status. Capped. */
export async function list({ status, limit = 100, offset = 0 } = {}) {
  const where = [];
  const params = [];
  if (status) { where.push('status = ?'); params.push(status); }
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

/** Counts by status, for the little dashboard header. */
export async function summary() {
  const rows = await q(
    `SELECT status, COUNT(*) AS n FROM f95_refresh_queue GROUP BY status`);
  const out = { pending: 0, processing: 0, done: 0, error: 0 };
  for (const r of rows) out[r.status] = Number(r.n);
  // Rough ETA to drain the backlog at 1 job / 10s (worker's default pace).
  out.eta_seconds = (out.pending + out.processing) * 10;
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
