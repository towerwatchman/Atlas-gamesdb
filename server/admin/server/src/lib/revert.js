// ---------------------------------------------------------------------------
// Undo an admin action (edits, merges, links, deletions).
//
// Every reversible action carries a `snapshot` written at the moment of the
// change, and the audit rows one logical operation produces share a `batch_id`.
// Reverting works on the batch, newest row first, inside a single transaction:
// a merge emits several relinks plus a delete, and undoing them piecemeal (or
// in the wrong order) would leave source rows pointing at an atlas row that
// doesn't exist yet.
//
// Two things this deliberately will NOT do:
//
//   * Revert an action recorded before migration 007. Those rows have no
//     snapshot, so for anything lossy the old state simply isn't recoverable.
//     They report `revertible: false` with a reason instead of failing halfway.
//   * Revert blindly over the top of later work. Before undoing a field edit it
//     checks the column still holds the value the edit set. If somebody has
//     changed it since, the revert is refused rather than silently discarding
//     their change — reverting is an undo, not a rollback of everything after.
//
// A revert is itself audited, with `revert_of` pointing at the row it undid, so
// it shows up as ordinary history rather than an unexplained edit.
// ---------------------------------------------------------------------------
import { q, q1, tx, touchAtlas } from './db.js';
import { logAudit, newBatchId, EDITABLE_ATLAS_COLUMNS } from './atlas.js';

const EDITABLE = new Set(EDITABLE_ATLAS_COLUMNS);
const SOURCE_TABLES = new Set(['f95_zone', 'lewdcorner', 'dlsite', 'sxs']);

function parseSnapshot(row) {
  if (!row || row.snapshot == null) return null;
  if (typeof row.snapshot !== 'string') return row.snapshot;
  try { return JSON.parse(row.snapshot); } catch { return null; }
}

/** Which broad kind of undo a verb needs. */
export function actionKind(field) {
  const f = String(field || '');
  if (f === 'atlas.create') return 'create';
  if (f === 'atlas.delete' || f === 'merge.delete') return 'row-delete';
  if (f === 'merge.relink') return 'relink';
  if (/^(f95_zone|lewdcorner|dlsite|sxs)\.(link|float)$/.test(f)) return 'relink';
  if (f === 'manual_link.add') return 'link-add';
  if (f === 'manual_link.remove') return 'link-remove';
  if (f === 'manual_link.update') return 'link-update';
  if (f.startsWith('atlas.')) return 'field';
  return 'unsupported';
}

/**
 * Can this audit row be undone, and if not, why not?
 * Pure inspection — no writes, safe to call for every row in a list.
 */
export function describeRevertability(row) {
  if (!row) return { revertible: false, reason: 'No such audit entry.' };
  if (row.reverted_at) {
    return { revertible: false, reason: `Already reverted by ${row.reverted_by}.` };
  }
  if (row.revert_of) {
    return {
      revertible: false,
      reason: 'This entry is itself a revert. Undo it by redoing the change.',
    };
  }

  const kind = actionKind(row.field);
  const snap = parseSnapshot(row);

  switch (kind) {
    case 'field':
      if (!EDITABLE.has(String(row.field).slice('atlas.'.length))) {
        return { revertible: false, reason: 'That column is not editable.' };
      }
      return { revertible: true, kind };
    case 'create':
      return { revertible: true, kind };
    case 'row-delete':
      if (!snap?.row) {
        return {
          revertible: false,
          reason: 'Recorded before undo support existed, so the deleted row was '
                + 'never captured and cannot be rebuilt.',
        };
      }
      return { revertible: true, kind };
    case 'relink':
      if (!snap?.ids?.length) {
        return {
          revertible: false,
          reason: 'Recorded before undo support existed; which source rows moved '
                + 'was not captured.',
        };
      }
      return { revertible: true, kind };
    case 'link-add':
      if (!snap?.linkId) {
        return { revertible: false, reason: 'The created link was not recorded.' };
      }
      return { revertible: true, kind };
    case 'link-remove':
      if (!snap?.row) {
        return { revertible: false, reason: 'The removed link was not captured.' };
      }
      return { revertible: true, kind };
    case 'link-update':
      if (!snap?.before) {
        return { revertible: false, reason: 'The previous values were not captured.' };
      }
      return { revertible: true, kind };
    default:
      return {
        revertible: false,
        reason: `"${row.field}" has no defined undo.`,
      };
  }
}

async function getAudit(auditId) {
  return q1('SELECT * FROM atlas_audit WHERE audit_id = ? LIMIT 1', [Number(auditId)]);
}

/** Every row in the same logical operation, newest first. */
export async function getBatch(row) {
  if (!row.batch_id) return [row];
  const rows = await q(
    `SELECT * FROM atlas_audit
      WHERE batch_id = ? AND reverted_at IS NULL
      ORDER BY audit_id DESC`,
    [row.batch_id]);

  // Creating a game logs `atlas.create` plus one row per field it set. Undoing
  // the creation means deleting the row -- restoring each field individually is
  // meaningless (and impossible for id_name/short_name, which are derived and
  // not editable). So the create subsumes the rest of its batch.
  const create = rows.find((r) => r.field === 'atlas.create');
  if (create) return [create];
  return rows;
}

