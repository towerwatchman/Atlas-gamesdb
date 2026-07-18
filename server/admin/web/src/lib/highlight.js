// ---------------------------------------------------------------------------
// Local, browser-only match highlighting for the review queue (requirement 2).
// Given a target string (a candidate's title/creator/version) and a reference
// string (the queued item's equivalent field), it returns segments marking the
// parts of the target that overlap the reference, so the UI can <mark> them.
//
// Strategy: normalise, then find the longest common substrings greedily. This
// catches full matches ("Corrupted Kingdoms") and partial ones ("Corrupted"
// inside "Corrupted Kingdoms Remake") without any server round-trip.
// ---------------------------------------------------------------------------

const MIN_RUN = 3; // ignore trivially short overlaps (spaces, "a", "of", …)

function norm(s) {
  return (s ?? '').toString().toLowerCase();
}

// Longest common substring between two strings -> {start, len} in `a`, or null.
function longestCommon(a, b) {
  if (!a || !b) return null;
  const m = a.length;
  const n = b.length;
  let best = 0;
  let bestEnd = 0;
  // rolling 1-D DP over b to keep it light for short game titles
  let prev = new Array(n + 1).fill(0);
  for (let i = 1; i <= m; i++) {
    const cur = new Array(n + 1).fill(0);
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        cur[j] = prev[j - 1] + 1;
        if (cur[j] > best) { best = cur[j]; bestEnd = i; }
      }
    }
    prev = cur;
  }
  if (best < MIN_RUN) return null;
  return { start: bestEnd - best, len: best };
}

/**
 * Split `target` into segments: [{ text, match: boolean }, ...].
 * Matching is computed against the lowercased forms but slices come from the
 * original `target` so display casing is preserved.
 */
export function highlightSegments(target, reference) {
  const t = (target ?? '').toString();
  if (!t) return [{ text: '', match: false }];
  const ref = norm(reference);
  if (!ref) return [{ text: t, match: false }];

  const lowerT = norm(t);
  // Collect non-overlapping matched ranges by repeatedly pulling the longest
  // common substring and masking it out of the reference-search each pass.
  const ranges = [];
  let remainingRef = ref;
  // A few passes are enough for game metadata; cap to avoid pathological loops.
  for (let pass = 0; pass < 6 && remainingRef.length >= MIN_RUN; pass++) {
    const hit = longestCommon(lowerT, remainingRef);
    if (!hit) break;
    const slice = lowerT.slice(hit.start, hit.start + hit.len);
    // record every occurrence of this slice in the target
    let idx = lowerT.indexOf(slice);
    while (idx !== -1) {
      ranges.push([idx, idx + slice.length]);
      idx = lowerT.indexOf(slice, idx + 1);
    }
    // remove the slice from the reference pool so later passes find new overlap
    remainingRef = remainingRef.split(slice).join(' ');
  }

  if (!ranges.length) return [{ text: t, match: false }];

  // merge overlapping/adjacent ranges
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [ranges[0].slice()];
  for (let i = 1; i < ranges.length; i++) {
    const last = merged[merged.length - 1];
    if (ranges[i][0] <= last[1]) last[1] = Math.max(last[1], ranges[i][1]);
    else merged.push(ranges[i].slice());
  }

  const segs = [];
  let cursor = 0;
  for (const [s, e] of merged) {
    if (s > cursor) segs.push({ text: t.slice(cursor, s), match: false });
    segs.push({ text: t.slice(s, e), match: true });
    cursor = e;
  }
  if (cursor < t.length) segs.push({ text: t.slice(cursor), match: false });
  return segs;
}
