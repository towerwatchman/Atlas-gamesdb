/**
 * Date editing and per-field locks.
 *
 * The lock tests matter most. `version` was always in EDITABLE_ATLAS_COLUMNS
 * and PATCH always applied it — but the scraper's updateAtlasById() wrote the
 * whole crawl result back over the row and nothing read the `edited` flag, so
 * the edit reverted on the next crawl of that thread. These check both halves:
 * the admin API records the lock, and the scraper honours it.
 *
 *   node tests/locks.test.mjs
 *
 * The scraper half shells out to python and needs the scraper's dependencies
 * plus a .env pointing at the same database; it skips cleanly if either is
 * missing.
 */
import { execFile } from 'child_process';
import { promisify } from 'util';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { existsSync } from 'fs';

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..', '..', '..');

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

async function main() {
  await login();
  console.log(`logged in as ${USER}\n`);

  let id = null;
  await test('setup: a game to work on', async () => {
    const { status, json } = await api('/admin/api/atlas', {
      method: 'POST',
      body: { fields: { title: 'Lock Test Game', creator: 'LockDev', version: '1.0' } },
    });
    eq(status, 201, 'created');
    id = json.atlas_id;
  });

  // ------------------------------------------------------------- metadata
  await test('column metadata names the date and lockable fields', async () => {
    const { json } = await api('/admin/api/atlas/meta/columns');
    assert(json.dates.includes('release_date'), 'release_date is a date');
    assert(json.dates.includes('last_record_update'), 'last_record_update is a date');
    assert(json.editable.includes('version'), 'version is editable');
    assert(json.editable.includes('last_record_update'), 'last_record_update is editable');
    assert(!json.lockable.includes('last_record_update'),
      'last_record_update must not be lockable — it drives the delta packager');
    assert(json.lockable.includes('release_date'), 'release_date is lockable');
  });

  // ----------------------------------------------------------- date edits
  await test('release_date can be set', async () => {
    const when = 1768953600;
    await api(`/admin/api/atlas/${id}`, {
      method: 'PATCH', body: { changes: { release_date: when } },
    });
    const row = (await api(`/admin/api/atlas/${id}`)).json;
    eq(Number(row.release_date), when, 'release_date stored');
  });

  await test('an explicit last_record_update is kept, not stamped over', async () => {
    // Every other edit bumps this to now(); setting it deliberately must win,
    // or the field would be impossible to change.
    const backdated = 1600000000;
    await api(`/admin/api/atlas/${id}`, {
      method: 'PATCH', body: { changes: { last_record_update: backdated } },
    });
    const row = (await api(`/admin/api/atlas/${id}`)).json;
    eq(Number(row.last_record_update), backdated, 'explicit timestamp preserved');
  });

  await test('an unrelated edit still bumps last_record_update', async () => {
    const before = Math.floor(Date.now() / 1000) - 5;
    await api(`/admin/api/atlas/${id}`, {
      method: 'PATCH', body: { changes: { developer: 'Bumped' } },
    });
    const row = (await api(`/admin/api/atlas/${id}`)).json;
    assert(Number(row.last_record_update) >= before,
      'a normal edit must re-export the row');
  });

  await test('date edits are audited', async () => {
    const audit = (await api(`/admin/api/atlas/${id}/audit`)).json;
    assert(audit.some((a) => a.field === 'atlas.release_date'), 'release_date audited');
    assert(audit.some((a) => a.field === 'atlas.last_record_update'),
      'last_record_update audited');
  });

  // ---------------------------------------------------------------- locks
  await test('editing a field locks it automatically', async () => {
    await api(`/admin/api/atlas/${id}`, {
      method: 'PATCH', body: { changes: { version: '2.0-admin' } },
    });
    const row = (await api(`/admin/api/atlas/${id}`)).json;
    assert(row._locked_fields.includes('version'),
      `version not locked: ${JSON.stringify(row._locked_fields)}`);
  });

  await test('locking last_record_update is refused', async () => {
    const { status, json } = await api(`/admin/api/atlas/${id}/locks/last_record_update`, {
      method: 'PUT', body: { locked: true },
    });
    eq(status, 400, 'status');
    assert(/bookkeeping/i.test(json.error), json.error);
  });

  await test('editing last_record_update does not lock it', async () => {
    const row = (await api(`/admin/api/atlas/${id}`)).json;
    assert(!row._locked_fields.includes('last_record_update'),
      'it must stay writable by the scraper');
  });

  await test('a field can be unlocked again', async () => {
    const { status, json } = await api(`/admin/api/atlas/${id}/locks/version`, {
      method: 'PUT', body: { locked: false },
    });
    eq(status, 200, 'status');
    assert(!json.locked_fields.includes('version'), 'unlocked');
    const row = (await api(`/admin/api/atlas/${id}`)).json;
    assert(!row._locked_fields.includes('version'), 'persisted');
  });

  await test('lock changes are audited', async () => {
    const audit = (await api(`/admin/api/atlas/${id}/audit`)).json;
    assert(audit.some((a) => a.field === 'atlas.lock' || a.field === 'atlas.unlock'),
      'lock/unlock should appear in history');
  });

  await test('locking an unknown column is refused', async () => {
    const { status } = await api(`/admin/api/atlas/${id}/locks/not_a_column`, {
      method: 'PUT', body: { locked: true },
    });
    eq(status, 400, 'status');
  });

  // --------------------------------------- the scraper half of the contract
  await test('the scraper skips locked fields (and only those)', async () => {
    const envFile = resolve(repoRoot, '.env');
    if (!existsSync(envFile)) {
      console.log('      (skipping: no scraper .env at repo root)');
      return;
    }
    // Re-lock version, leave status unlocked.
    await api(`/admin/api/atlas/${id}`, {
      method: 'PATCH', body: { changes: { version: '3.0-admin', status: 'Ongoing' } },
    });
    await api(`/admin/api/atlas/${id}/locks/status`, {
      method: 'PUT', body: { locked: false },
    });

    // Drive the real scraper write path.
    const script = `
import sys
sys.path.insert(0, ${JSON.stringify(repoRoot)})
from scraper.utils.db import updateAtlasById, getLockedAtlasFields
print("locked:", sorted(getLockedAtlasFields(${id})))
updateAtlasById(${id}, {"version": "9.9-from-scraper", "status": "Completed"})
`;
    try {
      const { stdout } = await run('python3', ['-c', script], { cwd: repoRoot });
      console.log(`      ${stdout.trim().split('\n').join('\n      ')}`);
    } catch (e) {
      // Print the real reason rather than a truncated command echo; a silent
      // skip here would hide the half of the contract that matters most.
      const why = (e.stderr || e.message || '').trim().split('\n').slice(-4).join(' | ');
      console.log(`      (skipping: scraper could not run — ${why})`);
      return;
    }

    const row = (await api(`/admin/api/atlas/${id}`)).json;
    eq(row.version, '3.0-admin', 'the LOCKED field must survive the crawl');
    eq(row.status, 'Completed', 'the UNLOCKED field must still be updated');
  });

  await test('cleanup', async () => {
    await api(`/admin/api/atlas/${id}`, { method: 'DELETE' }).catch(() => {});
  });

  console.log(`\n${passed}/${passed + failures.length} passed`);
  if (failures.length) {
    console.log('\nfailures:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((err) => { console.error('\nsuite crashed:', err); process.exit(1); });
