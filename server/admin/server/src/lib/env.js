// Loads and validates environment configuration once at startup.
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// .env lives at server/admin/server/.env (two levels up from src/lib)
dotenv.config({ path: path.join(__dirname, '..', '..', '.env') });

function req(key) {
  const v = process.env[key];
  if (!v) throw new Error(`Missing required env var ${key}. Copy .env.example to .env.`);
  return v;
}

const DEFAULT_SESSION_HOURS = 168;   // one week

function sessionHours() {
  const raw = process.env.SESSION_HOURS;
  if (raw === undefined || String(raw).trim() === '') return DEFAULT_SESSION_HOURS;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) {
    console.warn(`SESSION_HOURS="${raw}" is not a positive number; `
      + `using ${DEFAULT_SESSION_HOURS}h.`);
    return DEFAULT_SESSION_HOURS;
  }
  return n;
}

export const env = {
  DB_HOST: process.env.DB_HOST || 'localhost',
  DB_PORT: Number(process.env.DB_PORT || 3306),
  DB_USER: req('DB_USER'),
  DB_PASSWORD: process.env.DB_PASSWORD || '',
  DB_NAME: process.env.DB_NAME || 'games',

  JWT_SECRET: req('JWT_SECRET'),
  // How long a login lasts, in hours. One week by default (issue #281).
  //
  // NOTE: a value in .env overrides this default. Raising the default alone did
  // nothing for deployments whose .env already pinned SESSION_HOURS=12 -- which
  // is why logins kept expiring after half a day. The effective value is logged
  // at startup and returned by /api/auth/me so a stale .env is visible rather
  // than silent.
  //
  // A blank, zero, negative or non-numeric value falls back to the default
  // instead of producing a cookie that expires immediately.
  SESSION_HOURS: sessionHours(),

  PORT: Number(process.env.PORT || 8787),
  CORS_ORIGINS: (process.env.CORS_ORIGINS || '')
    .split(',').map((s) => s.trim()).filter(Boolean),

  SEED_ADMIN_USER: process.env.SEED_ADMIN_USER || 'admin',
  SEED_ADMIN_PASSWORD: process.env.SEED_ADMIN_PASSWORD || '',
};

/** Human summary of the session length, for the startup banner. */
export function sessionSummary() {
  const h = env.SESSION_HOURS;
  const days = h / 24;
  const pretty = days >= 1
    ? `${Number.isInteger(days) ? days : days.toFixed(1)} day${days === 1 ? '' : 's'}`
    : `${h} hour${h === 1 ? '' : 's'}`;
  const source = process.env.SESSION_HOURS ? '.env' : 'default';
  return `${h}h (${pretty}), from ${source}`;
}
