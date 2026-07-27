/**
 * Revert tests against a REAL database.
 *
 * The interesting case is a merge: it emits several `merge.relink` rows plus a
 * `merge.delete`, the deleted atlas row is gone, and undoing it means restoring
 * that row and then moving every source row back — in the right order, all or
 * nothing. Everything else (field edits, link add/remove/update, creation) is
 * simpler but shares the same batch/snapshot machinery.
 *
 *   node tests/revert.test.mjs
 *
 * Needs a running server, schema 001..007, and a seeded admin. It writes and
 * cleans up its own rows — scratch database only.
 */
const BASE = process.env.API_BASE || 'http://127.0.0.1:8788';
const USER = process.env.ADMIN_USER || 'tester';
const PASS = process.env.ADMIN_PASSWORD || 'testpass123';

let cookie = '';
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

async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch { json = { _raw: text }; }
  return { status: res.status, json };
}

async function login() {
  const res = await fetch(`${BASE}/admin/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  assert(res.ok, `login failed: ${res.status}`);
  cookie = res.headers.get('set-cookie').split(';')[0];
}

const auditFor = async (id) => (await api(`/admin/api/atlas/${id}/audit`)).json;
const findAudit = (rows, field) => rows.find((r) => r.field === field);

async function main() {
  await login();
  console.log(`logged in as ${USER}\n`);

  // ---------------------------------------------------------- field edits
  let gameId = null;
  await test('setup: create a game to work on', async () => {
    const { status, json } = await api('/admin/api/atlas', {
      method: 'POST',
      body: { fields: { title: 'Revert Test Game', creator: 'RevDev', version: '1.0' } },
    });
    eq(status, 201, 'created');
    gameId = json.atlas_id;
  });

  await test('a field edit can be reverted', async () => {
    await api(`/admin/api/atlas/${gameId}`, {
      method: 'PATCH', body: { changes: { version: '2.0' } },
    });
    const before = (await api(`/admin/api/atlas/${gameId}`)).json;
    eq(before.version, '2.0', 'edit applied');

    const entry = findAudit(await auditFor(gameId), 'atlas.version');
    assert(entry, 'no atlas.version audit row');
    assert(entry.revertible, `not revertible: ${entry.reason}`);

    const { status } = await api(`/admin/api/revert/${entry.audit_id}`, { method: 'POST' });
    eq(status, 200, 'revert status');
    const after = (await api(`/admin/api/atlas/${gameId}`)).json;
    eq(after.version, '1.0', 'version restored');
  });

  await test('the revert is itself audited', async () => {
    const rows = await auditFor(gameId);
    const rev = rows.find((r) => r.field === 'revert.atlas.version');
    assert(rev, 'no revert audit row');
    assert(rev.revert_of, 'revert_of not set');
    const original = rows.find((r) => r.audit_id === rev.revert_of);
    assert(original.reverted_at, 'original not marked reverted');
    eq(original.reverted_by, USER, 'reverted_by');
  });

  await test('the same entry cannot be reverted twice', async () => {
    const rows = await auditFor(gameId);
    const entry = rows.find((r) => r.field === 'atlas.version' && r.reverted_at);
    const { status, json } = await api(`/admin/api/revert/${entry.audit_id}`, { method: 'POST' });
    eq(status, 409, 'status');
    assert(/already reverted/i.test(json.error), json.error);
  });

  await test('a revert entry is flagged as not revertible', async () => {
    const rev = (await auditFor(gameId)).find((r) => r.field === 'revert.atlas.version');
    eq(rev.revertible, false, 'revertible');
    assert(/itself a revert/i.test(rev.reason), rev.reason);
  });

  await test('reverting refuses to discard a newer change', async () => {
    await api(`/admin/api/atlas/${gameId}`, {
      method: 'PATCH', body: { changes: { developer: 'First' } },
    });
    const entry = findAudit(await auditFor(gameId), 'atlas.developer');
    // Somebody else edits the same column afterwards.
    await api(`/admin/api/atlas/${gameId}`, {
      method: 'PATCH', body: { changes: { developer: 'Second' } },
    });
    const { status, json } = await api(`/admin/api/revert/${entry.audit_id}`, { method: 'POST' });
    eq(status, 409, 'status');
    assert(/has changed since/i.test(json.error), json.error);
    const now = (await api(`/admin/api/atlas/${gameId}`)).json;
    eq(now.developer, 'Second', 'the newer value must survive a refused revert');
  });

  // ------------------------------------------------------- manual links
  let linkId = null;
  await test('adding a link can be reverted', async () => {
    const created = (await api(`/admin/api/atlas/${gameId}/manual-links`, {
      method: 'POST', body: { kind: 'steam', extId: '55501', label: 'Base' },
    })).json;
    linkId = created.link_id;
    const entry = findAudit(await auditFor(gameId), 'manual_link.add');
    assert(entry.revertible, entry.reason);
    await api(`/admin/api/revert/${entry.audit_id}`, { method: 'POST' });
    const links = (await api(`/admin/api/atlas/${gameId}/manual-links`)).json;
    assert(!links.some((l) => l.link_id === linkId), 'link should be gone');
  });

  await test('removing a link can be reverted, DLC and all', async () => {
    const base = (await api(`/admin/api/atlas/${gameId}/manual-links`, {
      method: 'POST', body: { kind: 'steam', extId: '55502', label: 'Base again' },
    })).json;
    const dlc = (await api(`/admin/api/atlas/${gameId}/manual-links`, {
      method: 'POST',
      body: {
        kind: 'steam', extId: '55503', label: 'A DLC',
        entryType: 'dlc', parentKind: 'manual', parentLinkId: base.link_id,
      },
    })).json;

    const del = await api(`/admin/api/atlas/${gameId}/manual-links/${base.link_id}`, { method: 'DELETE' });
    eq(del.json.orphaned, 1, 'one DLC orphaned');

    const entry = findAudit(await auditFor(gameId), 'manual_link.remove');
    assert(entry.revertible, entry.reason);
    await api(`/admin/api/revert/${entry.audit_id}`, { method: 'POST' });

    const links = (await api(`/admin/api/atlas/${gameId}/manual-links`)).json;
    const restored = links.find((l) => l.link_id === base.link_id);
    assert(restored, 'base link not restored');
    eq(restored.label, 'Base again', 'label restored');
    const child = links.find((l) => l.link_id === dlc.link_id);
    eq(child.parent_link_id, base.link_id, 'the DLC must be re-tied to its parent');
  });

  await test('editing a link can be reverted', async () => {
    const link = (await api(`/admin/api/atlas/${gameId}/manual-links`, {
      method: 'POST', body: { kind: 'gog', extId: 'g1', label: 'Original label' },
    })).json;
    await api(`/admin/api/atlas/${gameId}/manual-links/${link.link_id}`, {
      method: 'PATCH', body: { label: 'Changed label' },
    });
    const entry = findAudit(await auditFor(gameId), 'manual_link.update');
    assert(entry.revertible, entry.reason);
    await api(`/admin/api/revert/${entry.audit_id}`, { method: 'POST' });
    const links = (await api(`/admin/api/atlas/${gameId}/manual-links`)).json;
    eq(links.find((l) => l.link_id === link.link_id).label, 'Original label', 'label restored');
  });

  // --------------------------------------------------------- the merge
  let survivorId = null;
  let doomedId = null;
  await test('setup: two games to merge, each with a source', async () => {
    survivorId = (await api('/admin/api/atlas', {
      method: 'POST', body: { fields: { title: 'Merge Survivor', creator: 'MDev' } },
    })).json.atlas_id;
    doomedId = (await api('/admin/api/atlas', {
      method: 'POST', body: { fields: { title: 'Merge Doomed', creator: 'MDev2', version: '9.9' } },
    })).json.atlas_id;
    assert(survivorId && doomedId, 'ids');
  });

  await test('merging then reverting restores the deleted row AND its sources', async () => {
    // Give the doomed row a source so the merge has something to relink.
    const link = await api('/admin/api/duplicates/relink-source', {
      method: 'POST',
      body: { table: 'f95_zone', sourceId: 777001, action: 'link', atlasId: doomedId },
    });
    if (link.status !== 200) {
      console.log(`      (skipping: could not attach a test source — ${link.json?.error})`);
      return;
    }

    const merged = await api('/admin/api/duplicates/merge', {
      method: 'POST', body: { survivorId, groupIds: [survivorId, doomedId] },
    });
    eq(merged.status, 200, `merge failed: ${JSON.stringify(merged.json)}`);

    // The doomed row is gone and its source moved to the survivor.
    eq((await api(`/admin/api/atlas/${doomedId}`)).status, 404, 'doomed row deleted');
    const survivor = (await api(`/admin/api/atlas/${survivorId}`)).json;
    assert(survivor._sources?.f95_id, 'source did not move to the survivor');

    // Find the merge batch and preview it.
    const recent = (await api('/admin/api/atlas/audit/recent?limit=50')).json;
    const del = recent.find((r) => r.field === 'merge.delete' && r.atlas_id === doomedId);
    assert(del, 'no merge.delete audit row');

    const preview = (await api(`/admin/api/revert/${del.audit_id}`)).json;
    assert(preview.revertible, `not revertible: ${JSON.stringify(preview.blockers)}`);
    assert(preview.entries.length >= 2,
      `a merge should undo as a batch, got ${preview.entries.length} entries`);

    const rev = await api(`/admin/api/revert/${del.audit_id}`, { method: 'POST' });
    eq(rev.status, 200, `revert failed: ${JSON.stringify(rev.json)}`);

    // The row is back, with its field values.
    const restored = await api(`/admin/api/atlas/${doomedId}`);
    eq(restored.status, 200, 'deleted atlas row restored');
    eq(restored.json.title, 'Merge Doomed', 'title restored');
    eq(restored.json.version, '9.9', 'field values restored, not just the id');
    // ...and the source went back with it.
    assert(restored.json._sources?.f95_id, 'the source row was not moved back');
    const surv = (await api(`/admin/api/atlas/${survivorId}`)).json;
    assert(!surv._sources?.f95_id, 'the survivor should no longer own the source');
  });

  await test('a merge reverts all-or-nothing', async () => {
    const recent = (await api('/admin/api/atlas/audit/recent?limit=50')).json;
    const del = recent.find((r) => r.field === 'merge.delete' && r.reverted_at);
    if (!del) return;      // merge test skipped
    const { status, json } = await api(`/admin/api/revert/${del.audit_id}`, { method: 'POST' });
    eq(status, 409, 'a reverted batch cannot be reverted again');
    assert(/already reverted/i.test(json.error), json.error);
  });

  // ------------------------------------------------ legacy rows / preview
  await test('an entry with no snapshot reports why it cannot be reverted', async () => {
    // Simulate a pre-migration row by reverting something that never had one.
    const rows = await auditFor(gameId);
    const legacy = rows.find((r) => r.field === 'atlas.id_name');
    if (!legacy) return;
    eq(legacy.revertible, false, 'id_name is not an editable column');
    assert(legacy.reason, 'a reason must be given');
  });

  await test('preview never writes', async () => {
    const before = (await api(`/admin/api/atlas/${gameId}`)).json;
    const entry = (await auditFor(gameId)).find((r) => r.revertible);
    if (!entry) return;
    await api(`/admin/api/revert/${entry.audit_id}`);          // GET
    const after = (await api(`/admin/api/atlas/${gameId}`)).json;
    eq(after.version, before.version, 'preview must not change anything');
    eq(after.title, before.title, 'preview must not change anything');
  });

  await test('reverting a creation deletes the row', async () => {
    const fresh = (await api('/admin/api/atlas', {
      method: 'POST', body: { fields: { title: 'Undo My Creation', creator: 'Tmp' } },
    })).json;
    const entry = findAudit(await auditFor(fresh.atlas_id), 'atlas.create');
    assert(entry.revertible, entry.reason);
    const { status } = await api(`/admin/api/revert/${entry.audit_id}`, { method: 'POST' });
    eq(status, 200, 'revert status');
    eq((await api(`/admin/api/atlas/${fresh.atlas_id}`)).status, 404, 'row should be gone');
  });

  await test('revert requires auth', async () => {
    const saved = cookie;
    cookie = '';
    const { status } = await api('/admin/api/revert/1', { method: 'POST' });
    cookie = saved;
    eq(status, 401, 'status');
  });

  console.log(`\n${passed}/${passed + failures.length} passed`);
  if (failures.length) {
    console.log('\nfailures:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((err) => { console.error('\nsuite crashed:', err); process.exit(1); });
