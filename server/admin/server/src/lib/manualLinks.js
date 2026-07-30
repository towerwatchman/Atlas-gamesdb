// ---------------------------------------------------------------------------
// Manual external links (Steam / GOG / Itch.io / custom) attached to an atlas
// game by a human. These live in atlas_manual_links, a table the SCRAPER NEVER
// WRITES TO, so they are never overwritten by a re-scrape.
//
// Each link carries an optional external id and an optional url; the app
// requires at least one of the two. Known store kinds get a canonical url built
// from the id when the admin only supplies an id.
//
// Store links additionally carry (issues #285/#278):
//   * a free-text label, so several Steam entries on one game are tellable
//     apart ("Base game", "Season 2 DLC", ...)
//   * entry_type: 'game' or 'dlc'
//   * for a DLC, a parent -- either another manual store link on the same atlas
//     row, or one of that row's source mappings (F95 / LewdCorner / DLsite /
//     SXS)
//
// 'custom' links are deliberately excluded from typing: they're plain web pages
// (a dev blog, a Discord, a Patreon), not store entries, so a game/DLC
// distinction is meaningless for them. They keep using `label` as their display
// name, which is what they already did.
// ---------------------------------------------------------------------------
import { q, q1, tx, touchAtlas } from './db.js';
import { logAudit } from './atlas.js';

export const MANUAL_LINK_KINDS = ['steam', 'gog', 'itch', 'custom'];
const KIND_SET = new Set(MANUAL_LINK_KINDS);

// Kinds that represent a storefront entry, and so may be typed/labelled/parented.
export const STORE_KINDS = ['steam', 'gog', 'itch'];
const STORE_SET = new Set(STORE_KINDS);

export const ENTRY_TYPES = ['game', 'dlc'];
const ENTRY_SET = new Set(ENTRY_TYPES);

// Source tables a DLC may hang off, mirroring lib/merge.js.
export const PARENT_SOURCES = ['f95_zone', 'lewdcorner', 'dlsite', 'sxs'];
const PARENT_SOURCE_ID_COL = {
  f95_zone: 'f95_id', lewdcorner: 'lc_id', dlsite: 'dlsite_id', sxs: 'sxs_id',
};
export const PARENT_KINDS = ['manual', ...PARENT_SOURCES];
const PARENT_KIND_SET = new Set(PARENT_KINDS);

const now = () => Math.floor(Date.now() / 1000);

export function isStoreKind(kind) {
  return STORE_SET.has(String(kind || '').toLowerCase());
}

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

// Host used for the favicon (issue #285). Derived server-side so every client
// renders the same icon, and so a malformed url can't produce a broken <img>.
export function faviconHost(kind, url) {
  const fallback = {
    steam: 'store.steampowered.com',
    gog: 'www.gog.com',
    itch: 'itch.io',
  }[String(kind || '').toLowerCase()];
  if (url) {
    try {
      const host = new URL(url).hostname;
      if (host) return host;
    } catch {
      /* fall through to the per-kind default */
    }
  }
  return fallback || null;
}

function decorate(row) {
  if (!row) return row;
  return {
    ...row,
    _store: isStoreKind(row.kind),
    _favicon_host: faviconHost(row.kind, row.url),
  };
}

/**
 * Distinct labels previously used on 'custom' links, most-used first.
 *
 * Backs a suggestion list on the "Add link" form so an admin naming a custom
 * link (Patreon, Discord, official site...) sees what's already in use instead
 * of retyping it, and so the same site doesn't end up spelled three different
 * ways across different games. 'Link' is excluded -- that's normaliseCore's
 * fallback for an unlabelled custom link, not something anyone chose.
 */
export async function getCustomLinkLabels(limit = 50) {
  const lim = Math.min(Math.max(parseInt(limit, 10) || 50, 1), 200);
  const rows = await q(
    `SELECT label, COUNT(*) AS n
       FROM atlas_manual_links
      WHERE kind = 'custom' AND label IS NOT NULL AND label <> 'Link'
      GROUP BY label
      ORDER BY n DESC, label ASC
      LIMIT ${lim}`,
  );
  return rows.map((r) => r.label);
}

