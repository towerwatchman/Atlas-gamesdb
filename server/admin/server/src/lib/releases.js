// ---------------------------------------------------------------------------
// GitHub release download stats, proxied and cached.
//
// Fetched server-side rather than from the browser for three reasons:
//   * Unauthenticated GitHub allows 60 requests/hour PER IP. Every admin with
//     the page open burns that shared budget, and once it's gone the page just
//     breaks. One cached server-side fetch serves everyone.
//   * A GITHUB_TOKEN in .env raises the limit to 5000/hour without shipping the
//     token to the browser.
//   * The channel classification lives in one place and is testable.
//
// On a fetch failure the last good payload is served with `stale: true` rather
// than erroring, so a rate-limit blip doesn't blank the page.
// ---------------------------------------------------------------------------

const REPO = process.env.GITHUB_REPO || 'towerwatchman/Atlas';
const TTL_MS = Number(process.env.RELEASES_CACHE_SECONDS || 600) * 1000;
const MAX_PAGES = 5;   // 500 releases; well past what this repo has

// Update metadata and checksums, not things a human downloads.
const HIDDEN_EXTENSIONS = new Set([
  'blockmap', 'yml', 'yaml', 'sha256', 'sha512', 'sig', 'asc', 'json',
]);

export const CHANNELS = ['main', 'nightly'];

/** Extension of an asset filename, lowercased. 'other' when there isn't one. */
export function assetType(name) {
  const m = String(name || '').toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? m[1] : 'other';
}

export function isInstaller(name) {
  return !HIDDEN_EXTENSIONS.has(assetType(name));
}

/**
 * Which channel a release belongs to.
 *
 * GitHub has no notion of a channel, so it is inferred: the `prerelease` flag
 * first, then the tag/name for the word "nightly" (a nightly published without
 * the flag set is still a nightly). Everything else is main.
 *
 * The classification is returned per release so the UI can show it — if this
 * guesses wrong for a given tag, it's visible rather than silently miscounted.
 */
export function channelOf(release) {
  const tag = String(release?.tag_name || '').toLowerCase();
  const name = String(release?.name || '').toLowerCase();
  if (/nightly|nightlies/.test(tag) || /nightly/.test(name)) return 'nightly';
  if (release?.prerelease) return 'nightly';
  return 'main';
}

// --- fetching --------------------------------------------------------------

let cache = { at: 0, payload: null };

function ghHeaders() {
  const headers = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'atlas-admin',
  };
  const token = process.env.GITHUB_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function fetchAllReleases() {
  const out = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const url = `https://api.github.com/repos/${REPO}/releases?per_page=100&page=${page}`;
    const res = await fetch(url, { headers: ghHeaders() });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      const err = new Error(
        res.status === 403 && /rate limit/i.test(body)
          ? 'GitHub API rate limit reached. Set GITHUB_TOKEN in server/.env to raise it.'
          : `GitHub API returned ${res.status}`);
      err.status = res.status === 404 ? 404 : 502;
      throw err;
    }
    const batch = await res.json();
    if (!Array.isArray(batch) || batch.length === 0) break;
    out.push(...batch);
    if (batch.length < 100) break;
  }
  return out;
}

/** Reshape the GitHub payload into what the page needs. */
export function shapeReleases(raw) {
  const releases = (Array.isArray(raw) ? raw : [])
    .filter((r) => !r.draft)
    .map((r) => {
      const assets = (r.assets || [])
        .filter((a) => isInstaller(a.name))
        .map((a) => ({
          id: a.id,
          name: a.name,
          type: assetType(a.name),
          downloads: a.download_count || 0,
          size: a.size || 0,
        }))
        .sort((a, b) => b.downloads - a.downloads);
      return {
        tag: r.tag_name,
        name: r.name || r.tag_name,
        channel: channelOf(r),
        prerelease: Boolean(r.prerelease),
        published_at: r.published_at,
        url: r.html_url,
        assets,
        total: assets.reduce((s, a) => s + a.downloads, 0),
      };
    });

  // Newest first. published_at can be null for an unpublished tag, so those
  // sort last rather than crashing the comparator.
  releases.sort((a, b) => {
    const at = a.published_at ? Date.parse(a.published_at) : 0;
    const bt = b.published_at ? Date.parse(b.published_at) : 0;
    return bt - at;
  });

  const types = [...new Set(releases.flatMap((r) => r.assets.map((a) => a.type)))].sort();
  const byChannel = {};
  for (const channel of CHANNELS) {
    const subset = releases.filter((r) => r.channel === channel);
    byChannel[channel] = {
      releases: subset.length,
      downloads: subset.reduce((s, r) => s + r.total, 0),
      latest: subset[0]?.tag ?? null,
    };
  }

  return {
    repo: REPO,
    releases,
    types,
    channels: CHANNELS,
    by_channel: byChannel,
    total_downloads: releases.reduce((s, r) => s + r.total, 0),
  };
}

/** Cached release stats. `force` bypasses the cache (the Refresh button). */
export async function getReleases({ force = false } = {}) {
  const fresh = cache.payload && (Date.now() - cache.at) < TTL_MS;
  if (fresh && !force) {
    return { ...cache.payload, cached_at: cache.at, stale: false };
  }
  try {
    const payload = shapeReleases(await fetchAllReleases());
    cache = { at: Date.now(), payload };
    return { ...payload, cached_at: cache.at, stale: false };
  } catch (err) {
    // Serve the last good copy rather than blanking the page on a rate-limit
    // blip; the UI shows how old it is.
    if (cache.payload) {
      return {
        ...cache.payload, cached_at: cache.at, stale: true, error: err.message,
      };
    }
    throw err;
  }
}

/** Test seam: drop the cache. */
export function clearReleaseCache() {
  cache = { at: 0, payload: null };
}
