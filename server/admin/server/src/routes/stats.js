import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { q1 } from '../lib/db.js';

const router = safeRouter(express.Router());

// GET /api/stats — headline counts for the home dashboard.
router.get('/', async (req, res) => {
  // Each count is its own query so one missing table (partial dev DB) doesn't
  // sink the whole dashboard; failures fall back to null and the UI shows "—".
  async function count(sql) {
    try { return (await q1(sql)).n; } catch { return null; }
  }

  const [atlas, f95, lc, lcFloating, f95Floating, queue] = await Promise.all([
    count('SELECT COUNT(*) AS n FROM atlas'),
    count('SELECT COUNT(*) AS n FROM f95_zone'),
    count('SELECT COUNT(*) AS n FROM lewdcorner'),
    count('SELECT COUNT(*) AS n FROM lewdcorner WHERE floating = 1'),
    count('SELECT COUNT(*) AS n FROM f95_zone WHERE floating = 1'),
    count('SELECT COUNT(*) AS n FROM lc_review_queue'),
  ]);

  res.json({
    atlas,
    sources: { f95, lc },
    floating: { f95: f95Floating, lc: lcFloating },
    queue,
  });
});

export default router;
