import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import {
  enqueue, enqueueMany, list, summary, retry, cancel, clearFinished,
  REFRESH_SOURCES,
} from '../lib/f95Refresh.js';

const router = safeRouter(express.Router());

// GET /api/f95-refresh?status=&source=&limit=&offset=  — list queue rows
router.get('/', async (req, res) => {
  const { status, source, limit, offset } = req.query;
  res.json(await list({ status: status || null, source: source || null, limit, offset }));
});

// GET /api/f95-refresh/sources — which sources this build's worker supports,
// for a filter dropdown / for the SourcePanel to know which "Queue refresh"
// buttons to show.
router.get('/sources', (req, res) => {
  res.json({ sources: REFRESH_SOURCES });
});

// GET /api/f95-refresh/summary — status counts + rough ETA + per-source breakdown
router.get('/summary', async (req, res) => {
  res.json(await summary());
});

// POST /api/f95-refresh  { f95Id, source? }  OR  { f95Ids: [...], source? }  — enqueue
// `source` defaults to 'f95' so every existing caller keeps working unchanged.
router.post('/', async (req, res) => {
  try {
    const { f95Id, f95Ids, priority, source } = req.body || {};
    if (Array.isArray(f95Ids)) {
      return res.json({ results: await enqueueMany(f95Ids, req.user.username, priority, source) });
    }
    if (f95Id == null || f95Id === '') {
      return res.status(400).json({ error: 'Provide an id to refresh.' });
    }
    res.json(await enqueue(f95Id, req.user.username, priority, source));
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// POST /api/f95-refresh/:queueId/retry — requeue a finished/errored item
router.post('/:queueId/retry', async (req, res) => {
  try {
    res.json(await retry(Number(req.params.queueId), req.user.username));
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// DELETE /api/f95-refresh/:queueId — cancel pending / remove finished
router.delete('/:queueId', async (req, res) => {
  try {
    res.json(await cancel(Number(req.params.queueId)));
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// POST /api/f95-refresh/clear-finished — housekeeping
router.post('/clear-finished', async (req, res) => {
  try {
    res.json(await clearFinished());
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

export default router;
