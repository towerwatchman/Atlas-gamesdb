/**
 * Integration tests for the admin API against a REAL database.
 *
 * These cover the nine features added for issues #287 #286 #285 #281 #278 #276
 * #271 plus manual game creation, and they hit the running HTTP server rather
 * than calling the lib functions directly, so route wiring, auth and JSON
 * shapes are all exercised.
 *
 *   node tests/api.test.mjs
 *
 * Environment:
 *   API_BASE        default http://127.0.0.1:8788
 *   ADMIN_USER      default tester
 *   ADMIN_PASSWORD  default testpass123
 *
 * The database must already have the schema (sql/001..006) applied and a seeded
 * admin. The suite creates and cleans up its own atlas rows, but it does assume
 * it can write — point it at a scratch database, never production.
 */
const BASE = process.env.API_BASE || 'http://127.0.0.1:8788';
const USER = process.env.ADMIN_USER || 'tester';
const PASS = process.env.ADMIN_PASSWORD || 'testpass123';

let cookie = '';
let passed = 0;
const failures = [];

function ok(name) { passed += 1; console.log(`ok    ${name}`); }
function fail(name, err) {
  failures.push(`${name}: ${err && err.message ? err.message : err}`);
  console.log(`FAIL  ${name}: ${err && err.message ? err.message : err}`);
}
async function test(name, fn) {
  try { await fn(); ok(name); } catch (err) { fail(name, err); }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }
function eq(a, b, msg) {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${msg || 'not equal'}: got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`);
  }
}

async function api(path, { method = 'GET', body, raw = false } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(cookie ? { Cookie: cookie } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (raw) return res;
  let json = null;
  const text = await res.text();
  try { json = text ? JSON.parse(text) : null; } catch { json = { _raw: text }; }
  return { status: res.status, json, res };
}

// ---------------------------------------------------------------- auth (#281)
async function login() {
  const res = await fetch(`${BASE}/admin/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  const setCookie = res.headers.get('set-cookie');
  assert(res.ok, `login failed: ${res.status} ${await res.text()}`);
  assert(setCookie, 'no Set-Cookie on login');
  cookie = setCookie.split(';')[0];
  return setCookie;
}

