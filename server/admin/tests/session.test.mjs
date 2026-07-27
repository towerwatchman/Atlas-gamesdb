/**
 * How SESSION_HOURS is resolved.
 *
 * This exists because of a real miss: the code default was raised from 12 to 168
 * and a test asserted "the cookie lasts a week" — and passed, because the test
 * environment had no SESSION_HOURS set so the default applied. The deployed
 * server's .env pinned SESSION_HOURS=12, which silently won, and logins kept
 * expiring after half a day.
 *
 * A test can't reach into someone's deployment, so instead these pin the
 * resolution rules and make the effective value observable: env.js falls back
 * for blank/zero/junk rather than minting a cookie that expires immediately,
 * and the startup banner states the value and where it came from.
 *
 *   node tests/session.test.mjs
 */
import { execFile } from 'child_process';
import { promisify } from 'util';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const serverDir = resolve(here, '..', 'server');

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
  if (String(a) !== String(b)) throw new Error(`${m || 'not equal'}: got ${a}, want ${b}`);
}

// env.js reads process.env once at import, so each case needs its own process.
async function resolveWith(sessionHours) {
  const env = {
    ...process.env,
    DB_USER: 'x',
    JWT_SECRET: 'y',
  };
  if (sessionHours === undefined) delete env.SESSION_HOURS;
  else env.SESSION_HOURS = String(sessionHours);

  const script = `
import { env, sessionSummary } from './src/lib/env.js';
process.stdout.write(JSON.stringify({ hours: env.SESSION_HOURS, summary: sessionSummary() }));
`;
  const { stdout } = await run('node', ['--input-type=module', '-e', script],
    { cwd: serverDir, env });
  return JSON.parse(stdout);
}

async function main() {
  await test('unset falls back to one week', async () => {
    const r = await resolveWith(undefined);
    eq(r.hours, 168, 'hours');
    assert(/from default/.test(r.summary), r.summary);
    assert(/7 days/.test(r.summary), r.summary);
  });

  await test('an explicit value wins, and says it came from .env', async () => {
    // The exact situation that caused the bug: a deployment pinning 12.
    const r = await resolveWith(12);
    eq(r.hours, 12, 'hours');
    assert(/from \.env/.test(r.summary), r.summary);
    assert(/12 hours/.test(r.summary), `should spell out the short duration: ${r.summary}`);
  });

  await test('a week can be set explicitly', async () => {
    const r = await resolveWith(168);
    eq(r.hours, 168, 'hours');
    assert(/7 days/.test(r.summary), r.summary);
  });

  await test('blank falls back rather than expiring instantly', async () => {
    eq((await resolveWith('')).hours, 168, 'blank');
    eq((await resolveWith('   ')).hours, 168, 'whitespace');
  });

  await test('zero and negative fall back', async () => {
    eq((await resolveWith(0)).hours, 168, 'zero');
    eq((await resolveWith(-5)).hours, 168, 'negative');
  });

  await test('junk falls back', async () => {
    eq((await resolveWith('one week')).hours, 168, 'junk');
    eq((await resolveWith('12h')).hours, 168, '"12h" is not a number');
  });

  await test('fractional hours are allowed', async () => {
    const r = await resolveWith(0.5);
    eq(r.hours, 0.5, 'hours');
    assert(/0\.5 hours/.test(r.summary), r.summary);
  });

  await test('the shipped .env.example asks for a week', async () => {
    const { readFileSync } = await import('fs');
    const example = readFileSync(resolve(serverDir, '.env.example'), 'utf8');
    const m = /^SESSION_HOURS=(\d+)/m.exec(example);
    assert(m, 'SESSION_HOURS missing from .env.example');
    eq(m[1], '168', '.env.example should default to a week');
    assert(/OVERRIDES/i.test(example),
      '.env.example should warn that this value overrides the code default');
  });

  console.log(`\n${passed}/${passed + failures.length} passed`);
  if (failures.length) {
    console.log('\nfailures:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((e) => { console.error('\nsuite crashed:', e); process.exit(1); });
