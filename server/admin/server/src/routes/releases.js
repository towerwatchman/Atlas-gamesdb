import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { getReleases } from '../lib/releases.js';

const router = safeRouter(express.Router());

// GET /api/releases?force=1
router.get('/', async (req, res) => {
  try {
    res.json(await getReleases({ force: req.query.force === '1' }));
  } catch (err) {
    res.status(err.status || 502).json({ error: err.message });
  }
});

export default router;
