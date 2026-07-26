// ---------------------------------------------------------------------------
// Per-admin activity stats (issue #271).
//
// No new tracking table: every human action in the portal already writes a row
// to atlas_audit with the acting `admin_user`, so this is a read model over data
// that is already there. The useful consequence is that history is retroactive
// -- the page shows what everyone has done since the audit log started, not just
// since this feature shipped.
//
// The `field` column doubles as the action verb. lib/changelog.js already maps a
// verb to a coarse group; the categories here are finer, because "what did this
// admin do" wants edits separated from additions and deletions, which
// changelog's `edit`/`merge`/`queue` grouping lumps together.
// ---------------------------------------------------------------------------
import { q, q1 } from './db.js';

// Verb -> category. Order matters: the first matching prefix wins, so the
// specific 'atlas.create' / 'atlas.delete' are tested before the generic
// 'atlas.' field-edit prefix.
const CATEGORY_RULES = [
  ['addition', ['atlas.create', 'lc.new', 'user.add', 'invite.create']],
  ['deletion', ['atlas.delete', 'merge.delete']],
  ['merge',    ['merge.relink', 'merge.']],
  ['queue',    ['lc.link', 'lc.dismiss', 'lc.defer', 'queue.']],
  ['link',     ['manual_link.']],
  ['refresh',  ['f95_refresh.', 'refresh.']],
  ['user',     ['user.', 'invite.']],
  ['auth',     ['auth.']],
  ['edit',     ['atlas.']],
];

export const CATEGORIES = [
  'edit', 'addition', 'deletion', 'merge', 'queue', 'link', 'refresh',
  'user', 'auth', 'other',
];

export function categoryFor(field) {
  const f = String(field || '');
  for (const [category, prefixes] of CATEGORY_RULES) {
    for (const prefix of prefixes) {
      if (f === prefix || f.startsWith(prefix)) return category;
    }
  }
  return 'other';
}

// Build the SQL CASE that does the same mapping server-side, so grouping happens
// in the database rather than by pulling the whole audit log into node.
function categoryCaseSql() {
  const whens = [];
  for (const [category, prefixes] of CATEGORY_RULES) {
    for (const prefix of prefixes) {
      // '=' for exact verbs, LIKE for the prefix families.
      whens.push(prefix.endsWith('.')
        ? `WHEN field LIKE '${prefix}%' THEN '${category}'`
        : `WHEN field = '${prefix}' THEN '${category}'`);
    }
  }
  return `CASE ${whens.join(' ')} ELSE 'other' END`;
}

function windowClause({ since, until, user }) {
  const where = [];
  const params = [];
  if (since) { where.push('ts >= ?'); params.push(Number(since)); }
  if (until) { where.push('ts <= ?'); params.push(Number(until)); }
  if (user)  { where.push('admin_user = ?'); params.push(String(user)); }
  return { sql: where.length ? `WHERE ${where.join(' AND ')}` : '', params };
}

/**
 * Per-admin totals, one row per admin with a count per category.
 *
 * Auth events are counted but kept out of the headline `total`: logging in
 * fifty times isn't fifty pieces of work, and including it would rank whoever
 * has the shortest session timeout at the top.
 */
export async function getAdminActivity({ since = null, until = null } = {}) {
  const { sql: whereSql, params } = windowClause({ since, until });
  const rows = await q(
    `SELECT admin_user,
            ${categoryCaseSql()} AS category,
            COUNT(*) AS n,
            MIN(ts) AS first_ts,
            MAX(ts) AS last_ts
       FROM atlas_audit
       ${whereSql}
      GROUP BY admin_user, category`,
    params,
  );

  const byUser = new Map();
  for (const r of rows) {
    const key = r.admin_user || '(unknown)';
    if (!byUser.has(key)) {
      byUser.set(key, {
        admin_user: key,
        counts: Object.fromEntries(CATEGORIES.map((c) => [c, 0])),
        total: 0,
        total_with_auth: 0,
        first_ts: r.first_ts,
        last_ts: r.last_ts,
      });
    }
    const entry = byUser.get(key);
    const n = Number(r.n);
    entry.counts[r.category] = (entry.counts[r.category] || 0) + n;
    entry.total_with_auth += n;
    if (r.category !== 'auth') entry.total += n;
    entry.first_ts = Math.min(Number(entry.first_ts), Number(r.first_ts));
    entry.last_ts = Math.max(Number(entry.last_ts), Number(r.last_ts));
  }

  const admins = [...byUser.values()].sort((a, b) => b.total - a.total
    || String(a.admin_user).localeCompare(String(b.admin_user)));

  const totals = Object.fromEntries(CATEGORIES.map((c) => [c, 0]));
  let grand = 0;
  for (const a of admins) {
    for (const c of CATEGORIES) totals[c] += a.counts[c] || 0;
    grand += a.total;
  }

  return { admins, totals, grand_total: grand, categories: CATEGORIES };
}

/** Day-by-day counts for one admin (or everyone), for a small activity chart. */
export async function getActivityTimeline({ since = null, until = null, user = null, days = 30 } = {}) {
  const span = Math.min(Math.max(parseInt(days, 10) || 30, 1), 365);
  const from = since || (Math.floor(Date.now() / 1000) - span * 86400);
  const { sql: whereSql, params } = windowClause({ since: from, until, user });
  return q(
    `SELECT DATE(FROM_UNIXTIME(ts)) AS day,
            ${categoryCaseSql()} AS category,
            COUNT(*) AS n
       FROM atlas_audit
       ${whereSql}
      GROUP BY day, category
      ORDER BY day ASC`,
    params,
  );
}

/** Most recent actions by one admin, for the drill-down panel. */
export async function getAdminRecent(user, limit = 50) {
  const lim = Math.min(Math.max(parseInt(limit, 10) || 50, 1), 500);
  const rows = await q(
    `SELECT a.audit_id, a.atlas_id, a.field, a.old_value, a.new_value, a.ts,
            t.title
       FROM atlas_audit a
       LEFT JOIN atlas t ON t.atlas_id = a.atlas_id
      WHERE a.admin_user = ?
      ORDER BY a.ts DESC, a.audit_id DESC
      LIMIT ${lim}`,
    [String(user)],
  );
  return rows.map((r) => ({ ...r, category: categoryFor(r.field) }));
}

/** The set of admins that appear in the audit log, for filter dropdowns. */
export async function getAuditUsers() {
  const rows = await q(
    'SELECT DISTINCT admin_user FROM atlas_audit ORDER BY admin_user');
  return rows.map((r) => r.admin_user);
}

/** Overall window bounds, so the UI can show "since <date>". */
export async function getAuditBounds() {
  const row = await q1('SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts, COUNT(*) AS n FROM atlas_audit');
  return row || { first_ts: null, last_ts: null, n: 0 };
}
