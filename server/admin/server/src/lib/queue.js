// ---------------------------------------------------------------------------
// LewdCorner review-queue resolution, ported from reconcile_lc.py's queue job.
// Items land in lc_review_queue when the scraper couldn't unambiguously link
// an LC thread to an atlas game. A human resolves each by:
//   • linking it to an existing candidate atlas row,
//   • creating it as a brand-new atlas row, or
//   • dismissing it (drop from queue, make no link).
// Candidates are re-derived live so the queue survives atlas changes.
// ---------------------------------------------------------------------------
import { q, q1, tx } from './db.js';
import { findFuzzyAtlasCandidates, findAtlasIdsByIdName } from './candidates.js';
import { logAudit, EDITABLE_ATLAS_COLUMNS } from './atlas.js';

export async function getQueue(kind) {
  if (kind) {
    return q(
      `SELECT * FROM lc_review_queue WHERE match_kind = ?
       ORDER BY first_seen, lc_id`, [kind]);
  }
  return q('SELECT * FROM lc_review_queue ORDER BY first_seen, lc_id');
}

export async function getQueueItem(lcId) {
  return q1('SELECT * FROM lc_review_queue WHERE lc_id = ? LIMIT 1', [lcId]);
}

/** Live candidate atlas_ids for a queue item (fuzzy or exact id_name). */
export async function candidatesFor(item) {
  const kind = item.match_kind || 'multi';
  let live = kind === 'fuzzy'
    ? await findFuzzyAtlasCandidates(item.short_name, item.creator)
    : await findAtlasIdsByIdName(item.id_name);
  if (!live || !live.length) {
    // fall back to the stored snapshot
    live = (item.candidate_ids || '').split(',').map((s) => Number(s.trim())).filter(Boolean);
  }
  return live;
}

function parseJson(s, fallback) {
  try { return s ? JSON.parse(s) : fallback; } catch { return fallback; }
}

/** Upsert a lewdcorner row (column->value dict) linked to atlasId. */
async function upsertLewdcorner(conn, payload) {
  const cols = Object.keys(payload);
  if (!cols.length) return;
  const placeholders = cols.map(() => '?').join(', ');
  const updates = cols.map((c) => `${c}=VALUES(${c})`).join(', ');
  const params = cols.map((c) => (typeof payload[c] === 'boolean' ? Number(payload[c]) : payload[c]));
  await conn.execute(
    `INSERT INTO lewdcorner (${cols.join(', ')}) VALUES (${placeholders})
     ON DUPLICATE KEY UPDATE ${updates}`, params);
}

/** Link a queue item to an existing atlas row. */
export async function linkQueueItem(lcId, atlasId, user) {
  const item = await getQueueItem(lcId);
  if (!item) throw Object.assign(new Error('Queue item not found.'), { status: 404 });
  const lcPayload = parseJson(item.lc_payload, {});
  lcPayload.atlas_id = Number(atlasId);
  lcPayload.lc_id = Number(lcId);

  await tx(async (conn) => {
    await upsertLewdcorner(conn, lcPayload);
    await conn.execute('DELETE FROM lc_review_queue WHERE lc_id = ?', [lcId]);
    await logAudit(conn, {
      atlasId: Number(atlasId), field: 'lc.link', user,
      oldValue: `lc_id ${lcId} (queued, ${item.match_kind})`,
      newValue: `linked lc_id ${lcId} -> atlas_id ${atlasId}`,
    });
  });
  return { linked: true, atlas_id: Number(atlasId) };
}

/** Create a fresh atlas row from the queued payload, then link the LC row. */
export async function newFromQueueItem(lcId, user) {
  const item = await getQueueItem(lcId);
  if (!item) throw Object.assign(new Error('Queue item not found.'), { status: 404 });
  const atlasPayload = parseJson(item.atlas_payload, {});
  delete atlasPayload.atlas_id;
  const lcPayload = parseJson(item.lc_payload, {});
  lcPayload.lc_id = Number(lcId);

  let newAtlasId;
  await tx(async (conn) => {
    const cols = Object.keys(atlasPayload);
    const placeholders = cols.map(() => '?').join(', ');
    const params = cols.map((c) => (typeof atlasPayload[c] === 'boolean' ? Number(atlasPayload[c]) : atlasPayload[c]));
    const [res] = await conn.execute(
      `INSERT INTO atlas (${cols.join(', ')}) VALUES (${placeholders})`, params);
    newAtlasId = res.insertId;
    lcPayload.atlas_id = newAtlasId;
    await upsertLewdcorner(conn, lcPayload);
    await conn.execute('DELETE FROM lc_review_queue WHERE lc_id = ?', [lcId]);
    await logAudit(conn, {
      atlasId: newAtlasId, field: 'lc.new', user,
      oldValue: `lc_id ${lcId} (queued, ${item.match_kind})`,
      newValue: `created atlas_id ${newAtlasId} and linked lc_id ${lcId}`,
    });
  });
  return { created: true, atlas_id: newAtlasId };
}

/** Drop a queue item without making any link. */
export async function dismissQueueItem(lcId, user) {
  const item = await getQueueItem(lcId);
  if (!item) throw Object.assign(new Error('Queue item not found.'), { status: 404 });
  await tx(async (conn) => {
    await conn.execute('DELETE FROM lc_review_queue WHERE lc_id = ?', [lcId]);
    await logAudit(conn, {
      atlasId: null, field: 'lc.dismiss', user,
      oldValue: `lc_id ${lcId} (queued, ${item.match_kind})`, newValue: 'dismissed',
    });
  });
  return { dismissed: true };
}

export { EDITABLE_ATLAS_COLUMNS };
