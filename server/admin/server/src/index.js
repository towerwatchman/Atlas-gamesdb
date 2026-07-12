// ---------------------------------------------------------------------------
// Atlas Admin API server.
//
// Serves the JSON API under /api/* and, in production, the built React app
// from ./public (so the whole admin tool runs on one origin behind your
// existing web server / reverse proxy). The Python scraper and the read-only
// updates.php endpoint are entirely separate and untouched.
// ---------------------------------------------------------------------------
import express from 'express';
import cookieParser from 'cookie-parser';
import path from 'path';
import { fileURLToPath } from 'url';

import { env } from './lib/env.js';
import { requireAuth } from './lib/auth.js';
import authRoutes from './routes/auth.js';
import atlasRoutes from './routes/atlas.js';
import duplicateRoutes from './routes/duplicates.js';
import queueRoutes from './routes/queue.js';
import statsRoutes from './routes/stats.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();

app.use(express.json({ limit: '2mb' }));
app.use(cookieParser());

// Dev CORS (frontend on a different port). No-op in production (same origin).
if (env.CORS_ORIGINS.length) {
  app.use((req, res, next) => {
    const origin = req.headers.origin;
    if (origin && env.CORS_ORIGINS.includes(origin)) {
      res.header('Access-Control-Allow-Origin', origin);
      res.header('Access-Control-Allow-Credentials', 'true');
      res.header('Access-Control-Allow-Headers', 'Content-Type');
      res.header('Access-Control-Allow-Methods', 'GET,POST,PATCH,DELETE,OPTIONS');
    }
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    next();
  });
}

app.get('/api/health', (req, res) => res.json({ ok: true }));

// Public auth endpoints (login/logout); the rest of /auth requires a session.
app.use('/api/auth', authRoutes);

// Everything below needs a signed-in admin.
app.use('/api/atlas', requireAuth, atlasRoutes);
app.use('/api/duplicates', requireAuth, duplicateRoutes);
app.use('/api/queue', requireAuth, queueRoutes);
app.use('/api/stats', requireAuth, statsRoutes);

// Serve the built frontend in production.
const publicDir = path.join(__dirname, '..', 'public');
app.use(express.static(publicDir));
app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/')) return next();
  res.sendFile(path.join(publicDir, 'index.html'), (err) => { if (err) next(); });
});

app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Something went wrong on the server.' });
});

app.listen(env.PORT, () => {
  console.log(`Atlas Admin API listening on http://localhost:${env.PORT}`);
});

// Final safety net: a stray rejection anywhere should be logged, never fatal.
// Route-level errors are already caught by safeRouter + the handler above;
// this covers anything outside the request lifecycle.
process.on('unhandledRejection', (err) => {
  console.error('Unhandled rejection (kept alive):', err);
});
process.on('uncaughtException', (err) => {
  console.error('Uncaught exception (kept alive):', err);
});
