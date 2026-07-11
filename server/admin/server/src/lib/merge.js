// ---------------------------------------------------------------------------
// Source-ownership + merge helpers, ported from the Python db layer and
// reconcile_lc.py. A merge points every source row (f95_zone / lewdcorner /
// dlsite / sxs) at a chosen SURVIVING atlas_id, then hard-deletes the other
// atlas rows in the group — but ONLY if nothing still references them. An
// atlas row that another source still owns is never deleted.
// ---------------------------------------------------------------------------
import { q, q1, tx } from './db.js';
import { logAudit } from './atlas.js';

const SOURCE_TABLES = [
  { table: 'f95_zone', idCol: 'f95_id' },
  { table: 'dlsite', idCol: 'dlsite_id' },
  { table: 'sxs', idCol: 'sxs_id' },
  { table: 'lewdcorner', idCol: 'lc_id' },
];

/** List of source table names that reference this atlas_id. */
export async function getSourceOwners(atlasId) {
  const owners = [];
  for (const { table } of SOURCE_TABLES) {
    const row = await q1(`SELECT 1 FROM ${table} WHERE atlas_id = ? LIMIT 1`, [atlasId]);
    if (row) owners.push(table);
  }
  return owners;
}

/** { f95_id, lc_id, ... } for each source that references this atlas_id. */
export async function getSourceIds(atlasId) {
  const out = {};
  for (const { table, idCol } of SOURCE_TABLES) {
    const rows = await q(`SELECT ${idCol} AS v FROM ${table} WHERE atlas_id = ?`, [atlasId]);
    if (rows.length) out[idCol] = rows.length === 1 ? rows[0].v : rows.map((r) => r.v);
  }
  return out;
}

/**
 * Merge a duplicate group into one surviving atlas row.
 *   survivorId  — the atlas_id to keep.
 *   groupIds    — all atlas_ids in the group (including the survivor).
 *   user        — admin username for the audit log.
 *
 * Steps, all in one transaction:
 *   1. Repoint every source row on a non-survivor atlas_id to the survivor.
 *      lewdcorner/f95_zone/dlsite/sxs each have atlas_id UNIQUE, so if the
 *      survivor is ALREADY owned by that same source we cannot repoint a
 *      second row onto it — that would be two lc_ids for one game. Those are
 *      reported back as `conflicts` and left untouched for manual handling.
 *   2. Hard-delete any non-survivor atlas row that is now unreferenced.
 *   3. Audit every relink and delete.
 */
export async function mergeGroup({ survivorId, groupIds, user }) {
  survivorId = Number(survivorId);
  const others = [...new Set(groupIds.map(Number))].filter((id) => id !== survivorId);
  if (!others.length) return { relinked: [], deleted: [], kept: [], conflicts: [] };

  const survivorOwners = new Set(await getSourceOwners(survivorId));

  const relinked = [];
  const deleted = [];
  const kept = [];
  const conflicts = [];

  await tx(async (conn) => {
    for (const aid of others) {
      for (const { table, idCol } of SOURCE_TABLES) {
        const [rows] = await conn.execute(
          `SELECT ${idCol} AS v FROM ${table} WHERE atlas_id = ?`, [aid]);
        if (!rows.length) continue;
        if (survivorOwners.has(table)) {
          // Survivor already has a row from this source; can't have two.
          conflicts.push({ atlas_id: aid, source: table, ids: rows.map((r) => r.v) });
          continue;
        }
        await conn.execute(
          `UPDATE ${table} SET atlas_id = ? WHERE atlas_id = ?`, [survivorId, aid]);
        survivorOwners.add(table);
        relinked.push({ from: aid, to: survivorId, source: table, ids: rows.map((r) => r.v) });
        await logAudit(conn, {
          atlasId: survivorId, field: 'merge.relink', user,
          oldValue: `${table} atlas_id ${aid}`,
          newValue: `${table} atlas_id ${survivorId}`,
        });
      }
    }

    // Delete non-survivors that nothing references anymore.
    for (const aid of others) {
      let stillOwned = false;
      for (const { table } of SOURCE_TABLES) {
        const [rows] = await conn.execute(
          `SELECT 1 FROM ${table} WHERE atlas_id = ? LIMIT 1`, [aid]);
        if (rows.length) { stillOwned = true; break; }
      }
      if (stillOwned) { kept.push(aid); continue; }
      await conn.execute('DELETE FROM atlas WHERE atlas_id = ?', [aid]);
      deleted.push(aid);
      await logAudit(conn, {
        atlasId: aid, field: 'merge.delete', user,
        oldValue: `atlas_id ${aid} (orphaned duplicate)`, newValue: null,
      });
    }

    // Mark the survivor as human-touched.
    await conn.execute(
      'UPDATE atlas SET edited = 1, edited_at = ?, edited_by = ? WHERE atlas_id = ?',
      [Math.floor(Date.now() / 1000), user, survivorId]);
  });

  return { relinked, deleted, kept, conflicts };
}
