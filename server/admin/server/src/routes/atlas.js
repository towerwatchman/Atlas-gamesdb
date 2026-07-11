import express from 'express';
import { q } from '../lib/db.js';
import {
  getAtlasRow, editAtlasRow, getAuditForAtlas, getRecentAudit,
  EDITABLE_ATLAS_COLUMNS,
} from '../lib/atlas.js';
import { getSourceIds } from '../lib/merge.js';

const router = express.Router();

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
  const lim = Math.min(Number(limit) || 50, 200);
  const off = Number(offset) || 0;

  const rows = await q(
    `SELECT a.atlas_id, a.title, a.creator, a.developer, a.version,
            a.engine, a.status, a.id_name, a.edited, a.edited_at, a.edited_by,
            f.f95_id, l.lc_id
       FROM atlas a
       LEFT JOIN f95_zone f ON f.atlas_id = a.atlas_id
       LEFT JOIN lewdcorner l ON l.atlas_id = a.atlas_id
       ${whereSql}
       ORDER BY a.atlas_id
       LIMIT ? OFFSET ?`,
    [...params, lim, off],
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
  res.json({ ...row, _sources: sources });
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
