import express from 'express';
import { safeRouter } from '../lib/safeRouter.js';
import rateLimit from 'express-rate-limit';
import { q, q1, write } from '../lib/db.js';
import {
  hashPassword, verifyPassword, signToken, requireAuth,
  COOKIE_NAME, cookieOptions,
} from '../lib/auth.js';
import {
  createInvite, listInvites, revokeInvite, redeemInvite,
} from '../lib/invites.js';

const router = safeRouter(express.Router());

const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 20,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Too many attempts. Wait a few minutes and try again.' },
});

const now = () => Math.floor(Date.now() / 1000);

router.post('/login', loginLimiter, async (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) {
    return res.status(400).json({ error: 'Enter a username and password.' });
  }
  const user = await q1('SELECT * FROM admin_users WHERE username = ? LIMIT 1', [username]);
  // Constant-ish response whether or not the user exists.
  const ok = user && await verifyPassword(password, user.password_hash);
  if (!ok) return res.status(401).json({ error: 'Wrong username or password.' });

  await write('UPDATE admin_users SET last_login = ? WHERE user_id = ?', [now(), user.user_id]);
  res.cookie(COOKIE_NAME, signToken(user), cookieOptions());
  res.json({ username: user.username });
});

router.post('/logout', (req, res) => {
  res.clearCookie(COOKIE_NAME, { ...cookieOptions(), maxAge: undefined });
  res.json({ ok: true });
});

router.get('/me', requireAuth, (req, res) => {
  res.json({ username: req.user.username });
});

// --- self-service registration via one-time invite code -------------------
// PUBLIC (a new user has no session yet), rate-limited like login.
router.post('/register', loginLimiter, async (req, res) => {
  try {
    const { code, username, password } = req.body || {};
    const result = await redeemInvite({ code, username, password });
    res.status(201).json(result);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

// Admin-only: generate / list / revoke invite codes.
router.post('/invites', requireAuth, async (req, res) => {
  const result = await createInvite(req.user.username);
  res.status(201).json(result); // { code, expires_at } — raw code shown once
});

router.get('/invites', requireAuth, async (req, res) => {
  res.json(await listInvites());
});

router.delete('/invites/:id', requireAuth, async (req, res) => {
  try {
    res.json(await revokeInvite(Number(req.params.id)));
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

// --- admin user management (any signed-in admin can add another) ----------
router.get('/users', requireAuth, async (req, res) => {
  const rows = await q(
    'SELECT user_id, username, created_at, last_login FROM admin_users ORDER BY username');
  res.json(rows);
});

router.post('/users', requireAuth, async (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) {
    return res.status(400).json({ error: 'Enter a username and password.' });
  }
  if (password.length < 8) {
    return res.status(400).json({ error: 'Use a password of at least 8 characters.' });
  }
  const exists = await q1('SELECT 1 FROM admin_users WHERE username = ? LIMIT 1', [username]);
  if (exists) return res.status(409).json({ error: 'That username is taken.' });

  const hash = await hashPassword(password);
  await write(
    'INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)',
    [username, hash, now()]);
  res.status(201).json({ username });
});

router.delete('/users/:id', requireAuth, async (req, res) => {
  const id = Number(req.params.id);
  const total = (await q1('SELECT COUNT(*) AS n FROM admin_users')).n;
  if (total <= 1) {
    return res.status(400).json({ error: 'Cannot remove the last remaining admin.' });
  }
  const target = await q1('SELECT username FROM admin_users WHERE user_id = ?', [id]);
  if (!target) return res.status(404).json({ error: 'No such admin.' });
  if (target.username === req.user.username) {
    return res.status(400).json({ error: 'You cannot remove your own account while signed in.' });
  }
  await write('DELETE FROM admin_users WHERE user_id = ?', [id]);
  res.json({ ok: true });
});

export default router;