/** Rows a batch revert marks done without acting on them individually. */
export async function subsumedBy(row) {
  if (!row.batch_id || row.field !== 'atlas.create') return [];
  const rows = await q(
    `SELECT audit_id FROM atlas_audit
      WHERE batch_id = ? AND audit_id <> ? AND reverted_at IS NULL`,
    [row.batch_id, row.audit_id]);
  return rows.map((r) => r.audit_id);
}

// --- per-kind undo ---------------------------------------------------------

async function undoField(conn, row) {
  const col = String(row.field).slice('atlas.'.length);
  const [cur] = await conn.execute(
    `SELECT \`${col}\` AS v FROM atlas WHERE atlas_id = ? LIMIT 1`, [row.atlas_id]);
  if (!cur.length) {
    throw Object.assign(
      new Error(`Atlas #${row.atlas_id} no longer exists.`), { status: 409 });
  }
  const current = cur[0].v;
  const expected = row.new_value;
  // Compared as text because the audit stores strings.
  const same = (current == null ? '' : String(current)) === (expected == null ? '' : String(expected));
  if (!same) {
    throw Object.assign(new Error(
      `"${col}" has changed since this edit (it now reads `
      + `${current == null ? 'empty' : `"${String(current).slice(0, 60)}"`}). `
      + 'Reverting would discard that. Undo the newer change first.'),
    { status: 409 });
  }
  await conn.execute(
    `UPDATE atlas SET \`${col}\` = ? WHERE atlas_id = ?`,
    [row.old_value === undefined ? null : row.old_value, row.atlas_id]);
  await touchAtlas(conn, row.atlas_id);
  return `restored ${col}`;
}

async function undoCreate(conn, row) {
  const id = row.atlas_id;
  // Refuse if the row has since acquired anything: a source mapping means the
  // scraper matched it, and deleting it would orphan that mapping.
  for (const table of SOURCE_TABLES) {
    const [rows] = await conn.execute(
      `SELECT 1 AS x FROM ${table} WHERE atlas_id = ? LIMIT 1`, [id]).catch(() => [[]]);
    if (rows.length) {
      throw Object.assign(new Error(
        `Atlas #${id} now has a ${table} mapping, so it is no longer a blank `
        + 'hand-created row. Unlink the source before undoing the creation.'),
      { status: 409 });
    }
  }
  await conn.execute('DELETE FROM atlas WHERE atlas_id = ?', [id]);
  return `deleted atlas #${id}`;
}

async function undoRowDelete(conn, row, snap) {
  const data = snap.row;
  const [exists] = await conn.execute(
    'SELECT 1 AS x FROM atlas WHERE atlas_id = ? LIMIT 1', [data.atlas_id]);
  if (exists.length) {
    throw Object.assign(new Error(
      `Atlas #${data.atlas_id} already exists again; nothing to restore.`),
    { status: 409 });
  }
  // Re-inserted WITH its original atlas_id, so every source row, manual link
  // and client-side reference still points at the right game.
  const cols = Object.keys(data);
  await conn.execute(
    `INSERT INTO atlas (${cols.map((c) => `\`${c}\``).join(', ')})
     VALUES (${cols.map(() => '?').join(', ')})`,
    cols.map((c) => data[c]));
  await touchAtlas(conn, data.atlas_id);
  return `restored atlas #${data.atlas_id}`;
}

async function undoRelink(conn, row, snap) {
  const { table, idCol, ids, from, floated, wasFloating } = snap;
  if (!SOURCE_TABLES.has(table)) {
    throw Object.assign(new Error(`Unknown source table ${table}.`), { status: 400 });
  }
  // Putting a source row back needs its old owner to exist. In a merge batch
  // the atlas row is restored first because we walk newest-first and the delete
  // was logged last.
  if (from != null) {
    const [owner] = await conn.execute(
      'SELECT 1 AS x FROM atlas WHERE atlas_id = ? LIMIT 1', [from]);
    if (!owner.length) {
      throw Object.assign(new Error(
        `Cannot move ${table} back to atlas #${from}: that row no longer exists.`),
      { status: 409 });
    }
  }
  for (const id of ids) {
    if (floated || wasFloating || from == null) {
      await conn.execute(
        `UPDATE ${table} SET atlas_id = ?, floating = ? WHERE ${idCol} = ?`,
        [from ?? null, from == null ? 1 : 0, id]);
    } else {
      await conn.execute(
        `UPDATE ${table} SET atlas_id = ?, floating = 0 WHERE ${idCol} = ?`, [from, id]);
    }
  }
  if (from != null) await touchAtlas(conn, from);
  if (snap.to != null) await touchAtlas(conn, snap.to);
  return `moved ${ids.length} ${table} row(s) back`;
}

async function undoLinkAdd(conn, row, snap) {
  await conn.execute('DELETE FROM atlas_manual_links WHERE link_id = ?', [snap.linkId]);
  await touchAtlas(conn, row.atlas_id);
  return `removed link #${snap.linkId}`;
}

