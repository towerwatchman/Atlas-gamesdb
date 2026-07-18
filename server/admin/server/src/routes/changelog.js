// ---------------------------------------------------------------------------
// Changelog API — read-only view over atlas_audit for the admin portal.
//   GET /admin/api/changelog        filtered, paginated feed
//   GET /admin/api/changelog/users  distinct admin users (for the filter)
// ---------------------------------------------------------------------------
import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { getChangelog, getChangelogUsers } from '../lib/changelog.js';

const router = safeRouter(express.Router());

router.get('/', async (req, res) => {
  const { user, group, since, until, atlasId, limit, offset } = req.query;
  const result = await getChangelog({ user, group, since, until, atlasId, limit, offset });
  res.json(result);
});

router.get('/users', async (req, res) => {
  res.json(await getChangelogUsers());
});

export default router;
