// Authentication helpers: bcrypt password hashing + signed session tokens.
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { env } from './env.js';

export async function hashPassword(plain) {
  return bcrypt.hash(plain, 12);
}

export async function verifyPassword(plain, hash) {
  return bcrypt.compare(plain, hash);
}

export function signToken(user) {
  return jwt.sign(
    { uid: user.user_id, username: user.username },
    env.JWT_SECRET,
    { expiresIn: `${env.SESSION_HOURS}h` },
  );
}

export function verifyToken(token) {
  try { return jwt.verify(token, env.JWT_SECRET); }
  catch { return null; }
}

// Express middleware: requires a valid session cookie, attaches req.user.
export function requireAuth(req, res, next) {
  const token = req.cookies?.atlas_admin;
  const payload = token && verifyToken(token);
  if (!payload) return res.status(401).json({ error: 'Not signed in.' });
  req.user = payload;
  next();
}

export const COOKIE_NAME = 'atlas_admin';
export function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    maxAge: env.SESSION_HOURS * 3600 * 1000,
    path: '/',
  };
}