/** All manual links for an atlas row, base games first then their DLC. */
export async function getManualLinks(atlasId) {
  const rows = await q(
    `SELECT link_id, atlas_id, kind, label, ext_id, url,
            entry_type, parent_kind, parent_link_id, parent_source_id,
            added_by, added_at
       FROM atlas_manual_links WHERE atlas_id = ?
      ORDER BY entry_type ASC, added_at DESC, link_id DESC`,
    [Number(atlasId)],
  );
  return rows.map(decorate);
}

function describe(link) {
  const bits = [link.kind];
  if (link.label) bits.push(`"${link.label}"`);
  if (link.entry_type === 'dlc') bits.push('[dlc]');
  const idPart = `${link.ext_id || ''}${link.ext_id && link.url ? ' \u00b7 ' : ''}${link.url || ''}`;
  return `${bits.join(' ')}: ${idPart}`.trim();
}

/**
 * Validate a requested parent for a DLC entry and return the columns to store.
 *
 * The rules exist to stop the tree becoming nonsense, and none of them can be a
 * CHECK constraint (they're all cross-row):
 *   - only a 'dlc' may have a parent
 *   - the parent must belong to the SAME atlas row
 *   - a manual parent must itself be a 'game', so DLC can't chain off DLC
 *   - a link can't be its own parent
 */
async function resolveParent(atlasId, { entryType, parentKind, parentLinkId, parentSourceId }, selfLinkId = null) {
  if (entryType !== 'dlc') {
    if (parentKind) {
      throw Object.assign(
        new Error('Only a DLC entry can have a parent. Set the type to "dlc" first.'),
        { status: 400 });
    }
    return { parent_kind: null, parent_link_id: null, parent_source_id: null };
  }
  if (!parentKind) {
    // A DLC with no parent is allowed -- it's how you record one before the base
    // entry exists. The UI shows it as unparented.
    return { parent_kind: null, parent_link_id: null, parent_source_id: null };
  }

  const kind = String(parentKind).toLowerCase().trim();
  if (!PARENT_KIND_SET.has(kind)) {
    throw Object.assign(new Error(`Unknown parent kind "${parentKind}".`), { status: 400 });
  }

  if (kind === 'manual') {
    const id = Number(parentLinkId);
    if (!id) {
      throw Object.assign(new Error('Choose which link this DLC belongs to.'), { status: 400 });
    }
    if (selfLinkId && id === Number(selfLinkId)) {
      throw Object.assign(new Error('A link cannot be its own parent.'), { status: 400 });
    }
    const parent = await q1(
      'SELECT link_id, atlas_id, entry_type FROM atlas_manual_links WHERE link_id = ? LIMIT 1',
      [id]);
    if (!parent) {
      throw Object.assign(new Error(`No link #${id}.`), { status: 404 });
    }
    if (Number(parent.atlas_id) !== Number(atlasId)) {
      throw Object.assign(
        new Error('That parent link belongs to a different game.'), { status: 400 });
    }
    if (parent.entry_type === 'dlc') {
      throw Object.assign(
        new Error('A DLC cannot be the parent of another DLC. Pick the base game entry.'),
        { status: 400 });
    }
    return { parent_kind: 'manual', parent_link_id: id, parent_source_id: null };
  }

  // A source mapping: verify the row exists AND is mapped to this atlas game, so
  // a typo can't tie a DLC to another game's F95 thread.
  const idCol = PARENT_SOURCE_ID_COL[kind];
  const wanted = String(parentSourceId ?? '').trim();
  if (!wanted) {
    throw Object.assign(new Error(`Provide the ${idCol} to tie this DLC to.`), { status: 400 });
  }
  const owner = await q1(
    `SELECT ${idCol} AS id FROM ${kind} WHERE ${idCol} = ? AND atlas_id = ? LIMIT 1`,
    [wanted, Number(atlasId)]);
  if (!owner) {
    throw Object.assign(
      new Error(`${kind} ${wanted} is not mapped to atlas #${atlasId}.`), { status: 400 });
  }
  return { parent_kind: kind, parent_link_id: null, parent_source_id: String(owner.id) };
}

