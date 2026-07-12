// ---------------------------------------------------------------------------
// Source-ownership + merge/relink helpers for the admin tool's duplicate model.
//
// MODEL (per requirement 2):
//   * Source rows (f95_zone / lewdcorner / dlsite / sxs) are NEVER deleted.
//     They can be relinked to a different atlas_id, or set "floating"
//     (atlas_id = NULL, floating = 1) meaning linked to no atlas game.
//   * Many source rows may share one atlas_id (the UNIQUE constraint was
//     dropped in migration 002).
//   * Atlas rows CAN be deleted, but only as duplicates and only once nothing
//     references them. Because a FOREIGN KEY still protects atlas_id, the DB
//     itself refuses to delete a still-referenced atlas row — we surface that
//     as an orphan prompt rather than forcing it.
// ---------------------------------------------------------------------------
import { q, q1, tx } from './db.js';
import { logAudit } from './atlas.js';

// Sources that support floating (migration 002 relaxed these two). dlsite/sxs
// still have NOT NULL/UNIQUE atlas_id, so they can be relinked but not floated
// until migration 002 is extended to them.
const SOURCE_TABLES = [
  { table: 'f95_zone', idCol: 'f95_id', floatable: true },
  { table: 'lewdcorner', idCol: 'lc_id', floatable: true },
  { table: 'dlsite', idCol: 'dlsite_id', floatable: false },
  { table: 'sxs', idCol: 'sxs_id', floatable: false },
];

const SOURCE_BY_NAME = Object.fromEntries(SOURCE_TABLES.map((s) => [s.table, s]));
const now = () => Math.floor(Date.now() / 1000);

/** List of source table names that reference this atlas_id. */
export async function getSourceOwners(atlasId) {
  const owners = [];
  for (const { table } of SOURCE_TABLES) {
    const row = await q1(`SELECT 1 FROM ${table} WHERE atlas_id = ? LIMIT 1`, [atlasId]);
    if (row) owners.push(table);
  }
  return owners;
}

/** { f95_id: [...], lc_id: [...] } for each source referencing this atlas_id. */
export async function getSourceIds(atlasId) {
  const out = {};
  for (const { table, idCol } of SOURCE_TABLES) {
    const rows = await q(`SELECT ${idCol} AS v FROM ${table} WHERE atlas_id = ?`, [atlasId]);
    if (rows.length) out[idCol] = rows.length === 1 ? rows[0].v : rows.map((r) => r.v);
  }
  return out;
}

/**
 * Detailed source rows referencing an atlas_id, including site_url, so the UI
 * can render clickable links. Returns e.g.
 *   [{ source:'f95_zone', idCol:'f95_id', id: 123, site_url:'https://...' }, ...]
 */
export async function getSourceLinks(atlasId) {
  const out = [];
  for (const { table, idCol } of SOURCE_TABLES) {
    const rows = await q(
      `SELECT ${idCol} AS id, site_url FROM ${table} WHERE atlas_id = ?`, [atlasId]);
    for (const r of rows) out.push({ source: table, idCol, id: r.id, site_url: r.site_url });
  }
  return out;
}

/** True if no source row references this atlas_id (safe to delete). */
export async function isAtlasOrphaned(atlasId) {
  return (await getSourceOwners(atlasId)).length === 0;
}

/**
 * ATLAS-duplicate merge. Two+ atlas rows are the same game; keep one.
 *   - Every source row on a losing atlas_id is repointed to the survivor
 *     (many->one is now allowed, so no conflicts).
 *   - Each losing atlas row is then deleted (it is guaranteed orphaned once
 *     its sources have moved). Source rows are never deleted.
 */