async function undoLinkRemove(conn, row, snap) {
  const data = snap.row;
  const cols = Object.keys(data);
  await conn.execute(
    `INSERT INTO atlas_manual_links (${cols.map((c) => `\`${c}\``).join(', ')})
     VALUES (${cols.map(() => '?').join(', ')})`,
    cols.map((c) => data[c]));
  // Re-tie the DLC whose parent pointer the FK nulled when this was deleted.
  for (const childId of snap.orphanedChildren || []) {
    await conn.execute(
      `UPDATE atlas_manual_links SET parent_kind = 'manual', parent_link_id = ?
        WHERE link_id = ? AND parent_link_id IS NULL`,
      [data.link_id, childId]);
  }
  await touchAtlas(conn, row.atlas_id);
  const kids = (snap.orphanedChildren || []).length;
  return `restored link #${data.link_id}${kids ? ` and re-tied ${kids} DLC` : ''}`;
}

async function undoLinkUpdate(conn, row, snap) {
  const b = snap.before;
  const [exists] = await conn.execute(
    'SELECT 1 AS x FROM atlas_manual_links WHERE link_id = ? LIMIT 1', [b.link_id]);
  if (!exists.length) {
    throw Object.assign(new Error(
      `Link #${b.link_id} has since been deleted.`), { status: 409 });
  }
  await conn.execute(
    `UPDATE atlas_manual_links
        SET label = ?, ext_id = ?, url = ?, entry_type = ?,
            parent_kind = ?, parent_link_id = ?, parent_source_id = ?
      WHERE link_id = ?`,
    [b.label, b.ext_id, b.url, b.entry_type,
     b.parent_kind, b.parent_link_id, b.parent_source_id, b.link_id]);
  await touchAtlas(conn, row.atlas_id);
  return `restored link #${b.link_id}`;
}

const HANDLERS = {
  field: undoField,
  create: undoCreate,
  'row-delete': undoRowDelete,
  relink: undoRelink,
  'link-add': undoLinkAdd,
  'link-remove': undoLinkRemove,
  'link-update': undoLinkUpdate,
};

/** Preview: what would reverting this audit entry (or its batch) do? */
export async function previewRevert(auditId) {
  const row = await getAudit(auditId);
  if (!row) throw Object.assign(new Error('No such audit entry.'), { status: 404 });
  const batch = await getBatch(row);
  const entries = batch.map((r) => ({
    audit_id: r.audit_id,
    atlas_id: r.atlas_id,
    field: r.field,
    old_value: r.old_value,
    new_value: r.new_value,
    ts: r.ts,
    admin_user: r.admin_user,
    ...describeRevertability(r),
  }));
  const blockers = entries.filter((e) => !e.revertible);
  return {
    audit_id: row.audit_id,
    batch_id: row.batch_id,
    entries,
    revertible: blockers.length === 0,
    blockers,
  };
}

/**
 * Revert one audit entry, or the whole batch it belongs to.
 *
 * All-or-nothing: if any row in the batch can't be undone the whole thing is
 * refused, because a half-undone merge is worse than one that stands.
 */
export async function revertAudit(auditId, user) {
  const row = await getAudit(auditId);
  if (!row) throw Object.assign(new Error('No such audit entry.'), { status: 404 });

  const batch = await getBatch(row);
  for (const entry of batch) {
    const check = describeRevertability(entry);
    if (!check.revertible) {
      throw Object.assign(
        new Error(`Cannot revert: ${check.reason}`), { status: 409 });
    }
  }

  const revertBatch = newBatchId();
  const results = [];

  await tx(async (conn) => {
    // Newest first. Within a merge the delete was logged last, so the atlas row
    // comes back before the relinks that need it to exist.
    for (const entry of batch) {
      const snap = parseSnapshot(entry);
      const kind = actionKind(entry.field);
      const handler = HANDLERS[kind];
      if (!handler) {
        throw Object.assign(
          new Error(`No undo defined for "${entry.field}".`), { status: 400 });
      }
      const what = await handler(conn, entry, snap);
      results.push({ audit_id: entry.audit_id, field: entry.field, did: what });

      const stamp = Math.floor(Date.now() / 1000);
      await conn.execute(
        'UPDATE atlas_audit SET reverted_at = ?, reverted_by = ? WHERE audit_id = ?',
        [stamp, user, entry.audit_id]);
      // The per-field rows of a creation go with it, so the history doesn't
      // keep offering buttons for changes that no longer exist.
      for (const id of await subsumedBy(entry)) {
        await conn.execute(
          'UPDATE atlas_audit SET reverted_at = ?, reverted_by = ? WHERE audit_id = ?',
          [stamp, user, id]);
      }

      await logAudit(conn, {
        atlasId: entry.atlas_id,
        field: `revert.${entry.field}`,
        user,
        batchId: revertBatch,
        revertOf: entry.audit_id,
        oldValue: entry.new_value,
        newValue: entry.old_value,
      });
    }
  });

  return {
    reverted: results.length,
    batch_id: row.batch_id,
    revert_batch_id: revertBatch,
    results,
  };
}
