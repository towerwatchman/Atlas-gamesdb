import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { q } from '../lib/db.js';
import {
  getAtlasRow, editAtlasRow, createAtlasRow, getAuditForAtlas, getRecentAudit,
  setFieldLock, parseLockedFields,
  EDITABLE_ATLAS_COLUMNS, DATE_ATLAS_COLUMNS, LOCKABLE_ATLAS_COLUMNS,
} from '../lib/atlas.js';
import { getSourceIds, getSourceLinks } from '../lib/merge.js';
import { getSourceDetail } from '../lib/sourceDetail.js';
import { parseExternalIds } from '../lib/externalIds.js';
import { computeIdentity } from '../lib/identity.js';
import { buildAtlasSearch } from '../lib/search.js';
import {
  getManualLinks, addManualLink, updateManualLink, removeManualLink,
  getParentOptions,
  MANUAL_LINK_KINDS, STORE_KINDS, ENTRY_TYPES, PARENT_KINDS,
} from '../lib/manualLinks.js';

const router = safeRouter(express.Router());

// GET /api/atlas?search=...&edited=0|1&limit=&offset=
// Ranked, multi-term search — see lib/search.js for what was wrong before.
router.get('/', async (req, res) => {
  const { search = '', edited, limit = 50, offset = 0 } = req.query;
  const {
    joinSql, whereSql, orderSql, scoreSql, params, countParams,
  } = buildAtlasSearch({ search, edited });

  // LIMIT/OFFSET cannot be bound as prepared-statement params in MySQL, so
  // they are coerced to safe non-negative integers and inlined directly.
  const lim = Math.min(Math.max(parseInt(limit, 10) || 50, 1), 200);
  const off = Math.max(parseInt(offset, 10) || 0, 0);

  const rows = await q(
    `SELECT a.atlas_id, a.title, a.creator, a.developer, a.version,
            a.engine, a.status, a.id_name, a.edited, a.edited_at, a.edited_by,
            f.f95_id, f.site_url AS f95_url,
            l.lc_id, l.site_url AS lc_url,
            (${scoreSql}) AS _score
       ${joinSql}
       ${whereSql}
       ${orderSql}
       LIMIT ${lim} OFFSET ${off}`,
    params,
  );
  // Same joins + WHERE as the row query, so the two can never disagree about
  // what matched.
  const countRow = await q(
    `SELECT COUNT(*) AS n ${joinSql} ${whereSql}`, countParams);
  res.json({ rows, total: countRow[0].n, limit: lim, offset: off });
});

router.get('/editable-columns', (req, res) => {
  res.json(EDITABLE_ATLAS_COLUMNS);
});

// Column metadata: which fields are dates (date picker rather than a number
// box) and which can be locked against the scraper.
router.get('/meta/columns', (req, res) => {
  res.json({
    editable: EDITABLE_ATLAS_COLUMNS,
    dates: DATE_ATLAS_COLUMNS,
    lockable: LOCKABLE_ATLAS_COLUMNS,
  });
});

// Preview the identity keys the server would derive, so the create form can
// show them live and warn about a collision before anything is written.
router.get('/preview-identity', async (req, res) => {
  const title = String(req.query.title || '');
  const creator = String(req.query.creator || '');
  const identity = computeIdentity(title, creator);
  let clash = null;
  if (identity.id_name && identity.id_name !== '_') {
    const rows = await q(
      'SELECT atlas_id, title FROM atlas WHERE id_name = ? LIMIT 1', [identity.id_name]);
    clash = rows[0] || null;
  }
  res.json({ ...identity, clash });
});

router.get('/audit/recent', async (req, res) => {
  res.json(await getRecentAudit(Number(req.query.limit) || 200));
});

// POST /api/atlas — create a game by hand. atlas_id comes from AUTO_INCREMENT.
router.post('/', async (req, res) => {
  try {
    const created = await createAtlasRow(req.body?.fields || req.body || {}, req.user.username);
    res.status(201).json(created);
  } catch (err) {
    res.status(err.status || 500).json({
      error: err.message,
      atlasId: err.atlasId,
      idName: err.idName,
    });
  }
});

router.get('/:id', async (req, res) => {
  const id = Number(req.params.id);
  const row = await getAtlasRow(id);
  if (!row) return res.status(404).json({ error: 'No atlas row with that id.' });
  const [sources, links, manualLinks, sourceDetail, parentOptions] = await Promise.all([
    getSourceIds(id), getSourceLinks(id), getManualLinks(id),
    getSourceDetail(id), getParentOptions(id),
  ]);
  res.json({
    ...row,
    _sources: sources,
    _links: links,
    _manual_links: manualLinks,
    // Full mapped source rows for the side panel (issue #286).
    _source_detail: sourceDetail,
    // The scraper's own external_ids blob, rendered as links. Read-only: the
    // scraper rewrites that column wholesale on every refresh.
    _scraped_links: parseExternalIds(row.external_ids),
    // Fields a human has claimed; the scraper skips these on its next crawl.
    _locked_fields: parseLockedFields(row.locked_fields),
    _parent_options: parentOptions,
  });
});

// --- manual external links (Steam/GOG/Itch/custom), scraper-safe -----------
router.get('/:id/manual-links', async (req, res) => {
  res.json(await getManualLinks(Number(req.params.id)));
});

router.get('/:id/manual-links/parent-options', async (req, res) => {
  res.json(await getParentOptions(Number(req.params.id)));
});

router.get('/meta/manual-link-kinds', (req, res) => {
  res.json({
    kinds: MANUAL_LINK_KINDS,
    storeKinds: STORE_KINDS,
    entryTypes: ENTRY_TYPES,
    parentKinds: PARENT_KINDS,
  });
});

router.post('/:id/manual-links', async (req, res) => {
  try {
    const created = await addManualLink(Number(req.params.id), req.body || {}, req.user.username);
    res.status(201).json(created);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

router.patch('/:id/manual-links/:linkId', async (req, res) => {
  try {
    const updated = await updateManualLink(
      Number(req.params.id), Number(req.params.linkId), req.body || {}, req.user.username);
    res.json(updated);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

router.delete('/:id/manual-links/:linkId', async (req, res) => {
  try {
    const result = await removeManualLink(
      Number(req.params.id), Number(req.params.linkId), req.user.username);
    res.json(result);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

// PUT /api/atlas/:id/locks/:field  { locked: true|false }
router.put('/:id/locks/:field', async (req, res) => {
  try {
    res.json(await setFieldLock(
      Number(req.params.id), req.params.field,
      Boolean(req.body?.locked), req.user.username));
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

router.get('/:id/audit', async (req, res) => {
  res.json(await getAuditForAtlas(Number(req.params.id)));
});

// PATCH /api/atlas/:id  { changes: { field: value, ... } }
router.patch('/:id', async (req, res) => {
  try {
    const result = await editAtlasRow(Number(req.params.id), req.body?.changes || {}, req.user.username);
    res.json(result);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

export default router;