export async function mergeAtlasGroup({ survivorId, groupIds, user }) {
  survivorId = Number(survivorId);
  const others = [...new Set(groupIds.map(Number))].filter((id) => id !== survivorId);
  if (!others.length) return { relinked: [], deleted: [] };

  const relinked = [];
  const deleted = [];

  await tx(async (conn) => {
    for (const aid of others) {
      for (const { table, idCol } of SOURCE_TABLES) {
        const [rows] = await conn.execute(
          `SELECT ${idCol} AS v FROM ${table} WHERE atlas_id = ?`, [aid]);
        if (!rows.length) continue;
        await conn.execute(
          `UPDATE ${table} SET atlas_id = ? WHERE atlas_id = ?`, [survivorId, aid]);
        relinked.push({ from: aid, to: survivorId, source: table, ids: rows.map((r) => r.v) });
        await logAudit(conn, {
          atlasId: survivorId, field: 'merge.relink', user,
          oldValue: `${table} atlas_id ${aid}`, newValue: `${table} atlas_id ${survivorId}`,
        });
      }
      // Sources moved off aid; it is now orphaned -> delete the atlas row.
      await conn.execute('DELETE FROM atlas WHERE atlas_id = ?', [aid]);
      deleted.push(aid);
      await logAudit(conn, {
        atlasId: aid, field: 'merge.delete', user,
        oldValue: `atlas_id ${aid} (duplicate merged into ${survivorId})`, newValue: null,
      });
    }
    await conn.execute(
      'UPDATE atlas SET edited = 1, edited_at = ?, edited_by = ? WHERE atlas_id = ?',
      [now(), user, survivorId]);
  });

  return { relinked, deleted };
}

/**
 * Relink or float ONE source row (identified by table + source id).
 *   action = 'float'          -> atlas_id = NULL, floating = 1
 *   action = 'link', atlasId  -> atlas_id = <atlasId>, floating = 0
 *
 * Returns { previousAtlasId, orphaned } where `orphaned` is the previous
 * atlas_id if moving this row left it with no remaining sources (so the caller
 * can prompt to delete it). The atlas row is NOT deleted here.
 */
export async function relinkSource({ table, sourceId, action, atlasId, user }) {
  const meta = SOURCE_BY_NAME[table];
  if (!meta) throw Object.assign(new Error(`Unknown source table ${table}`), { status: 400 });
  if (action === 'float' && !meta.floatable) {
    throw Object.assign(new Error(`${table} rows cannot float yet (schema not migrated).`), { status: 400 });
  }

  const row = await q1(
    `SELECT ${meta.idCol} AS id, atlas_id FROM ${table} WHERE ${meta.idCol} = ? LIMIT 1`,
    [sourceId]);
  if (!row) throw Object.assign(new Error('Source row not found.'), { status: 404 });
  const previousAtlasId = row.atlas_id;

  if (action === 'link') {
    const target = Number(atlasId);
    if (!target) throw Object.assign(new Error('Choose an atlas game to link to.'), { status: 400 });
    const exists = await q1('SELECT 1 FROM atlas WHERE atlas_id = ? LIMIT 1', [target]);
    if (!exists) throw Object.assign(new Error(`No atlas row #${target}.`), { status: 404 });
  }

  await tx(async (conn) => {
    if (action === 'float') {
      await conn.execute(
        `UPDATE ${table} SET atlas_id = NULL, floating = 1 WHERE ${meta.idCol} = ?`, [sourceId]);
      await logAudit(conn, {
        atlasId: previousAtlasId, field: `${table}.float`, user,
        oldValue: `${meta.idCol} ${sourceId} -> atlas_id ${previousAtlasId}`,
        newValue: `${meta.idCol} ${sourceId} floating`,
      });
    } else {
      await conn.execute(
        `UPDATE ${table} SET atlas_id = ?, floating = 0 WHERE ${meta.idCol} = ?`,
        [Number(atlasId), sourceId]);
      await logAudit(conn, {
        atlasId: Number(atlasId), field: `${table}.link`, user,
        oldValue: `${meta.idCol} ${sourceId} -> atlas_id ${previousAtlasId ?? 'floating'}`,
        newValue: `${meta.idCol} ${sourceId} -> atlas_id ${atlasId}`,
      });
    }
  });

  let orphaned = null;
  if (previousAtlasId != null && previousAtlasId !== Number(atlasId)) {
    if (await isAtlasOrphaned(previousAtlasId)) orphaned = previousAtlasId;
  }
  return { previousAtlasId, orphaned };
}

/** Delete an atlas row, but only if it is genuinely orphaned. */
export async function deleteAtlasIfOrphaned({ atlasId, user }) {
  atlasId = Number(atlasId);
  if (!(await isAtlasOrphaned(atlasId))) {
    throw Object.assign(
      new Error('That atlas row is still linked to a source and was not deleted.'),
      { status: 409 });
  }
  await tx(async (conn) => {
    await conn.execute('DELETE FROM atlas WHERE atlas_id = ?', [atlasId]);
    await logAudit(conn, {
      atlasId, field: 'atlas.delete', user,
      oldValue: `atlas_id ${atlasId} (orphaned, deleted on confirm)`, newValue: null,
    });
  });
  return { deleted: atlasId };
}
