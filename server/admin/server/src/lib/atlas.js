// ---------------------------------------------------------------------------
// Atlas write + audit helpers. Every human change writes a per-field row to
// atlas_audit and stamps atlas.edited / edited_at / edited_by, so the
// "this row was touched by a human" flag (requirement 1) is always in sync
// with the log.
// ---------------------------------------------------------------------------
import { q, q1, write, tx } from './db.js';

// Columns a human is allowed to edit through the admin UI. Deliberately
// excludes atlas_id (PK), id_name/short_name (identity/matching keys the
// scraper computes), and the edit-tracking columns themselves.
export const EDITABLE_ATLAS_COLUMNS = [
  'title', 'original_name', 'category', 'engine', 'status', 'version',
  'developer', 'creator', 'overview', 'censored', 'language', 'translations',
  'genre', 'tags', 'voice', 'os', 'release_date', 'length',
  'banner', 'banner_wide', 'cover', 'logo', 'wallpaper', 'previews',
];

const EDITABLE_SET = new Set(EDITABLE_ATLAS_COLUMNS);

function nowEpoch() { return Math.floor(Date.now() / 1000); }

export async function getAtlasRow(atlasId) {
  return q1('SELECT * FROM atlas WHERE atlas_id = ? LIMIT 1', [atlasId]);
}

export async function logAudit(conn, { atlasId, field, oldValue, newValue, user }) {
  const runner = conn || { execute: (sql, p) => write(sql, p) };
  const sql = `INSERT INTO atlas_audit
      (atlas_id, field, old_value, new_value, admin_user, ts)
      VALUES (?, ?, ?, ?, ?, ?)`;
  const params = [
    atlasId ?? null, field,
    oldValue === undefined ? null : oldValue,
    newValue === undefined ? null : newValue,
    user, nowEpoch(),
  ];
  if (conn) await conn.execute(sql, params);
  else await write(sql, params);
}

/**
 * Apply a set of field edits to one atlas row. `changes` is a plain object of
 * column -> new value. Only whitelisted columns are written. Returns the list
 * of fields that actually changed. No-op fields (same value) are skipped and
 * NOT logged, so the audit trail only records real changes.
 */
export async function editAtlasRow(atlasId, changes, user) {
  const current = await getAtlasRow(atlasId);
  if (!current) throw Object.assign(new Error('Atlas row not found.'), { status: 404 });

  const applied = [];
  const setParts = [];
  const setParams = [];
  const auditRows = [];

  for (const [col, rawNew] of Object.entries(changes || {})) {
    if (!EDITABLE_SET.has(col)) continue;
    const newVal = rawNew === '' ? null : rawNew;
    const oldVal = current[col] ?? null;
    // Compare as strings so 5 vs "5" from a form doesn't create noise.
    const same = (oldVal === null && newVal === null) ||
      (oldVal !== null && newVal !== null && String(oldVal) === String(newVal));
    if (same) continue;
    setParts.push(`${col} = ?`);
    setParams.push(newVal);
    auditRows.push({ field: `atlas.${col}`, oldVal, newVal });
    applied.push(col);
  }

  if (!applied.length) return { changed: [] };

  const ts = nowEpoch();
  await tx(async (conn) => {
    await conn.execute(
      `UPDATE atlas SET ${setParts.join(', ')},
         edited = 1, edited_at = ?, edited_by = ?
       WHERE atlas_id = ?`,
      [...setParams, ts, user, atlasId],
    );
    for (const a of auditRows) {
      await logAudit(conn, {
        atlasId, field: a.field,
        oldValue: a.oldVal === null ? null : String(a.oldVal),
        newValue: a.newVal === null ? null : String(a.newVal),
        user,
      });
    }
  });

  return { changed: applied };
}

export async function getAuditForAtlas(atlasId, limit = 200) {
  const lim = Math.min(Math.max(parseInt(limit, 10) || 200, 1), 1000);
  return q(
    `SELECT audit_id, atlas_id, field, old_value, new_value, admin_user, ts
     FROM atlas_audit WHERE atlas_id = ? ORDER BY ts DESC, audit_id DESC LIMIT ${lim}`,
    [atlasId],
  );
}

export async function getRecentAudit(limit = 200) {
  const lim = Math.min(Math.max(parseInt(limit, 10) || 200, 1), 1000);
  return q(
    `SELECT audit_id, atlas_id, field, old_value, new_value, admin_user, ts
     FROM atlas_audit ORDER BY ts DESC, audit_id DESC LIMIT ${lim}`,
  );
}
