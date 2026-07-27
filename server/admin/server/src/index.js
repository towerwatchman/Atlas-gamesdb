// ---------------------------------------------------------------------------
// Atlas server.
//
// Serves ONE React app at the root:
//   /            public landing page (starfield)
//   /admin       admin tool (login-gated in the UI)
//
// Two API surfaces:
//   GET /api/updates        PUBLIC, read-only feed for the Atlas client
//                           (replaces the old updates.php — same response shape)
//   /admin/api/*            admin API (auth-gated), used by the /admin UI
//
// One Node process, one origin. The Python scraper is untouched.
// ---------------------------------------------------------------------------
import express from 'express';
import cookieParser from 'cookie-parser';
import path from 'path';
import { fileURLToPath } from 'url';

import { env, sessionSummary } from './lib/env.js';
import { requireAuth } from './lib/auth.js';
import authRoutes from './routes/auth.js';
import atlasRoutes from './routes/atlas.js';
import duplicateRoutes from './routes/duplicates.js';
import queueRoutes from './routes/queue.js';
import f95RefreshRoutes from './routes/f95Refresh.js';
import statsRoutes from './routes/stats.js';
import changelogRoutes from './routes/changelog.js';
import adminActivityRoutes from './routes/adminActivity.js';
import revertRoutes from './routes/revert.js';
import updatesRoutes from './routes/updates.js';

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

// --- PUBLIC API ------------------------------------------------------------
// The Atlas client polls this; no auth. Kept at /api/updates to match the old
// Apache alias so the client needs no change.
app.use('/api/updates', updatesRoutes);
app.get('/api/health', (req, res) => res.json({ ok: true }));

// --- ADMIN API (namespaced under /admin/api, auth-gated) -------------------
app.use('/admin/api/auth', authRoutes);
app.use('/admin/api/atlas', requireAuth, atlasRoutes);
app.use('/admin/api/duplicates', requireAuth, duplicateRoutes);
app.use('/admin/api/queue', requireAuth, queueRoutes);
app.use('/admin/api/f95-refresh', requireAuth, f95RefreshRoutes);
app.use('/admin/api/stats', requireAuth, statsRoutes);
app.use('/admin/api/admin-activity', requireAuth, adminActivityRoutes);
app.use('/admin/api/revert', requireAuth, revertRoutes);
app.use('/admin/api/changelog', requireAuth, changelogRoutes);

// --- Static React app + SPA fallback ---------------------------------------
const publicDir = path.join(__dirname, '..', 'public');
app.use(express.static(publicDir));
app.get('*', (req, res, next) => {
  // Never let API paths fall through to the SPA index.
  if (req.path.startsWith('/api/') || req.path.startsWith('/admin/api/')) return next();
  res.sendFile(path.join(publicDir, 'index.html'), (err) => { if (err) next(); });
});

app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Something went wrong on the server.' });
});

app.listen(env.PORT, () => {
  console.log(`Atlas server listening on http://localhost:${env.PORT}`);
  // Printed so a stale SESSION_HOURS in .env is obvious in the pm2 logs
  // rather than only showing up as "I have to log in again".
  console.log(`Sessions last ${sessionSummary()}`);
});

// Final safety net: a stray rejection anywhere should be logged, never fatal.
process.on('unhandledRejection', (err) => {
  console.error('Unhandled rejection (kept alive):', err);
});
process.on('uncaughtException', (err) => {
  console.error('Uncaught exception (kept alive):', err);
});
