import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import { loadAtlasWithSources, rowSources, getAtlasRowsByIds } from '../lib/candidates.js';
import { findExactGroups, findFuzzyGroups } from '../lib/matching.js';
import {
  mergeAtlasGroup, relinkSource, deleteAtlasIfOrphaned,
  getSourceOwners, getSourceIds, getSourceLinks,
} from '../lib/merge.js';

const router = safeRouter(express.Router());

function groupSources(members) {
  const s = new Set();
  for (const m of members) for (const x of rowSources(m)) s.add(x);
  return [...s].sort();
}

function scopeOk(members, scope) {
  const s = new Set(groupSources(members));
  if (scope === 'f95') return s.has('f95');
  if (scope === 'lc') return s.has('lc');
  if (scope === 'cross') return s.has('f95') && s.has('lc');
  return true;
}

// GET /api/duplicates?scope=all|f95|lc|cross&floor=0.90&kinds=exact,fuzzy
// Finds duplicate ATLAS rows (the same game represented by 2+ atlas_ids).
router.get('/', async (req, res) => {
  const scope = req.query.scope || 'all';
  const floor = Math.min(Math.max(Number(req.query.floor) || 0.90, 0.5), 1);
  const kinds = (req.query.kinds || 'exact,fuzzy').split(',');

  const rows = await loadAtlasWithSources();
  const out = [];

  if (kinds.includes('exact')) {
    for (const g of findExactGroups(rows)) {
      if (!scopeOk(g.members, scope)) continue;
      out.push({ kind: 'exact', key: g.key, sources: groupSources(g.members), members: g.members });
    }
  }
  if (kinds.includes('fuzzy')) {
    for (const g of findFuzzyGroups(rows, floor)) {
      if (!scopeOk(g.members, scope)) continue;
      out.push({ kind: 'fuzzy', key: g.key, sources: groupSources(g.members), members: g.members });
    }
  }

  out.sort((a, b) => b.members.length - a.members.length);
  res.json({
    scope, floor, atlasCount: rows.length,
    exact: out.filter((g) => g.kind === 'exact').length,
    fuzzy: out.filter((g) => g.kind === 'fuzzy').length,
    groups: out,
  });
});

// GET /api/duplicates/group?ids=1,2,3 — full rows + owners + links for a group
router.get('/group', async (req, res) => {
  const ids = (req.query.ids || '').split(',').map(Number).filter(Boolean);
  const rows = await getAtlasRowsByIds(ids);
  const enriched = [];
  for (const r of rows) {
    enriched.push({
      ...r,
      _owners: await getSourceOwners(r.atlas_id),
      _sources: await getSourceIds(r.atlas_id),
      _links: await getSourceLinks(r.atlas_id),
    });
  }
  res.json(enriched);
});

// POST /api/duplicates/merge  { survivorId, groupIds: [] }
// Merge duplicate ATLAS rows: relink sources onto survivor, delete losers.
router.post('/merge', async (req, res) => {
  const { survivorId, groupIds } = req.body || {};
  if (!survivorId || !Array.isArray(groupIds) || groupIds.length < 2) {
    return res.status(400).json({ error: 'Choose a row to keep and at least one duplicate.' });
  }
  if (!groupIds.map(Number).includes(Number(survivorId))) {
    return res.status(400).json({ error: 'The row to keep must be part of the group.' });
  }
  const result = await mergeAtlasGroup({ survivorId, groupIds, user: req.user.username });
  res.json(result);
});

// POST /api/duplicates/relink-source
//   { table:'f95_zone'|'lewdcorner', sourceId, action:'float'|'link', atlasId? }
// Relink or float a single SOURCE row. Source is never deleted. If the move
// orphans the previous atlas row, `orphaned` comes back for a delete prompt.
router.post('/relink-source', async (req, res) => {
  const { table, sourceId, action, atlasId } = req.body || {};
  if (!table || !sourceId || !['float', 'link'].includes(action)) {
    return res.status(400).json({ error: 'Provide table, sourceId, and a valid action.' });
  }
  const result = await relinkSource({
    table, sourceId: Number(sourceId), action, atlasId, user: req.user.username,
  });
  res.json(result);
});

// POST /api/duplicates/delete-orphan  { atlasId }
// Delete an atlas row ONLY if it is orphaned (no source references it).
router.post('/delete-orphan', async (req, res) => {
  const { atlasId } = req.body || {};
  if (!atlasId) return res.status(400).json({ error: 'Missing atlasId.' });
  const result = await deleteAtlasIfOrphaned({ atlasId, user: req.user.username });
  res.json(result);
});

export default router;
