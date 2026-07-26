import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import {
  getQueue, getQueueItem, candidatesFor,
  linkQueueItem, newFromQueueItem, dismissQueueItem, deferQueueItem,
} from '../lib/queue.js';
import { getAtlasRowsByIds } from '../lib/candidates.js';
import { getSourceOwners, getSourceIds, getSourceLinks } from '../lib/merge.js';
import { getAtlasRow } from '../lib/atlas.js';

const router = safeRouter(express.Router());

// GET /api/queue?kind=multi|fuzzy
router.get('/', async (req, res) => {
  const kind = req.query.kind || null;
  const items = await getQueue(kind);
  res.json({ count: items.length, items });
});

// GET /api/queue/:lcId  — the item plus its live candidate atlas rows
router.get('/:lcId', async (req, res) => {
  const item = await getQueueItem(Number(req.params.lcId));
  if (!item) return res.status(404).json({ error: 'No queue item with that id.' });
  const candIds = await candidatesFor(item);
  const rows = await getAtlasRowsByIds(candIds);
  const candidates = [];
  for (const r of rows) {
    candidates.push({
      ...r,
      _owners: await getSourceOwners(r.atlas_id),
      _sources: await getSourceIds(r.atlas_id),
      _links: await getSourceLinks(r.atlas_id),
    });
  }
  // preserve candidate ordering
  candidates.sort((a, b) => candIds.indexOf(a.atlas_id) - candIds.indexOf(b.atlas_id));
  res.json({ item, candidates });
});

// GET /api/queue/atlas-lookup/:atlasId
// Backs the "map by atlas id" input (issue #276): confirm the id exists and show
// what it is BEFORE linking, so a typo doesn't silently attach a LewdCorner
// thread to an unrelated game. Linking itself still goes through
// POST /:lcId/link, which is unchanged.
router.get('/atlas-lookup/:atlasId', async (req, res) => {
  const id = Number(req.params.atlasId);
  if (!Number.isInteger(id) || id <= 0) {
    return res.status(400).json({ error: 'Enter a positive whole atlas id.' });
  }
  const row = await getAtlasRow(id);
  if (!row) return res.status(404).json({ error: `No atlas row #${id}.` });
  const owners = await getSourceOwners(id);
  const sources = await getSourceIds(id);
  const links = await getSourceLinks(id);
  // An atlas row that already owns a LewdCorner mapping cannot take another:
  // lewdcorner.atlas_id is UNIQUE, so the insert would fail. Flag it up front
  // rather than letting the link attempt blow up.
  res.json({
    ...row,
    _owners: owners,
    _sources: sources,
    _links: links,
    _has_lc: owners.includes('lewdcorner'),
  });
});

router.post('/:lcId/link', async (req, res) => {
  try {
    const { atlasId } = req.body || {};
    if (!atlasId) return res.status(400).json({ error: 'Choose an atlas row to link to.' });
    res.json(await linkQueueItem(Number(req.params.lcId), Number(atlasId), req.user.username));
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

router.post('/:lcId/new', async (req, res) => {
  try {
    res.json(await newFromQueueItem(Number(req.params.lcId), req.user.username));
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

router.post('/:lcId/defer', async (req, res) => {
  try {
    res.json(await deferQueueItem(Number(req.params.lcId), req.user.username));
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

router.post('/:lcId/dismiss', async (req, res) => {
  try {
    res.json(await dismissQueueItem(Number(req.params.lcId), req.user.username));
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

export default router;
