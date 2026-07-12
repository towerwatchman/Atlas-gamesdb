// ---------------------------------------------------------------------------
// Candidate lookups + atlas loaders, ported from the Python db layer and
// find_duplicates.py. These feed the duplicate finder and the LC queue.
// ---------------------------------------------------------------------------
import { q } from './db.js';

/** All atlas_ids whose id_name matches exactly. */
export async function findAtlasIdsByIdName(idName) {
  if (!idName) return [];
  const rows = await q(
    'SELECT atlas_id FROM atlas WHERE id_name = ? ORDER BY atlas_id', [idName]);
  return rows.map((r) => r.atlas_id);
}

/** Fuzzy candidate atlas_ids for an LC game with no exact id_name match. */
export async function findFuzzyAtlasCandidates(shortName, creator, limit = 25) {
  const sn = (shortName || '').trim();
  const cr = (creator || '').trim().toUpperCase();
  if (!sn && !cr) return [];
  const snPref = sn.slice(0, Math.max(4, Math.min(sn.length, 8)));
  const lim = Math.min(Math.max(parseInt(limit, 10) || 25, 1), 200);
  const rows = await q(
    `SELECT atlas_id
       FROM atlas
      WHERE short_name LIKE ? OR UPPER(creator) LIKE ?
      ORDER BY ((short_name LIKE ?) + (UPPER(creator) LIKE ?)) DESC, atlas_id
      LIMIT ${lim}`,
    [`${snPref}%`, `${cr}%`, `${snPref}%`, `${cr}%`],
  );
  return rows.map((r) => r.atlas_id);
}

/** Full atlas rows for a list of ids. */
export async function getAtlasRowsByIds(ids) {
  const clean = [...new Set(ids.map(Number))].filter((n) => Number.isFinite(n));
  if (!clean.length) return [];
  const placeholders = clean.map(() => '?').join(', ');
  return q(`SELECT * FROM atlas WHERE atlas_id IN (${placeholders})`, clean);
}

/**
 * Every atlas row with its f95_id / lc_id attached (LEFT JOIN), ordered by
 * atlas_id. Used by the atlas duplicate finder. Pulls the columns the matcher
 * and the UI need; not SELECT * to keep the payload lean on a large table.
 */
export async function loadAtlasWithSources() {
  return q(
    `SELECT a.atlas_id, a.title, a.creator, a.developer,
            a.short_name, a.id_name, a.version, a.engine, a.status,
            a.edited, a.edited_at, a.edited_by,
            f.f95_id, l.lc_id
       FROM atlas a
       LEFT JOIN f95_zone   f ON f.atlas_id = a.atlas_id
       LEFT JOIN lewdcorner l ON l.atlas_id = a.atlas_id
      ORDER BY a.atlas_id`,
  );
}

/** Which sources reference a row, as a Set, from a joined row. */
export function rowSources(row) {
  const s = new Set();
  if (row.f95_id != null) s.add('f95');
  if (row.lc_id != null) s.add('lc');
  return s;
}
