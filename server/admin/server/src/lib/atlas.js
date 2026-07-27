// ---------------------------------------------------------------------------
// Atlas write + audit helpers. Every human change writes a per-field row to
// atlas_audit and stamps atlas.edited / edited_at / edited_by, so the
// "this row was touched by a human" flag (requirement 1) is always in sync
// with the log.
// ---------------------------------------------------------------------------
import { randomUUID } from 'crypto';

import { q, q1, write, tx } from './db.js';
import { computeIdentity } from './identity.js';

// Columns a human is allowed to edit through the admin UI. Deliberately
// excludes atlas_id (PK), id_name/short_name (identity/matching keys the
// scraper computes), and the edit-tracking columns themselves.
export const EDITABLE_ATLAS_COLUMNS = [
  'title', 'original_name', 'category', 'engine', 'status', 'version',
  'developer', 'creator', 'overview', 'censored', 'language', 'translations',
  'genre', 'tags', 'voice', 'os', 'release_date', 'length',
  'banner', 'banner_wide', 'cover', 'logo', 'wallpaper', 'previews',
  // Export bookkeeping, editable on request but handled specially below and
  // never lockable -- see LOCKABLE_ATLAS_COLUMNS.
  'last_record_update',
];

// Stored as epoch seconds. The UI renders a date picker for these instead of a
// number box; typing 1768953600 by hand was the only way to set a date before.
export const DATE_ATLAS_COLUMNS = ['release_date', 'last_record_update'];

// Fields a human edit may claim, so the scraper stops overwriting them.
//
// last_record_update is excluded deliberately. It is what the delta packager
// uses to decide which rows changed; locking it would freeze the row out of
// every future package, so a locked game's edits would never reach clients.
// The scraper must stay free to bump it.
export const LOCKABLE_ATLAS_COLUMNS = EDITABLE_ATLAS_COLUMNS.filter(
  (c) => c !== 'last_record_update');
const LOCKABLE_SET = new Set(LOCKABLE_ATLAS_COLUMNS);

/** Parse the locked_fields JSON array off an atlas row. */
export function parseLockedFields(raw) {
  if (!raw) return [];
  let list = raw;
  if (typeof raw === 'string') {
    try { list = JSON.parse(raw); } catch { return []; }
  }
  if (!Array.isArray(list)) return [];
  return [...new Set(list.map(String).filter((f) => LOCKABLE_SET.has(f)))].sort();
}

const EDITABLE_SET = new Set(EDITABLE_ATLAS_COLUMNS);

function nowEpoch() { return Math.floor(Date.now() / 1000); }

export async function getAtlasRow(atlasId) {
  return q1('SELECT * FROM atlas WHERE atlas_id = ? LIMIT 1', [atlasId]);
}

export async function logAudit(connOrPayload, maybePayload) {
  // Accepts either logAudit(conn, payload) -- inside a transaction -- or
  // logAudit(payload) on its own.
  //
  // Both forms are supported because four call sites in routes/auth.js used the
  // short one. With the old (conn, payload) signature the payload landed in
  // `conn`, the second parameter was undefined, and destructuring it threw a
  // TypeError straight into a `catch {}` that swallowed it. The upshot was that
  // auth.login / auth.logout / user.add / user.remove were NEVER recorded, so
  // the Changelog page's "auth" and "user" filters could never match anything.
  const insideTx = maybePayload !== undefined;
  const conn = insideTx ? connOrPayload : null;
  const {
    atlasId, field, oldValue, newValue, user,
    // `snapshot` carries whatever an undo needs (see sql/007). It is
    // captured here because this is the last moment the old state exists.
    // `batchId` groups the rows one logical operation produces so they can
    // be reverted together and in the right order.
    snapshot = null, batchId = null, revertOf = null,
  } = (insideTx ? maybePayload : connOrPayload) || {};
  if (!field) throw new Error('logAudit requires a field.');
  const sql = `INSERT INTO atlas_audit
      (atlas_id, field, old_value, new_value, admin_user, ts,
       snapshot, batch_id, revert_of)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`;
  const params = [
    atlasId ?? null, field,
    oldValue === undefined ? null : oldValue,
    newValue === undefined ? null : newValue,
    user, nowEpoch(),
    snapshot == null ? null
      : (typeof snapshot === 'string' ? snapshot : JSON.stringify(snapshot)),
    batchId ?? null,
    revertOf ?? null,
  ];
  if (conn) {
    const [res] = await conn.execute(sql, params);
    return res.insertId;
  }
  const res = await write(sql, params);
  return res?.insertId ?? null;
}

