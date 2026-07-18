// ---------------------------------------------------------------------------
// Manual external links (Steam / GOG / Itch.io / custom) attached to an atlas
// game by a human. These live in atlas_manual_links, a table the SCRAPER NEVER
// WRITES TO, so they are never overwritten by a re-scrape (requirement 4a).
//
// Each link carries an optional external id and an optional url; the app
// requires at least one of the two. Known store kinds get a canonical url
// built from the id when the admin only supplies an id.
// ---------------------------------------------------------------------------
import { q, write, tx } from './db.js';
import { logAudit } from './atlas.js';

export const MANUAL_LINK_KINDS = ['steam', 'gog', 'itch', 'custom'];
const KIND_SET = new Set(MANUAL_LINK_KINDS);
const now = () => Math.floor(Date.now() / 1000);

// Build a canonical url from an id for the known stores, so an admin can paste
// just an appid. Returns null when we can't (custom, or no id).
function canonicalUrl(kind, extId) {
  if (!extId) return null;
  const id = String(extId).trim();
  if (!id) return null;
  switch (kind) {
    case 'steam': return `https://store.steampowered.com/app/${encodeURIComponent(id)}/`;
    case 'gog':   return `https://www.gog.com/game/${encodeURIComponent(id)}`;
    case 'itch':  return null; // itch has no stable id->url pattern; needs the url
    default:      return null;
  }
}

function labelFor(kind, label) {
  if (kind === 'custom') return (label || '').trim() || 'Link';
  return null; // known stores are labelled by the UI
}

/** All manual links for an atlas row, newest first. */
export async function getManualLinks(atlasId) {
  return q(
    `SELECT link_id, atlas_id, kind, label, ext_id, url, added_by, added_at
       FROM atlas_manual_links WHERE atlas_id = ?
      ORDER BY added_at DESC, link_id DESC`,
    [Number(atlasId)],
  );
}

/** Add one manual link. Requires at least an ext_id or a url. */
export async function addManualLink(atlasId, { kind, label, extId, url }, user) {
  atlasId = Number(atlasId);
  const k = String(kind || '').toLowerCase().trim();
  if (!KIND_SET.has(k)) {
    throw Object.assign(new Error(`Unknown link kind "${kind}".`), { status: 400 });
  }
  const cleanId = (extId ?? '').toString().trim() || null;
  let cleanUrl = (url ?? '').toString().trim() || null;
  if (!cleanId && !cleanUrl) {
    throw Object.assign(new Error('Provide an ID, a URL, or both.'), { status: 400 });
  }
  if (cleanUrl && !/^https?:\/\//i.test(cleanUrl)) {
    throw Object.assign(new Error('URL must start with http:// or https://'), { status: 400 });
  }
  if (!cleanUrl) cleanUrl = canonicalUrl(k, cleanId);

  const exists = await q('SELECT 1 FROM atlas WHERE atlas_id = ? LIMIT 1', [atlasId]);
  if (!exists.length) {
    throw Object.assign(new Error(`No atlas row #${atlasId}.`), { status: 404 });
  }

  const ts = now();
  const lbl = labelFor(k, label);
  let insertId;
  await tx(async (conn) => {
    const [res] = await conn.execute(
      `INSERT INTO atlas_manual_links (atlas_id, kind, label, ext_id, url, added_by, added_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [atlasId, k, lbl, cleanId, cleanUrl, user, ts],
    );
    insertId = res.insertId;
    await logAudit(conn, {
      atlasId, field: 'manual_link.add', user,
      oldValue: null,
      newValue: `${k}${lbl ? ` (${lbl})` : ''}: ${cleanId || ''}${cleanId && cleanUrl ? ' · ' : ''}${cleanUrl || ''}`.trim(),
    });
  });
  return { link_id: insertId, atlas_id: atlasId, kind: k, label: lbl, ext_id: cleanId, url: cleanUrl, added_by: user, added_at: ts };
}

/** Remove one manual link (scoped to its atlas row for safety). */
export async function removeManualLink(atlasId, linkId, user) {
  atlasId = Number(atlasId);
  linkId = Number(linkId);
  const rows = await q(
    'SELECT kind, label, ext_id, url FROM atlas_manual_links WHERE link_id = ? AND atlas_id = ? LIMIT 1',
    [linkId, atlasId]);
  if (!rows.length) {
    throw Object.assign(new Error('Link not found.'), { status: 404 });
  }
  const l = rows[0];
  await tx(async (conn) => {
    await conn.execute('DELETE FROM atlas_manual_links WHERE link_id = ? AND atlas_id = ?', [linkId, atlasId]);
    await logAudit(conn, {
      atlasId, field: 'manual_link.remove', user,
      oldValue: `${l.kind}${l.label ? ` (${l.label})` : ''}: ${l.ext_id || ''}${l.ext_id && l.url ? ' · ' : ''}${l.url || ''}`.trim(),
      newValue: null,
    });
  });
  return { removed: linkId };
}
