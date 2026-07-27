import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { previewRevert, revertAudit } from '../lib/revert.js';

const router = safeRouter(express.Router());

// GET /api/revert/:auditId  — what would this undo? Never writes.
router.get('/:auditId', async (req, res) => {
  try {
    res.json(await previewRevert(Number(req.params.auditId)));
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

// POST /api/revert/:auditId — undo it (and the rest of its batch).
router.post('/:auditId', async (req, res) => {
  try {
    res.json(await revertAudit(Number(req.params.auditId), req.user.username));
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

export default router;
