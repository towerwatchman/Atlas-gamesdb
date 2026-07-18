import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { q } from '../lib/db.js';
import {
  getAtlasRow, editAtlasRow, getAuditForAtlas, getRecentAudit,
  EDITABLE_ATLAS_COLUMNS,
} from '../lib/atlas.js';
import { getSourceIds, getSourceLinks } from '../lib/merge.js';
import {
  getManualLinks, addManualLink, removeManualLink, MANUAL_LINK_KINDS,
} from '../lib/manualLinks.js';

const router = safeRouter(express.Router());

// GET /api/atlas?search=...&edited=0|1&limit=&offset=
router.get('/', async (req, res) => {
  const { search = '', edited, limit = 50, offset = 0 } = req.query;
  const where = [];
  const params = [];
  if (search) {
    where.push('(a.title LIKE ? OR a.creator LIKE ? OR a.developer LIKE ? OR a.id_name LIKE ?)');
    const like = `%${search}%`;
    params.push(like, like, like, like);
  }
  if (edited === '0' || edited === '1') {
    where.push('a.edited = ?');
    params.push(Number(edited));
  }
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';
  // LIMIT/OFFSET cannot be bound as prepared-statement params in MySQL, so
  // they are coerced to safe non-negative integers and inlined directly.
  const lim = Math.min(Math.max(parseInt(limit, 10) || 50, 1), 200);
  const off = Math.max(parseInt(offset, 10) || 0, 0);

  const rows = await q(
    `SELECT a.atlas_id, a.title, a.creator, a.developer, a.version,
            a.engine, a.status, a.id_name, a.edited, a.edited_at, a.edited_by,
            f.f95_id, f.site_url AS f95_url,
            l.lc_id, l.site_url AS lc_url
       FROM atlas a
       LEFT JOIN f95_zone f ON f.atlas_id = a.atlas_id
       LEFT JOIN lewdcorner l ON l.atlas_id = a.atlas_id
       ${whereSql}
       ORDER BY a.atlas_id
       LIMIT ${lim} OFFSET ${off}`,
    params,
  );
  const countRow = await q(`SELECT COUNT(*) AS n FROM atlas a ${whereSql}`, params);
  res.json({ rows, total: countRow[0].n, limit: lim, offset: off });
});

router.get('/editable-columns', (req, res) => {
  res.json(EDITABLE_ATLAS_COLUMNS);
});

router.get('/audit/recent', async (req, res) => {
  res.json(await getRecentAudit(Number(req.query.limit) || 200));
});

router.get('/:id', async (req, res) => {
  const row = await getAtlasRow(Number(req.params.id));
  if (!row) return res.status(404).json({ error: 'No atlas row with that id.' });
  const sources = await getSourceIds(Number(req.params.id));
  const links = await getSourceLinks(Number(req.params.id));
  const manualLinks = await getManualLinks(Number(req.params.id));
  res.json({ ...row, _sources: sources, _links: links, _manual_links: manualLinks });
});

// --- manual external links (Steam/GOG/Itch/custom), scraper-safe -----------
router.get('/:id/manual-links', async (req, res) => {
  res.json(await getManualLinks(Number(req.params.id)));
});

router.get('/meta/manual-link-kinds', (req, res) => {
  res.json(MANUAL_LINK_KINDS);
});

router.post('/:id/manual-links', async (req, res) => {
  try {
    const { kind, label, extId, url } = req.body || {};
    const created = await addManualLink(Number(req.params.id), { kind, label, extId, url }, req.user.username);
    res.json(created);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

router.delete('/:id/manual-links/:linkId', async (req, res) => {
  try {
    const result = await removeManualLink(Number(req.params.id), Number(req.params.linkId), req.user.username);
    res.json(result);
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