async function main() {
  const setCookie = await login();
  console.log(`logged in as ${USER}\n`);

  await test('#281 session cookie lasts a week', async () => {
    const m = /Max-Age=(\d+)/i.exec(setCookie);
    assert(m, `no Max-Age in cookie: ${setCookie}`);
    const days = Number(m[1]) / 86400;
    assert(days >= 6.9 && days <= 7.1, `cookie lasts ${days.toFixed(2)} days, want ~7`);
  });

  // -------------------------------------------------------- search (#287)
  await test('#287 exact title ranks first', async () => {
    const { json } = await api('/admin/api/atlas?search=Eternum');
    assert(json.rows.length >= 2, 'expected Eternum and the fan remake');
    eq(json.rows[0].title, 'Eternum', 'top hit');
  });

  await test('#287 multi-word query narrows instead of widening', async () => {
    const one = await api('/admin/api/atlas?search=dik');
    const two = await api('/admin/api/atlas?search=being%20dik');
    assert(one.json.total >= 2,
      `"dik" should match several rows, got ${one.json.total}`);
    eq(two.json.total, 1, '"being dik" should match exactly one');
    eq(two.json.rows[0].title, 'Being a DIK', 'multi-term hit');
  });

  await test('#287 every term must match something', async () => {
    const { json } = await api('/admin/api/atlas?search=eternum%20nonexistentword');
    eq(json.total, 0, 'an unmatched term must exclude the row');
  });

  await test('#287 numeric query finds by atlas_id', async () => {
    const { json } = await api('/admin/api/atlas?search=2');
    assert(json.rows.length, 'no rows');
    eq(json.rows[0].atlas_id, 2, 'atlas_id 2 should rank first for "2"');
  });

  await test('#287 numeric query finds by f95_id', async () => {
    const { json } = await api('/admin/api/atlas?search=93340');
    assert(json.rows.length, 'no rows for f95 id');
    eq(json.rows[0].f95_id, 93340, 'f95_id lookup');
  });

  await test('#287 numeric query finds by lc_id', async () => {
    const { json } = await api('/admin/api/atlas?search=555');
    assert(json.rows.length, 'no rows for lc id');
    eq(json.rows[0].lc_id, 555, 'lc_id lookup');
  });

  await test('#287 LIKE wildcards are escaped', async () => {
    // "%" used to match the entire table.
    const pct = await api('/admin/api/atlas?search=%25');
    assert(pct.json.total <= 1,
      `"%" matched ${pct.json.total} rows; wildcards are not escaped`);
    // ...and a title genuinely containing "100%" is findable.
    const real = await api('/admin/api/atlas?search=100%25');
    eq(real.json.rows[0]?.title, '100% Completion', 'literal % search');
  });

  await test('#287 underscore is escaped too', async () => {
    // A bare "_" is a poor probe: every id_name contains a literal underscore
    // by construction (short_name + "_" + CREATOR), so matching every row is
    // correct. "E_ernum" only matches Eternum if "_" is a live wildcard.
    const { json } = await api('/admin/api/atlas?search=E_ernum');
    assert(json.total === 0,
      `"E_ernum" matched ${json.total} rows; "_" is being treated as a wildcard`);
    const literal = await api('/admin/api/atlas?search=ETERNUM_CARIBDIS');
    eq(literal.json.rows[0]?.atlas_id, 2, 'a literal underscore must still match');
  });

  await test('#287 shorter title wins at equal relevance', async () => {
    const { json } = await api('/admin/api/atlas?search=eternum');
    eq(json.rows[0].title, 'Eternum', 'short exact title should outrank the long fan remake');
  });

  await test('#287 count matches the filtered rows', async () => {
    const { json } = await api('/admin/api/atlas?search=eternum&limit=1');
    eq(json.rows.length, 1, 'limit respected');
    assert(json.total >= 2, `total should count all matches, got ${json.total}`);
  });

  await test('#287 empty search still lists everything by id', async () => {
    const { json } = await api('/admin/api/atlas');
    assert(json.total >= 6, `expected the whole table, got ${json.total}`);
    eq(json.rows[0].atlas_id, 1, 'unsearched listing stays in id order');
  });

  // ------------------------------------------------- create a game (#1)
  let newId = null;
  await test('#1 identity preview computes the scraper-compatible key', async () => {
    const { json } = await api('/admin/api/atlas/preview-identity?title=Brand%20New%20Game&creator=SomeDev');
    eq(json.id_name, 'BRANDNEWGAME_SOMEDEV', 'id_name');
    eq(json.short_name, 'BRANDNEWGAME', 'short_name');
    eq(json.clash, null, 'should not clash');
  });

  await test('#1 create assigns an atlas_id', async () => {
    const { status, json } = await api('/admin/api/atlas', {
      method: 'POST',
      body: { fields: { title: 'Brand New Game', creator: 'SomeDev', version: '0.1', engine: 'Ren\'Py' } },
    });
    eq(status, 201, 'status');
    assert(Number.isInteger(json.atlas_id) && json.atlas_id > 0, `bad atlas_id: ${json.atlas_id}`);
    eq(json.id_name, 'BRANDNEWGAME_SOMEDEV', 'derived id_name');
    newId = json.atlas_id;
  });

  await test('#1 created row is readable and marked as human-edited', async () => {
    const { json } = await api(`/admin/api/atlas/${newId}`);
    eq(json.title, 'Brand New Game', 'title');
    eq(json.version, '0.1', 'version');
    eq(json.edited, 1, 'edited flag');
    eq(json.edited_by, USER, 'edited_by');
    assert(json.last_record_update > 0, 'last_record_update must be set so it exports');
  });

  await test('#1 create refuses a duplicate identity key', async () => {
    const { status, json } = await api('/admin/api/atlas', {
      method: 'POST',
      body: { fields: { title: 'Brand New Game', creator: 'SomeDev' } },
    });
    eq(status, 409, 'status');
    eq(json.atlasId, newId, 'should point at the existing row');
    assert(/already exists/i.test(json.error), json.error);
  });

  await test('#1 create requires a title', async () => {
    const { status } = await api('/admin/api/atlas', { method: 'POST', body: { fields: { creator: 'x' } } });
    eq(status, 400, 'status');
  });

  await test('#1 create is audited', async () => {
    const { json } = await api(`/admin/api/atlas/${newId}/audit`);
    const verbs = json.map((r) => r.field);
    assert(verbs.includes('atlas.create'), `no atlas.create in ${verbs.join(',')}`);
    assert(verbs.includes('atlas.version'), 'per-field audit rows missing');
  });

  // ------------------------------------- mapped source panel (#286)
  await test('#286 source detail returns full rows per mapped source', async () => {
    const { json } = await api('/admin/api/atlas/2');
    const detail = json._source_detail;
    assert(Array.isArray(detail), 'no _source_detail');
    eq(detail.length, 2, 'Eternum has an F95 and an LC mapping');
    const sources = detail.map((d) => d.source).sort();
    eq(sources, ['f95_zone', 'lewdcorner'], 'sources');
    const f95 = detail.find((d) => d.source === 'f95_zone');
    eq(f95.id, '93340', 'f95 id');
    eq(f95.source_label, 'F95zone', 'label for the switcher');
    assert(f95.fields.some((f) => f.field === 'rating'), 'fields should carry real columns');
    assert(f95.site_url.includes('f95zone.to'), 'site_url');
  });

  await test('#286 single-source game returns one entry', async () => {
    const { json } = await api('/admin/api/atlas/1');
    eq(json._source_detail.length, 1, 'Being a DIK has only F95');
    eq(json._source_detail[0].source, 'f95_zone', 'source');
  });

  await test('#286 hand-created game has no mappings', async () => {
    const { json } = await api(`/admin/api/atlas/${newId}`);
    eq(json._source_detail, [], 'should be empty, not null');
  });

  // ------------------------- links: favicon, type, label, parent (#285/#278)
  let steamLink = null;
  let dlcLink = null;
  await test('#285/#278 add a labelled store link', async () => {
    const { status, json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: { kind: 'steam', extId: '1126320', label: 'Base game', entryType: 'game' },
    });
    eq(status, 201, 'status');
    eq(json.label, 'Base game', 'label persisted');
    eq(json.entry_type, 'game', 'entry_type');
    eq(json._store, true, 'store kind flag');
    eq(json._favicon_host, 'store.steampowered.com', 'favicon host');
    assert(json.url.includes('store.steampowered.com/app/1126320'), 'canonical url');
    steamLink = json.link_id;
  });

  await test('#285 favicon host comes from the url for custom links', async () => {
    const { json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: { kind: 'custom', label: 'Dev blog', url: 'https://blog.example.com/posts' },
    });
    eq(json._favicon_host, 'blog.example.com', 'host from url');
    eq(json._store, false, 'custom is not a store kind');
    eq(json.entry_type, 'game', 'plain pages are never DLC');
  });

  await test('#278 DLC can hang off a manual store link', async () => {
    const { status, json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: {
        kind: 'steam', extId: '1126321', label: 'Season 2 DLC',
        entryType: 'dlc', parentKind: 'manual', parentLinkId: steamLink,
      },
    });
    eq(status, 201, 'status');
    eq(json.entry_type, 'dlc', 'entry_type');
    eq(json.parent_kind, 'manual', 'parent_kind');
    eq(json.parent_link_id, steamLink, 'parent_link_id');
    dlcLink = json.link_id;
  });

  await test('#278 DLC can hang off an F95 source mapping', async () => {
    const { status, json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: {
        kind: 'gog', extId: 'eternum_dlc', label: 'Artbook',
        entryType: 'dlc', parentKind: 'f95_zone', parentSourceId: '93340',
      },
    });
    eq(status, 201, 'status');
    eq(json.parent_kind, 'f95_zone', 'parent_kind');
    eq(json.parent_source_id, '93340', 'parent_source_id');
  });

  await test('#278 refuses a source parent that is not mapped to this game', async () => {
    const { status, json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: {
        kind: 'steam', extId: '999', entryType: 'dlc',
        parentKind: 'f95_zone', parentSourceId: '11111', // belongs to atlas 1
      },
    });
    eq(status, 400, 'status');
    assert(/not mapped/i.test(json.error), json.error);
  });

  await test('#278 refuses a parent link from another game', async () => {
    const { status, json } = await api('/admin/api/atlas/1/manual-links', {
      method: 'POST',
      body: {
        kind: 'steam', extId: '4242', entryType: 'dlc',
        parentKind: 'manual', parentLinkId: steamLink, // belongs to atlas 2
      },
    });
    eq(status, 400, 'status');
    assert(/different game/i.test(json.error), json.error);
  });

  await test('#278 refuses DLC chained off DLC', async () => {
    const { status, json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: {
        kind: 'steam', extId: '7777', entryType: 'dlc',
        parentKind: 'manual', parentLinkId: dlcLink,
      },
    });
    eq(status, 400, 'status');
    assert(/cannot be the parent/i.test(json.error), json.error);
  });

  await test('#278 refuses a parent on a non-DLC entry', async () => {
    const { status, json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: {
        kind: 'steam', extId: '8888', entryType: 'game',
        parentKind: 'manual', parentLinkId: steamLink,
      },
    });
    eq(status, 400, 'status');
    assert(/only a dlc/i.test(json.error), json.error);
  });

  await test('#278 DLC with no parent is allowed', async () => {
    const { status, json } = await api('/admin/api/atlas/2/manual-links', {
      method: 'POST',
      body: { kind: 'itch', url: 'https://dev.itch.io/orphan-dlc', entryType: 'dlc' },
    });
    eq(status, 201, 'status');
    eq(json.entry_type, 'dlc', 'entry_type');
    eq(json.parent_kind, null, 'unparented');
  });

  await test('#278 update changes label and re-ties the parent', async () => {
    const { status, json } = await api(`/admin/api/atlas/2/manual-links/${dlcLink}`, {
      method: 'PATCH',
      body: { label: 'Season 2 (renamed)', parentKind: 'f95_zone', parentSourceId: '93340' },
    });
    eq(status, 200, 'status');
    eq(json.label, 'Season 2 (renamed)', 'label');
    eq(json.parent_kind, 'f95_zone', 'parent re-tied');
    eq(json.parent_link_id, null, 'old manual parent cleared');
  });

  await test('#278 cannot demote a base entry that has DLC', async () => {
    // Re-tie the DLC back onto the steam link first.
    await api(`/admin/api/atlas/2/manual-links/${dlcLink}`, {
      method: 'PATCH',
      body: { parentKind: 'manual', parentLinkId: steamLink },
    });
    const { status, json } = await api(`/admin/api/atlas/2/manual-links/${steamLink}`, {
      method: 'PATCH', body: { entryType: 'dlc' },
    });
    eq(status, 400, 'status');
    assert(/hang off this link/i.test(json.error), json.error);
  });

  await test('#278 parent options list manual games and source mappings', async () => {
    const { json } = await api('/admin/api/atlas/2/manual-links/parent-options');
    assert(json.manual.some((m) => m.link_id === steamLink), 'steam link missing');
    assert(!json.manual.some((m) => m.link_id === dlcLink), 'a DLC must not be offered as a parent');
    const kinds = json.sources.map((s) => s.parent_kind).sort();
    eq(kinds, ['f95_zone', 'lewdcorner'], 'source parents');
  });

  await test('#278 deleting a parent orphans its DLC rather than deleting them', async () => {
    const { json } = await api(`/admin/api/atlas/2/manual-links/${steamLink}`, { method: 'DELETE' });
    assert(json.orphaned >= 1, `expected orphan count, got ${json.orphaned}`);
    const after = await api('/admin/api/atlas/2/manual-links');
    const dlc = after.json.find((l) => l.link_id === dlcLink);
    assert(dlc, 'the DLC row was deleted along with its parent');
    eq(dlc.parent_link_id, null, 'parent cleared');
  });

  await test('#285 link kinds metadata exposes store kinds and entry types', async () => {
    const { json } = await api('/admin/api/atlas/meta/manual-link-kinds');
    eq(json.storeKinds, ['steam', 'gog', 'itch'], 'storeKinds');
    eq(json.entryTypes, ['game', 'dlc'], 'entryTypes');
    assert(json.parentKinds.includes('f95_zone'), 'parentKinds');
  });

  // ------------------------------------------- queue manual mapping (#276)
  await test('#276 atlas lookup returns the row for a valid id', async () => {
    const { status, json } = await api('/admin/api/queue/atlas-lookup/1');
    eq(status, 200, 'status');
    eq(json.title, 'Being a DIK', 'title');
    eq(json._has_lc, false, 'no LC mapping yet');
    assert(json._owners.includes('f95_zone'), 'owners');
  });

  await test('#276 atlas lookup flags a row that already has an LC mapping', async () => {
    const { json } = await api('/admin/api/queue/atlas-lookup/2');
    eq(json._has_lc, true, 'Eternum already owns lc 555');
  });

  await test('#276 atlas lookup 404s on a missing id', async () => {
    const { status } = await api('/admin/api/queue/atlas-lookup/999999');
    eq(status, 404, 'status');
  });

  await test('#276 atlas lookup rejects rubbish', async () => {
    const { status } = await api('/admin/api/queue/atlas-lookup/abc');
    eq(status, 400, 'status');
  });

  // -------------------------------------------- admin activity (#271)
  await test('#271 activity groups by admin and category', async () => {
    const { status, json } = await api('/admin/api/admin-activity?days=all');
    eq(status, 200, 'status');
    const me = json.admins.find((a) => a.admin_user === USER);
    assert(me, `no row for ${USER} in ${JSON.stringify(json.admins.map((a) => a.admin_user))}`);
    assert(me.counts.addition >= 1, `expected an addition, got ${me.counts.addition}`);
    assert(me.counts.link >= 1, `expected link actions, got ${me.counts.link}`);
    assert(me.counts.edit >= 1, `expected edits, got ${me.counts.edit}`);
    assert(me.total > 0, 'total');
  });

  await test('#271 auth events are counted but excluded from the work total', async () => {
    const { json } = await api('/admin/api/admin-activity?days=all');
    const me = json.admins.find((a) => a.admin_user === USER);
    assert(me.counts.auth >= 1, 'login should be recorded');
    eq(me.total, me.total_with_auth - me.counts.auth,
      'total must exclude auth events');
  });

  await test('#271 category mapping separates create/delete from field edits', async () => {
    const { json } = await api('/admin/api/admin-activity?days=all');
    const me = json.admins.find((a) => a.admin_user === USER);
    // atlas.create -> addition, atlas.<field> -> edit. If the generic 'atlas.'
    // rule won, addition would be 0 and everything would land in edit.
    assert(me.counts.addition >= 1, 'atlas.create must map to addition, not edit');
  });

  await test('#271 timeline returns per-day buckets', async () => {
    const { status, json } = await api('/admin/api/admin-activity/timeline?days=7');
    eq(status, 200, 'status');
    assert(Array.isArray(json), 'expected an array');
    assert(json.length >= 1, 'expected at least one bucket');
    assert('day' in json[0] && 'category' in json[0] && 'n' in json[0], 'bucket shape');
  });

  await test('#271 per-admin drilldown lists recent actions', async () => {
    const { status, json } = await api(`/admin/api/admin-activity/${USER}/recent?limit=5`);
    eq(status, 200, 'status');
    assert(json.length >= 1, 'expected recent rows');
    assert(json[0].category, 'each row should carry its category');
    assert('field' in json[0], 'row shape');
  });

  await test('#271 window filter narrows the range', async () => {
    const wide = await api('/admin/api/admin-activity?days=all');
    const narrow = await api('/admin/api/admin-activity?since=9999999999');
    assert(wide.json.grand_total >= 1, 'wide window should see work');
    eq(narrow.json.grand_total, 0, 'a future window should be empty');
  });

  await test('#271 users list feeds the filter dropdown', async () => {
    const { json } = await api('/admin/api/admin-activity?days=all');
    assert(json.users.includes(USER), 'users');
    assert(json.bounds.n >= 1, 'bounds');
  });

  // --------------------------------------------------------- auth guard
  await test('endpoints still require auth', async () => {
    const saved = cookie;
    cookie = '';
    const a = await api('/admin/api/admin-activity');
    const b = await api('/admin/api/atlas', { method: 'POST', body: { fields: { title: 'x' } } });
    cookie = saved;
    eq(a.status, 401, 'activity without cookie');
    eq(b.status, 401, 'create without cookie');
  });

  // ------------------------------------------------------------- cleanup
  console.log('\ncleaning up test rows...');
  if (newId) {
    // Leave the audit rows: they're the point of #271, and deleting the atlas
    // row cascades the manual links only.
    await api(`/admin/api/atlas/${newId}`, { method: 'DELETE' }).catch(() => {});
  }

  console.log(`\n${passed}/${passed + failures.length} passed`);
  if (failures.length) {
    console.log('\nfailures:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('\nsuite crashed:', err);
  process.exit(1);
});
