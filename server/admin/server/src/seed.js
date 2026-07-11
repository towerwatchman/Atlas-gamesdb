// Seed the first admin user from SEED_ADMIN_USER / SEED_ADMIN_PASSWORD.
// Run once after applying the SQL migration:  npm run seed
// Safe to re-run: it won't duplicate an existing username.
import { env } from './lib/env.js';
import { q1, write, pool } from './lib/db.js';
import { hashPassword } from './lib/auth.js';

async function main() {
  if (!env.SEED_ADMIN_PASSWORD) {
    console.error('Set SEED_ADMIN_PASSWORD in .env before seeding.');
    process.exit(1);
  }
  const existing = await q1(
    'SELECT user_id FROM admin_users WHERE username = ? LIMIT 1', [env.SEED_ADMIN_USER]);
  if (existing) {
    console.log(`Admin "${env.SEED_ADMIN_USER}" already exists — nothing to do.`);
  } else {
    const hash = await hashPassword(env.SEED_ADMIN_PASSWORD);
    await write(
      'INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)',
      [env.SEED_ADMIN_USER, hash, Math.floor(Date.now() / 1000)]);
    console.log(`Created admin "${env.SEED_ADMIN_USER}". Change the password after first login.`);
  }
  await pool.end();
}

main().catch((err) => { console.error(err); process.exit(1); });
