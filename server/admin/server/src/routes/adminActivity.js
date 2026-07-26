import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import {
  getAdminActivity, getActivityTimeline, getAdminRecent,
  getAuditUsers, getAuditBounds, CATEGORIES,
} from '../lib/adminActivity.js';

const router = safeRouter(express.Router());

function windowFromQuery(query) {
  const days = query.days === 'all' ? null : (parseInt(query.days, 10) || 30);
  const since = query.since ? Number(query.since)
    : (days ? Math.floor(Date.now() / 1000) - days * 86400 : null);
  const until = query.until ? Number(query.until) : null;
  return { since, until, days };
}

// GET /api/admin-activity?days=30|all
router.get('/', async (req, res) => {
  const { since, until, days } = windowFromQuery(req.query);
  const [activity, bounds, users] = await Promise.all([
    getAdminActivity({ since, until }),
    getAuditBounds(),
    getAuditUsers(),
  ]);
  res.json({ ...activity, since, until, days, bounds, users, categories: CATEGORIES });
});

// GET /api/admin-activity/timeline?days=30&user=
router.get('/timeline', async (req, res) => {
  const { since, until } = windowFromQuery(req.query);
  res.json(await getActivityTimeline({
    since, until, user: req.query.user || null, days: req.query.days,
  }));
});

// GET /api/admin-activity/:user/recent?limit=50
router.get('/:user/recent', async (req, res) => {
  res.json(await getAdminRecent(req.params.user, Number(req.query.limit) || 50));
});

export default router;
