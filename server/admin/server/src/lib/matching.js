// ---------------------------------------------------------------------------
// Duplicate-matching logic, ported directly from the Python find_duplicates.py
// so the admin tool surfaces the SAME groups the CLI does. Pure functions, no
// DB access — callers pass in atlas rows.
//
// A "duplicate game" = two or more DISTINCT atlas rows (different atlas_id)
// that are almost certainly the same game. Two detectors:
//   EXACT  — same computed id_name on more than one atlas row.
//   FUZZY  — high normalized title+creator similarity, but id_name differs.
//            Blocked by a short title prefix so it stays fast, and numbered
//            sequels ("Haydee 2" vs "Haydee 3") are excluded.
// ---------------------------------------------------------------------------

// --- normalization ---------------------------------------------------------
export function norm(s) {
  return (s || '').toLowerCase().replace(/[\W_]+/g, '');
}

// Ratio equivalent to Python difflib.SequenceMatcher.ratio() (Gestalt /
// Ratcliff-Obershelp): 2*M / (len(a)+len(b)) where M is the total number of
// matched characters found by recursively matching the longest common
// contiguous block and then the pieces to its left and right.
function matchingBlocks(a, b, alo, ahi, blo, bhi, acc) {
  // find longest matching block in a[alo:ahi], b[blo:bhi]
  let bestI = alo, bestJ = blo, bestSize = 0;
  const b2j = new Map();
  for (let j = blo; j < bhi; j++) {
    const ch = b[j];
    if (!b2j.has(ch)) b2j.set(ch, []);
    b2j.get(ch).push(j);
  }
  let j2len = new Map();
  for (let i = alo; i < ahi; i++) {
    const newj2len = new Map();
    const js = b2j.get(a[i]);
    if (js) {
      for (const j of js) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2len.set(j, k);
        if (k > bestSize) { bestI = i - k + 1; bestJ = j - k + 1; bestSize = k; }
      }
    }
    j2len = newj2len;
  }
  if (bestSize > 0) {
    matchingBlocks(a, b, alo, bestI, blo, bestJ, acc);
    acc.push(bestSize);
    matchingBlocks(a, b, bestI + bestSize, ahi, bestJ + bestSize, bhi, acc);
  }
}

function seqRatio(a, b) {
  if (!a.length && !b.length) return 1.0;
  const acc = [];
  matchingBlocks(a, b, 0, a.length, 0, b.length, acc);
  const matches = acc.reduce((s, n) => s + n, 0);
  return (2.0 * matches) / (a.length + b.length);
}

export function sim(a, b) {
  const na = norm(a), nb = norm(b);
  if (!na || !nb) return 0.0;
  return seqRatio(na, nb);
}

// title+creator similarity, title weighted 0.7; pure title if either creator blank
export function score(a, b) {
  const t = sim(a.title, b.title);
  const ca = a.creator || a.developer;
  const cb = b.creator || b.developer;
  if (!norm(ca) || !norm(cb)) return t;
  return 0.7 * t + 0.3 * sim(ca, cb);
}

// --- sequel detection ------------------------------------------------------
const ROMAN = new Set(['ii', 'iii', 'iv', 'vi', 'vii', 'viii', 'ix', 'xi', 'xii', 'xiii']);

function seqTokens(title) {
  const low = (title || '').toLowerCase();
  const nums = new Set((low.match(/\d+/g) || []));
  const romans = new Set((low.match(/[a-z]+/g) || []).filter((w) => ROMAN.has(w)));
  return new Set([...nums, ...romans]);
}

function setsEqual(x, y) {
  if (x.size !== y.size) return false;
  for (const v of x) if (!y.has(v)) return false;
  return true;
}

export function isSequelPair(a, b) {
  const sa = seqTokens(a.title), sb = seqTokens(b.title);
  if (setsEqual(sa, sb)) return false;
  if (sa.size === 0 && sb.size === 0) return false;
  return true;
}

// --- union-find ------------------------------------------------------------
class UF {
  constructor() { this.parent = new Map(); }
  find(x) {
    if (!this.parent.has(x)) this.parent.set(x, x);
    let root = x;
    while (this.parent.get(root) !== root) root = this.parent.get(root);
    while (this.parent.get(x) !== root) { const nx = this.parent.get(x); this.parent.set(x, root); x = nx; }
    return root;
  }
  union(a, b) { const ra = this.find(a), rb = this.find(b); if (ra !== rb) this.parent.set(rb, ra); }
}

// --- detectors -------------------------------------------------------------
export function findExactGroups(rows) {
  const by = new Map();
  for (const r of rows) {
    const key = (r.id_name || '').trim();
    if (key && key !== '_') {
      if (!by.has(key)) by.set(key, []);
      by.get(key).push(r);
    }
  }
  const groups = [];
  for (const [key, members] of by) {
    const ids = new Set(members.map((m) => m.atlas_id));
    if (ids.size > 1) groups.push({ key, members });
  }
  return groups;
}

export function findFuzzyGroups(rows, floor = 0.90) {
  const buckets = new Map();
  for (const r of rows) {
    const key = norm(r.title).slice(0, 4);
    if (key) { if (!buckets.has(key)) buckets.set(key, []); buckets.get(key).push(r); }
  }
  const rowById = new Map(rows.map((r) => [r.atlas_id, r]));
  const seenPairs = new Set();
  const uf = new UF();

  for (const members of buckets.values()) {
    const n = members.length;
    if (n < 2) continue;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = members[i], b = members[j];
        if (a.atlas_id === b.atlas_id) continue;
        if ((a.id_name || '').trim() === (b.id_name || '').trim()) continue;
        const pair = [a.atlas_id, b.atlas_id].sort((x, y) => x - y).join(',');
        if (seenPairs.has(pair)) continue;
        seenPairs.add(pair);
        if (isSequelPair(a, b)) continue;
        if (score(a, b) >= floor) uf.union(a.atlas_id, b.atlas_id);
      }
    }
  }

  const clusters = new Map();
  for (const aid of uf.parent.keys()) {
    const root = uf.find(aid);
    if (!clusters.has(root)) clusters.set(root, []);
    clusters.get(root).push(aid);
  }
  const groups = [];
  for (const ids of clusters.values()) {
    const uniq = [...new Set(ids)].sort((x, y) => x - y);
    if (uniq.length > 1) groups.push({ key: '(fuzzy)', members: uniq.map((i) => rowById.get(i)) });
  }
  return groups;
}
