import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { q } from '../lib/db.js';

const router = safeRouter(express.Router());

// GET /api/updates  — PUBLIC, read-only. Replaces the old updates.php.
//
// Returns the full `updates` table as a JSON array of
//   { date: <int epoch>, name: <string>, md5: <string>, is_full: <bool> }
// ordered by date DESC. The Atlas client compares these to its local update
// history and downloads newer .update files from /packages/. `is_full` tells
// the client whether a package is the complete dataset (true) or a snapshot of
// records changed since the last run (false).
//
// IMPORTANT: the response shape matches updates.php exactly so the existing
// client keeps working unchanged — date coerced to int, is_full to a real
// JSON boolean, and an empty table returns [] (never null).
router.get('/', async (req, res) => {
  res.set('Content-Type', 'application/json');
  let rows = [];
  try {
    rows = await q('SELECT date, name, md5, is_full FROM updates ORDER BY date DESC');
  } catch {
    return res.status(500).json({ error: 'database connection failed' });
  }
  const out = rows.map((r) => ({
    date: Number(r.date),
    name: r.name,
    md5: r.md5,
    is_full: Boolean(r.is_full),
  }));
  res.json(out);
});

export default router;
