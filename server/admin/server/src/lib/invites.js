// ---------------------------------------------------------------------------
// One-time invite codes for self-service admin registration.
//
// A code is a random string shown to the generating admin ONCE; only its
// bcrypt hash is stored. Redemption verifies the code against unused,
// unexpired rows, then — in a single transaction — marks the code used and
// creates the new admin account, so a code can never be redeemed twice.
// ---------------------------------------------------------------------------
import crypto from 'crypto';
import bcrypt from 'bcryptjs';
import { q, q1, tx } from './db.js';
import { hashPassword } from './auth.js';

const SEVEN_DAYS = 7 * 24 * 3600;
const now = () => Math.floor(Date.now() / 1000);

// Human-friendly-ish random code: 24 hex chars in groups, e.g. "3f9a-1c...".
function makeRawCode() {
  const hex = crypto.randomBytes(12).toString('hex'); // 24 chars
  return hex.match(/.{1,4}/g).join('-');
}

/** Generate a code, store its hash, return the RAW code (shown once). */
export async function createInvite(createdBy) {
  const raw = makeRawCode();
  const codeHash = await bcrypt.hash(raw, 12);
  const ts = now();
  await q(
    `INSERT INTO invite_codes (code_hash, created_by, created_at, expires_at)
     VALUES (?, ?, ?, ?)`,
    [codeHash, createdBy, ts, ts + SEVEN_DAYS],
  );
  return { code: raw, expires_at: ts + SEVEN_DAYS };
}

/** List invite codes (never returns hashes) for the Admins tab. */
export async function listInvites() {
  return q(
    `SELECT invite_id, created_by, created_at, expires_at, used_at, used_by
     FROM invite_codes ORDER BY created_at DESC`,
  );
}

/** Delete an unused invite code (revoke it). */
export async function revokeInvite(inviteId) {
  const row = await q1('SELECT used_at FROM invite_codes WHERE invite_id = ?', [inviteId]);
  if (!row) throw Object.assign(new Error('No such invite.'), { status: 404 });
  if (row.used_at) throw Object.assign(new Error('That invite was already used.'), { status: 409 });
  await q('DELETE FROM invite_codes WHERE invite_id = ?', [inviteId]);
  return { revoked: inviteId };
}

/**
 * Redeem a code to create a new admin account. Atomic: the code is verified,
 * consumed, and the account created in one transaction. bcrypt hashes can't be
 * looked up by value, so we scan candidate rows (unused + unexpired) and
 * compare — the set is small in practice, and this keeps codes un-guessable.
 */
export async function redeemInvite({ code, username, password }) {
  if (!code || !username || !password) {
    throw Object.assign(new Error('Enter an invite code, username, and password.'), { status: 400 });
  }
  if (password.length < 8) {
    throw Object.assign(new Error('Use a password of at least 8 characters.'), { status: 400 });
  }

  const ts = now();
  const candidates = await q(
    `SELECT invite_id, code_hash FROM invite_codes
     WHERE used_at IS NULL AND expires_at > ?`,
    [ts],
  );

  let matchedId = null;
  for (const row of candidates) {
    // eslint-disable-next-line no-await-in-loop
    if (await bcrypt.compare(code, row.code_hash)) { matchedId = row.invite_id; break; }
  }
  if (!matchedId) {
    throw Object.assign(new Error('That invite code is invalid, used, or expired.'), { status: 403 });
  }

  const taken = await q1('SELECT 1 FROM admin_users WHERE username = ? LIMIT 1', [username]);
  if (taken) throw Object.assign(new Error('That username is taken.'), { status: 409 });

  const passwordHash = await hashPassword(password);

  await tx(async (conn) => {
    // Consume the code only if still unused (guards against a race).
    const [res] = await conn.execute(
      `UPDATE invite_codes SET used_at = ?, used_by = ?
       WHERE invite_id = ? AND used_at IS NULL`,
      [ts, username, matchedId],
    );
    if (res.affectedRows !== 1) {
      throw Object.assign(new Error('That invite code was just used.'), { status: 409 });
    }
    await conn.execute(
      'INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)',
      [username, passwordHash, ts],
    );
  });

  return { username };
}
