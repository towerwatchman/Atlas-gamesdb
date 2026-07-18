// ---------------------------------------------------------------------------
// Changelog — a read model over atlas_audit.
//
// Every human action in the admin portal already writes a row to atlas_audit
// (field edits, merges, relinks, queue resolves, manual links, and now auth /
// user-management events). This module reads that single timeline back with
// filtering + pagination and joins the atlas title so entries are legible
// without a second lookup.
//
// The `field` column doubles as the action verb. We derive a coarse
// `action_group` from its prefix so the UI can offer a small, stable filter
// dropdown instead of dozens of raw verbs.
// ---------------------------------------------------------------------------
import { q, q1 } from './db.js';

// Map a raw `field` verb to a coarse group for filtering + display colour.
export function actionGroup(field) {
  const f = String(field || '');
  if (f.startsWith('atlas.')) return 'edit';
  if (f.startsWith('merge.')) return 'merge';
  if (f.startsWith('lc.') || f.startsWith('queue.')) return 'queue';
  if (f.startsWith('manual_link.')) return 'link';
  if (f.startsWith('auth.')) return 'auth';
  if (f.startsWith('user.')) return 'user';
  return 'other';
}

const GROUP_PREFIXES = {
  edit: ['atlas.'],
  merge: ['merge.'],
  queue: ['lc.', 'queue.'],
  link: ['manual_link.'],
  auth: ['auth.'],
  user: ['user.'],
};

// Build the shared WHERE clause + params from filter options.
function buildWhere({ user, group, since, until, atlasId }) {
  const where = [];
  const params = [];
  if (user) { where.push('a.admin_user = ?'); params.push(user); }
  if (atlasId) { where.push('a.atlas_id = ?'); params.push(Number(atlasId)); }
  if (since) { where.push('a.ts >= ?'); params.push(Number(since)); }
  if (until) { where.push('a.ts <= ?'); params.push(Number(until)); }
  if (group && GROUP_PREFIXES[group]) {
    const ors = GROUP_PREFIXES[group].map(() => 'a.field LIKE ?');
    where.push(`(${ors.join(' OR ')})`);
    for (const p of GROUP_PREFIXES[group]) params.push(`${p}%`);
  }
  return { clause: where.length ? `WHERE ${where.join(' AND ')}` : '', params };
}

/**
 * Page through the changelog. Returns { entries, total, limit, offset }.
 * Each entry carries a derived action_group and the atlas title (or null for
 * non-game actions like logins).
 */
export async function getChangelog(opts = {}) {
  const limit = Math.min(Math.max(parseInt(opts.limit, 10) || 50, 1), 200);
  const offset = Math.max(parseInt(opts.offset, 10) || 0, 0);
  const { clause, params } = buildWhere(opts);

  const rows = await q(
    `SELECT a.audit_id, a.atlas_id, a.field, a.old_value, a.new_value,
            a.admin_user, a.ts, at.title AS atlas_title
       FROM atlas_audit a
       LEFT JOIN atlas at ON at.atlas_id = a.atlas_id
       ${clause}
      ORDER BY a.ts DESC, a.audit_id DESC
      LIMIT ${limit} OFFSET ${offset}`,
    params,
  );

  const totalRow = await q1(
    `SELECT COUNT(*) AS n FROM atlas_audit a ${clause}`, params);

  return {
    entries: rows.map((r) => ({ ...r, action_group: actionGroup(r.field) })),
    total: totalRow ? totalRow.n : rows.length,
    limit, offset,
  };
}

/** Distinct admin users that appear in the log, for the filter dropdown. */
export async function getChangelogUsers() {
  const rows = await q(
    'SELECT DISTINCT admin_user FROM atlas_audit ORDER BY admin_user');
  return rows.map((r) => r.admin_user);
}