function normaliseCore({ kind, label, extId, url, entryType }) {
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

  // Labels are free text on store kinds, and remain the display name on custom.
  let lbl = (label ?? '').toString().trim() || null;
  if (lbl && lbl.length > 128) lbl = lbl.slice(0, 128);
  if (k === 'custom' && !lbl) lbl = 'Link';

  let type = String(entryType || 'game').toLowerCase().trim();
  if (!ENTRY_SET.has(type)) {
    throw Object.assign(new Error(`Unknown entry type "${entryType}".`), { status: 400 });
  }
  // Typing a plain web page as DLC is meaningless; keep those as 'game'.
  if (!STORE_SET.has(k)) type = 'game';

  return { kind: k, label: lbl, extId: cleanId, url: cleanUrl, entryType: type };
}

/** Add one manual link. Requires at least an ext_id or a url. */
export async function addManualLink(atlasId, input, user) {
  atlasId = Number(atlasId);
  const core = normaliseCore(input || {});

  const exists = await q1('SELECT 1 AS x FROM atlas WHERE atlas_id = ? LIMIT 1', [atlasId]);
  if (!exists) {
    throw Object.assign(new Error(`No atlas row #${atlasId}.`), { status: 404 });
  }

  const parent = await resolveParent(atlasId, {
    entryType: core.entryType,
    parentKind: input?.parentKind,
    parentLinkId: input?.parentLinkId,
    parentSourceId: input?.parentSourceId,
  });

  const ts = now();
  let insertId;
  await tx(async (conn) => {
    const [res] = await conn.execute(
      `INSERT INTO atlas_manual_links
         (atlas_id, kind, label, ext_id, url, entry_type,
          parent_kind, parent_link_id, parent_source_id, added_by, added_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [atlasId, core.kind, core.label, core.extId, core.url, core.entryType,
       parent.parent_kind, parent.parent_link_id, parent.parent_source_id, user, ts],
    );
    insertId = res.insertId;
    // A manual link is new data on this atlas record; bump its export timestamp
    // so the added id/url reaches clients.
    await touchAtlas(conn, atlasId, ts);
    await logAudit(conn, {
      atlasId, field: 'manual_link.add', user,
      oldValue: null,
      newValue: describe({ ...core, ext_id: core.extId, entry_type: core.entryType }),
      snapshot: { table: 'atlas_manual_links', linkId: insertId },
    });
  });

  return decorate({
    link_id: insertId, atlas_id: atlasId, kind: core.kind, label: core.label,
    ext_id: core.extId, url: core.url, entry_type: core.entryType,
    ...parent, added_by: user, added_at: ts,
  });
}

/** Update label / id / url / entry type / parent on an existing link. */
export async function updateManualLink(atlasId, linkId, input, user) {
  atlasId = Number(atlasId);
  linkId = Number(linkId);
  const current = await q1(
    `SELECT link_id, atlas_id, kind, label, ext_id, url, entry_type,
            parent_kind, parent_link_id, parent_source_id
       FROM atlas_manual_links WHERE link_id = ? AND atlas_id = ? LIMIT 1`,
    [linkId, atlasId]);
  if (!current) {
    throw Object.assign(new Error('Link not found.'), { status: 404 });
  }

  const has = (key) => Object.prototype.hasOwnProperty.call(input || {}, key);
  const core = normaliseCore({
    kind: current.kind,
    label: has('label') ? input.label : current.label,
    extId: has('extId') ? input.extId : current.ext_id,
    url: has('url') ? input.url : current.url,
    entryType: has('entryType') ? input.entryType : current.entry_type,
  });

  const parentInput = (has('parentKind') || has('parentLinkId') || has('parentSourceId'))
    ? { parentKind: input.parentKind, parentLinkId: input.parentLinkId,
        parentSourceId: input.parentSourceId }
    : { parentKind: current.parent_kind, parentLinkId: current.parent_link_id,
        parentSourceId: current.parent_source_id };

  // Demoting a base entry that DLC hang off would leave them pointing at a DLC,
  // which resolveParent forbids on the way in; refuse it here too rather than
  // letting the data reach a state the validator would reject.
  if (current.entry_type === 'game' && core.entryType === 'dlc') {
    const kids = await q1(
      'SELECT COUNT(*) AS n FROM atlas_manual_links WHERE parent_link_id = ?', [linkId]);
    if (kids && Number(kids.n) > 0) {
      throw Object.assign(
        new Error(`${kids.n} DLC entr${Number(kids.n) === 1 ? 'y' : 'ies'} hang off this link. `
                  + 'Re-tie or remove them before making it a DLC itself.'),
        { status: 400 });
    }
  }

  const parent = await resolveParent(atlasId,
    { entryType: core.entryType, ...parentInput }, linkId);

  const before = describe(current);
  const ts = now();
  await tx(async (conn) => {
    await conn.execute(
      `UPDATE atlas_manual_links
          SET label = ?, ext_id = ?, url = ?, entry_type = ?,
              parent_kind = ?, parent_link_id = ?, parent_source_id = ?
        WHERE link_id = ? AND atlas_id = ?`,
      [core.label, core.extId, core.url, core.entryType,
       parent.parent_kind, parent.parent_link_id, parent.parent_source_id,
       linkId, atlasId],
    );
    await touchAtlas(conn, atlasId, ts);
    await logAudit(conn, {
      atlasId, field: 'manual_link.update', user,
      oldValue: before,
      newValue: describe({ ...core, ext_id: core.extId, entry_type: core.entryType }),
      // The full prior row. `oldValue` is a human description; parsing it back
      // would be guesswork.
      snapshot: { table: 'atlas_manual_links', linkId, before: current },
    });
  });

  return decorate({
    link_id: linkId, atlas_id: atlasId, kind: current.kind, label: core.label,
    ext_id: core.extId, url: core.url, entry_type: core.entryType, ...parent,
  });
}

/** Remove one manual link (scoped to its atlas row for safety). */
export async function removeManualLink(atlasId, linkId, user) {
  atlasId = Number(atlasId);
  linkId = Number(linkId);
  const l = await q1(
    `SELECT * FROM atlas_manual_links WHERE link_id = ? AND atlas_id = ? LIMIT 1`,
    [linkId, atlasId]);
  if (!l) {
    throw Object.assign(new Error('Link not found.'), { status: 404 });
  }
  // Report how many DLC get orphaned, so the UI can warn before deleting.
  const kidRows = await q(
    'SELECT link_id FROM atlas_manual_links WHERE parent_link_id = ?', [linkId]);
  const childIds = kidRows.map((r) => r.link_id);
  const kids = { n: childIds.length };
  await tx(async (conn) => {
    // The FK is ON DELETE SET NULL, so children survive as unparented rather
    // than vanishing with the parent.
    await conn.execute(
      'DELETE FROM atlas_manual_links WHERE link_id = ? AND atlas_id = ?', [linkId, atlasId]);
    await touchAtlas(conn, atlasId);
    await logAudit(conn, {
      atlasId, field: 'manual_link.remove', user,
      oldValue: describe(l), newValue: null,
      // The deleted row, plus the DLC whose parent pointer the FK just nulled,
      // so an undo can restore the link AND re-tie its children.
      snapshot: { table: 'atlas_manual_links', row: l, orphanedChildren: childIds },
    });
  });
  return { removed: linkId, orphaned: kids ? Number(kids.n) : 0 };
}

/**
 * Candidate parents for a DLC on this atlas row: its non-DLC manual store links
 * plus its source mappings. Populates the parent picker.
 */
export async function getParentOptions(atlasId) {
  atlasId = Number(atlasId);
  const manual = await q(
    `SELECT link_id, kind, label, ext_id, url
       FROM atlas_manual_links
      WHERE atlas_id = ? AND entry_type = 'game'
      ORDER BY kind, link_id`,
    [atlasId]);

  const sources = [];
  for (const table of PARENT_SOURCES) {
    const idCol = PARENT_SOURCE_ID_COL[table];
    try {
      const rows = await q(
        `SELECT ${idCol} AS id, site_url FROM ${table} WHERE atlas_id = ?`, [atlasId]);
      for (const r of rows) {
        sources.push({
          parent_kind: table, id_col: idCol, id: String(r.id), site_url: r.site_url,
        });
      }
    } catch {
      // A partial dev database may not have every source table; skip it rather
      // than failing the whole picker.
    }
  }

  return {
    manual: manual.map((m) => ({
      parent_kind: 'manual',
      link_id: m.link_id,
      kind: m.kind,
      label: m.label,
      title: m.label || `${m.kind} ${m.ext_id || m.url || ''}`.trim(),
    })),
    sources,
  };
}
