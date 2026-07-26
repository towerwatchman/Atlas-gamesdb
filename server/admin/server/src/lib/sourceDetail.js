// ---------------------------------------------------------------------------
// Full source rows for one atlas game (issue #286).
//
// The edit modal needs to show the mapped F95 / LewdCorner / DLsite / SXS rows
// side by side with the atlas fields. `merge.getSourceLinks` only returns the id
// and site_url, which isn't enough to display, so this returns the whole row per
// mapped source along with a little display metadata.
//
// Worth knowing: every source table declares `atlas_id INT NOT NULL UNIQUE`, so
// there is at most ONE row per source per game. "More than one mapping" means
// more than one SOURCE is mapped (F95 and LewdCorner, say), not two F95 threads
// on one game. The UI's switcher therefore switches between sources.
// ---------------------------------------------------------------------------
import { q } from './db.js';
import { SOURCE_TABLES } from './merge.js';

// Columns worth surfacing first, per source. Anything else in the row still
// comes back, just after these.
const PRIMARY_FIELDS = {
  // Verified against the live schema. Anything not present is skipped by the
  // `f in row` filter below, so a schema drift degrades rather than breaks.
  f95_zone: ['f95_id', 'site_url', 'rating', 'views', 'likes', 'replies',
             'thread_updated', 'thread_publish_date', 'last_thread_comment',
             'last_record_update', 'floating', 'tags', 'translations',
             'downloads', 'patches', 'extras', 'screens', 'banner_url'],
  lewdcorner: ['lc_id', 'site_url', 'tier', 'prefixes', 'rating', 'views',
               'likes', 'thread_updated', 'register_date', 'last_record_update',
               'floating', 'tags', 'downloads', 'screens', 'banner_url'],
  dlsite: ['dlsite_id', 'site_url', 'last_record_update'],
  sxs: ['sxs_id', 'site_url', 'last_record_update'],
};

const LABELS = {
  f95_zone: 'F95zone',
  lewdcorner: 'LewdCorner',
  dlsite: 'DLsite',
  sxs: 'SXS',
};

/**
 * Every mapped source row for an atlas game, in a stable display order.
 * Returns [] when nothing is mapped (a hand-created game, for instance).
 */
export async function getSourceDetail(atlasId) {
  const id = Number(atlasId);
  const out = [];
  for (const { table, idCol } of SOURCE_TABLES) {
    let rows;
    try {
      rows = await q(`SELECT * FROM ${table} WHERE atlas_id = ?`, [id]);
    } catch {
      // Partial dev database: a missing source table shouldn't blank the modal.
      continue;
    }
    for (const row of rows) {
      const preferred = PRIMARY_FIELDS[table] || [idCol, 'site_url'];
      const ordered = [
        ...preferred.filter((f) => f in row),
        ...Object.keys(row).filter((f) => !preferred.includes(f) && f !== 'atlas_id'),
      ];
      out.push({
        source: table,
        source_label: LABELS[table] || table,
        id_col: idCol,
        id: row[idCol] == null ? null : String(row[idCol]),
        site_url: row.site_url || null,
        fields: ordered.map((f) => ({ field: f, value: row[f] })),
        row,
      });
    }
  }
  return out;
}