/** A batch id groups the audit rows one logical operation writes. */
export function newBatchId() {
  return randomUUID();
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
    // Written by the dedicated clause below, not the generic SET list, so it
    // can't appear twice in one UPDATE.
    if (col === 'last_record_update') {
      const oldStamp = current[col] ?? null;
      const newStamp = rawNew === '' || rawNew == null ? null : Number(rawNew);
      if (String(oldStamp ?? '') !== String(newStamp ?? '')) {
        auditRows.push({ field: `atlas.${col}`, oldVal: oldStamp, newVal: newStamp });
        applied.push(col);
      }
      continue;
    }
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

  // Editing a field marks it as human-owned so the next crawl leaves it alone
  // (scraper/utils/db.py::updateAtlasById drops locked columns). Without this
  // the edit silently reverts the next time the thread is scraped.
  const alreadyLocked = parseLockedFields(current.locked_fields);
  const nowLocked = [...new Set([
    ...alreadyLocked,
    ...applied.filter((c) => LOCKABLE_SET.has(c)),
  ])].sort();
  const locksChanged = nowLocked.join(',') !== alreadyLocked.join(',');

  // Normally every write bumps last_record_update so the delta packager picks
  // the row up. If the admin set it explicitly, that is the whole point of the
  // edit -- use their value rather than stamping over it.
  const explicitStamp = applied.includes('last_record_update');
  const stamp = explicitStamp
    ? (changes.last_record_update === '' || changes.last_record_update == null
      ? null : Number(changes.last_record_update))
    : ts;

  await tx(async (conn) => {
    // Built as a list rather than interpolating `setParts` directly: when the
    // only change is last_record_update, setParts is empty and a bare
    // "SET , edited = 1" is a syntax error.
    const sets = [
      ...setParts,
      'edited = 1', 'edited_at = ?', 'edited_by = ?',
      'last_record_update = ?', 'locked_fields = ?',
    ];
    await conn.execute(
      `UPDATE atlas SET ${sets.join(', ')} WHERE atlas_id = ?`,
      [...setParams, ts, user,
       explicitStamp ? stamp : ts,
       nowLocked.length ? JSON.stringify(nowLocked) : null,
       atlasId],
    );
    if (locksChanged) {
      await logAudit(conn, {
        atlasId, field: 'atlas.lock', user,
        oldValue: alreadyLocked.join(', ') || null,
        newValue: nowLocked.join(', ') || null,
      });
    }
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

// Fields a human may set when CREATING a game. Same whitelist as editing, plus
// nothing else: atlas_id comes from AUTO_INCREMENT and the identity keys are
// derived, never typed.
export const CREATE_REQUIRED = ['title'];

/**
 * Create a new atlas row by hand (requirement 1). The atlas_id is assigned by
 * AUTO_INCREMENT and returned.
 *
 * `id_name` and `short_name` are DERIVED, not accepted from the client, and are
 * computed with the same rule the scraper uses (see lib/identity.js). If they
 * were computed any other way the next crawl would fail to recognise this game
 * and would insert a duplicate atlas row alongside it.
 *
 * A pre-existing row with the same id_name is refused rather than silently
 * duplicated -- that collision is exactly the thing the key exists to prevent,
 * and the caller gets the offending atlas_id so the UI can link to it.
 */
export async function createAtlasRow(fields, user) {
  const title = String(fields?.title ?? '').trim();
  if (!title) {
    throw Object.assign(new Error('Title is required.'), { status: 400 });
  }
  const creator = String(fields?.creator ?? '').trim();
  const { id_name, short_name } = computeIdentity(title, creator);

  const clash = await q1(
    'SELECT atlas_id, title FROM atlas WHERE id_name = ? LIMIT 1', [id_name]);
  if (clash) {
    throw Object.assign(
      new Error(`A game with the same identity key already exists: #${clash.atlas_id} "${clash.title}" (${id_name}). ` +
                'Edit that row instead, or change the title/creator.'),
      { status: 409, atlasId: clash.atlas_id, idName: id_name },
    );
  }

  const cols = ['title', 'id_name', 'short_name'];
  const vals = [title, id_name, short_name];
  for (const col of EDITABLE_ATLAS_COLUMNS) {
    if (col === 'title') continue;
    if (!(col in (fields || {}))) continue;
    const raw = fields[col];
    const value = raw === '' || raw === undefined ? null : raw;
    cols.push(col);
    vals.push(value);
  }

  const ts = nowEpoch();
  // One batch so the create and its per-field rows undo together.
  const batchId = newBatchId();
  cols.push('edited', 'edited_at', 'edited_by', 'last_record_update');
  vals.push(1, ts, user, ts);

  let atlasId;
  await tx(async (conn) => {
    const [res] = await conn.execute(
      `INSERT INTO atlas (${cols.join(', ')}) VALUES (${cols.map(() => '?').join(', ')})`,
      vals,
    );
    atlasId = res.insertId;
    // One summary row so the Changelog and the per-admin activity page both show
    // the creation, then a row per supplied field so the detail is auditable.
    await logAudit(conn, {
      atlasId, field: 'atlas.create', user, batchId,
      oldValue: null, newValue: `${title}${creator ? ` (${creator})` : ''} [${id_name}]`,
      snapshot: { table: 'atlas', createdId: atlasId },
    });
    for (let i = 0; i < cols.length; i += 1) {
      const col = cols[i];
      if (['edited', 'edited_at', 'edited_by', 'last_record_update'].includes(col)) continue;
      if (vals[i] === null) continue;
      await logAudit(conn, {
        atlasId, field: `atlas.${col}`, user, batchId,
        oldValue: null, newValue: String(vals[i]),
      });
    }
  });

  return { atlas_id: atlasId, id_name, short_name, title };
}

/**
 * Lock or unlock individual fields on an atlas row.
 *
 * A locked field is one the scraper must leave alone. Editing a field locks it
 * automatically; unlocking hands it back so the next crawl can update it again.
 */
export async function setFieldLock(atlasId, field, locked, user) {
  atlasId = Number(atlasId);
  if (!LOCKABLE_SET.has(field)) {
    const why = field === 'last_record_update'
      ? 'last_record_update is export bookkeeping — locking it would keep the '
        + 'row out of every future package.'
      : `"${field}" is not an editable column.`;
    throw Object.assign(new Error(why), { status: 400 });
  }
  const row = await getAtlasRow(atlasId);
  if (!row) throw Object.assign(new Error(`No atlas row #${atlasId}.`), { status: 404 });

  const before = parseLockedFields(row.locked_fields);
  const after = locked
    ? [...new Set([...before, field])].sort()
    : before.filter((f) => f !== field);
  if (before.join(',') === after.join(',')) return { locked_fields: before, changed: false };

  await tx(async (conn) => {
    await conn.execute(
      'UPDATE atlas SET locked_fields = ? WHERE atlas_id = ?',
      [after.length ? JSON.stringify(after) : null, atlasId]);
    await logAudit(conn, {
      atlasId, field: locked ? 'atlas.lock' : 'atlas.unlock', user,
      oldValue: before.join(', ') || null,
      newValue: after.join(', ') || null,
    });
  });
  return { locked_fields: after, changed: true };
}

export async function getAuditForAtlas(atlasId, limit = 200) {
  const lim = Math.min(Math.max(parseInt(limit, 10) || 200, 1), 1000);
  const rows = await q(
    `SELECT audit_id, atlas_id, field, old_value, new_value, admin_user, ts,
            snapshot, batch_id, revert_of, reverted_at, reverted_by
     FROM atlas_audit WHERE atlas_id = ? ORDER BY ts DESC, audit_id DESC LIMIT ${lim}`,
    [atlasId],
  );
  // Annotate each row with whether it can be undone, so the history table can
  // show a working button (or say why not) without a request per row. Imported
  // lazily to avoid a cycle: revert.js needs logAudit from here.
  const { describeRevertability } = await import('./revert.js');
  return rows.map((r) => {
    const { snapshot, ...rest } = r;   // the blob is internal; don't ship it
    return { ...rest, ...describeRevertability(r) };
  });
}

export async function getRecentAudit(limit = 200) {
  const lim = Math.min(Math.max(parseInt(limit, 10) || 200, 1), 1000);
  return q(
    `SELECT audit_id, atlas_id, field, old_value, new_value, admin_user, ts
     FROM atlas_audit ORDER BY ts DESC, audit_id DESC LIMIT ${lim}`,
  );
}
