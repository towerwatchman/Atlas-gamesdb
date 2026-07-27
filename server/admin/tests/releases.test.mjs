/**
 * Release stats: channel classification, shaping, and caching.
 *
 * No network. GitHub allows 60 unauthenticated requests/hour per IP, which a
 * test suite would burn through immediately (and which is exactly why the page
 * goes through a cached server-side proxy rather than fetching from the
 * browser). `fetch` is stubbed with fixtures instead.
 *
 *   node tests/releases.test.mjs
 */
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const here = dirname(fileURLToPath(import.meta.url));
const libPath = resolve(here, '..', 'server', 'src', 'lib', 'releases.js');

let passed = 0;
const failures = [];
function ok(n) { passed += 1; console.log(`ok    ${n}`); }
function fail(n, e) {
  failures.push(`${n}: ${e?.message || e}`);
  console.log(`FAIL  ${n}: ${e?.message || e}`);
}
async function test(n, fn) { try { await fn(); ok(n); } catch (e) { fail(n, e); } }
function assert(c, m) { if (!c) throw new Error(m || 'assertion failed'); }
function eq(a, b, m) {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${m || 'not equal'}: got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`);
  }
}

const mod = await import(`file://${libPath}`);
const { assetType, isInstaller, channelOf, shapeReleases, getReleases, clearReleaseCache } = mod;

// A payload shaped like the real API, covering the awkward cases.
const FIXTURE = [
  {
    tag_name: 'v1.2.0', name: 'Atlas 1.2.0', prerelease: false, draft: false,
    published_at: '2025-06-01T10:00:00Z', html_url: 'u1',
    assets: [
      { id: 1, name: 'Atlas-1.2.0-win-x64.exe', download_count: 500, size: 10 },
      { id: 2, name: 'atlas_1.2.0_amd64.deb', download_count: 120, size: 10 },
      { id: 3, name: 'Atlas-1.2.0.AppImage', download_count: 60, size: 10 },
      // noise that must never be counted as a download
      { id: 4, name: 'Atlas-1.2.0-win-x64.exe.blockmap', download_count: 9000, size: 1 },
      { id: 5, name: 'latest.yml', download_count: 8000, size: 1 },
      { id: 6, name: 'Atlas-1.2.0.sha512', download_count: 7000, size: 1 },
    ],
  },
  {
    // nightly by flag
    tag_name: 'v1.3.0-build.412', name: 'Build 412', prerelease: true, draft: false,
    published_at: '2025-06-20T10:00:00Z', html_url: 'u2',
    assets: [{ id: 7, name: 'Atlas-1.3.0-win-x64.exe', download_count: 40, size: 10 }],
  },
  {
    // nightly by name, WITHOUT the prerelease flag set
    tag_name: 'nightly', name: 'Nightly build', prerelease: false, draft: false,
    published_at: '2025-06-25T10:00:00Z', html_url: 'u3',
    assets: [{ id: 8, name: 'Atlas-nightly-win-x64.exe', download_count: 300, size: 10 }],
  },
  {
    // drafts are not public and must be dropped
    tag_name: 'v9.9.9', name: 'Draft', prerelease: false, draft: true,
    published_at: null, html_url: 'u4',
    assets: [{ id: 9, name: 'secret.exe', download_count: 1, size: 10 }],
  },
  {
    // an older main release, to check ordering
    tag_name: 'v1.1.0', name: 'Atlas 1.1.0', prerelease: false, draft: false,
    published_at: '2025-01-01T10:00:00Z', html_url: 'u5',
    assets: [{ id: 10, name: 'Atlas-1.1.0-win-x64.exe', download_count: 1000, size: 10 }],
  },
];

// ------------------------------------------------------------------ helpers
await test('assetType reads the extension, ignoring version numbers', () => {
  eq(assetType('Atlas-1.2.0-win-x64.exe'), 'exe');
  eq(assetType('atlas_1.2.0_amd64.deb'), 'deb');
  eq(assetType('Atlas-1.2.0.AppImage'), 'appimage', 'lowercased');
  eq(assetType('Atlas.tar.gz'), 'gz');
  eq(assetType('NOEXTENSION'), 'other');
  eq(assetType(''), 'other');
  eq(assetType(undefined), 'other');
});

await test('checksums and update metadata are not installers', () => {
  for (const n of ['x.blockmap', 'latest.yml', 'latest.yaml', 'a.sha256', 'a.sha512',
                   'a.sig', 'a.asc', 'meta.json']) {
    eq(isInstaller(n), false, n);
  }
  for (const n of ['a.exe', 'a.deb', 'a.AppImage', 'a.pacman', 'a.dmg', 'a.zip']) {
    eq(isInstaller(n), true, n);
  }
});

// ----------------------------------------------------------------- channels
await test('the prerelease flag means nightly', () => {
  eq(channelOf({ tag_name: 'v1.3.0', prerelease: true }), 'nightly');
});

await test('a tag or name saying nightly means nightly even without the flag', () => {
  eq(channelOf({ tag_name: 'nightly', prerelease: false }), 'nightly');
  eq(channelOf({ tag_name: 'nightly-2025-06-25', prerelease: false }), 'nightly');
  eq(channelOf({ tag_name: 'v1.3.0', name: 'Nightly build', prerelease: false }), 'nightly');
});

await test('a plain tagged release is main', () => {
  eq(channelOf({ tag_name: 'v1.2.0', name: 'Atlas 1.2.0', prerelease: false }), 'main');
  eq(channelOf({ tag_name: '1.2.0', prerelease: false }), 'main');
});

await test('channelOf survives a junk release object', () => {
  eq(channelOf({}), 'main');
  eq(channelOf(null), 'main');
});

// ------------------------------------------------------------------ shaping
await test('shaping drops drafts and non-installer assets', () => {
  const out = shapeReleases(FIXTURE);
  eq(out.releases.length, 4, 'the draft must be dropped');
  assert(!out.releases.some((r) => r.tag === 'v9.9.9'), 'draft leaked');
  const v120 = out.releases.find((r) => r.tag === 'v1.2.0');
  eq(v120.assets.length, 3, 'only the three installers');
  eq(v120.total, 680, '500 + 120 + 60, excluding the 24000 of checksum noise');
});

await test('releases come back newest first', () => {
  const tags = shapeReleases(FIXTURE).releases.map((r) => r.tag);
  eq(tags, ['nightly', 'v1.3.0-build.412', 'v1.2.0', 'v1.1.0']);
});

await test('per-channel totals are separated', () => {
  const out = shapeReleases(FIXTURE);
  eq(out.by_channel.main.releases, 2, 'v1.2.0 and v1.1.0');
  eq(out.by_channel.main.downloads, 1680, '680 + 1000');
  eq(out.by_channel.main.latest, 'v1.2.0', 'newest main');
  eq(out.by_channel.nightly.releases, 2, 'the flagged one and the named one');
  eq(out.by_channel.nightly.downloads, 340, '40 + 300');
  eq(out.by_channel.nightly.latest, 'nightly');
  eq(out.total_downloads, 2020, 'everything');
});

await test('asset types are collected for the dropdown', () => {
  eq(shapeReleases(FIXTURE).types, ['appimage', 'deb', 'exe']);
});

await test('assets within a release are ordered by downloads', () => {
  const v120 = shapeReleases(FIXTURE).releases.find((r) => r.tag === 'v1.2.0');
  eq(v120.assets.map((a) => a.downloads), [500, 120, 60]);
});

await test('shaping tolerates an empty or junk payload', () => {
  for (const input of [[], null, undefined, {}, 'nope']) {
    const out = shapeReleases(input);
    eq(out.releases, [], JSON.stringify(input));
    eq(out.total_downloads, 0);
    eq(out.by_channel.main.latest, null);
  }
});

await test('a release with no installer assets still appears with zero', () => {
  const out = shapeReleases([{
    tag_name: 'v0.1', prerelease: false, draft: false,
    published_at: '2025-01-01T00:00:00Z',
    assets: [{ id: 1, name: 'only.yml', download_count: 5 }],
  }]);
  eq(out.releases.length, 1, 'kept, so the page can show it exists');
  eq(out.releases[0].total, 0, 'but nothing counted');
  eq(out.releases[0].assets, []);
});

await test('an unpublished release sorts last instead of crashing', () => {
  const out = shapeReleases([
    { tag_name: 'no-date', prerelease: false, draft: false, published_at: null, assets: [] },
    { tag_name: 'dated', prerelease: false, draft: false, published_at: '2025-01-01T00:00:00Z', assets: [] },
  ]);
  eq(out.releases.map((r) => r.tag), ['dated', 'no-date']);
});

// ------------------------------------------------------------------ caching
const realFetch = globalThis.fetch;
function stubFetch(handler) { globalThis.fetch = handler; }
function restoreFetch() { globalThis.fetch = realFetch; }

function jsonRes(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

await test('a second call inside the TTL does not hit GitHub again', async () => {
  clearReleaseCache();
  let calls = 0;
  stubFetch(async () => { calls += 1; return jsonRes(FIXTURE); });
  try {
    const a = await getReleases();
    const b = await getReleases();
    eq(calls, 1, 'only one upstream request');
    eq(a.total_downloads, b.total_downloads, 'same payload');
    eq(b.stale, false, 'not stale');
    assert(b.cached_at, 'cached_at reported');
  } finally { restoreFetch(); }
});

await test('force bypasses the cache', async () => {
  clearReleaseCache();
  let calls = 0;
  stubFetch(async () => { calls += 1; return jsonRes(FIXTURE); });
  try {
    await getReleases();
    await getReleases({ force: true });
    eq(calls, 2, 'the Refresh button must actually refetch');
  } finally { restoreFetch(); }
});

await test('a rate limit serves the last good copy rather than blanking', async () => {
  clearReleaseCache();
  let calls = 0;
  stubFetch(async () => {
    calls += 1;
    if (calls === 1) return jsonRes(FIXTURE);
    return jsonRes({ message: 'API rate limit exceeded for 1.2.3.4.' }, 403);
  });
  try {
    const good = await getReleases();
    eq(good.stale, false, 'first call is fresh');
    const stale = await getReleases({ force: true });
    eq(stale.stale, true, 'flagged as stale');
    eq(stale.total_downloads, good.total_downloads, 'still has the figures');
    assert(/rate limit/i.test(stale.error), stale.error);
    assert(/GITHUB_TOKEN/.test(stale.error), 'should say how to raise the limit');
  } finally { restoreFetch(); }
});

await test('a failure with nothing cached throws', async () => {
  clearReleaseCache();
  stubFetch(async () => jsonRes({ message: 'Not Found' }, 404));
  try {
    let threw = false;
    try { await getReleases(); } catch (e) { threw = true; eq(e.status, 404, 'status'); }
    assert(threw, 'should surface the error when there is nothing to serve');
  } finally { restoreFetch(); }
});

await test('pagination stops on a short page', async () => {
  clearReleaseCache();
  const pages = [];
  stubFetch(async (url) => {
    pages.push(new URL(url).searchParams.get('page'));
    // 100 on page 1 forces a second request; 1 on page 2 ends it.
    return jsonRes(pages.length === 1
      ? Array.from({ length: 100 }, (_, i) => ({
        tag_name: `v0.0.${i}`, prerelease: false, draft: false,
        published_at: '2025-01-01T00:00:00Z', assets: [],
      }))
      : [FIXTURE[0]]);
  });
  try {
    const out = await getReleases();
    eq(pages, ['1', '2'], 'followed to page 2 then stopped');
    eq(out.releases.length, 101, 'both pages kept');
  } finally { restoreFetch(); }
});

console.log(`\n${passed}/${passed + failures.length} passed`);
if (failures.length) {
  console.log('\nfailures:');
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
