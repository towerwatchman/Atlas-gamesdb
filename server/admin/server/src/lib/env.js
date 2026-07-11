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

export const env = {
  DB_HOST: process.env.DB_HOST || 'localhost',
  DB_PORT: Number(process.env.DB_PORT || 3306),
  DB_USER: req('DB_USER'),
  DB_PASSWORD: process.env.DB_PASSWORD || '',
  DB_NAME: process.env.DB_NAME || 'games',

  JWT_SECRET: req('JWT_SECRET'),
  SESSION_HOURS: Number(process.env.SESSION_HOURS || 12),

  PORT: Number(process.env.PORT || 8787),
  CORS_ORIGINS: (process.env.CORS_ORIGINS || '')
    .split(',').map((s) => s.trim()).filter(Boolean),

  SEED_ADMIN_USER: process.env.SEED_ADMIN_USER || 'admin',
  SEED_ADMIN_PASSWORD: process.env.SEED_ADMIN_PASSWORD || '',
};
