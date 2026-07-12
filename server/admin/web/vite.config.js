import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The app is served at the site root. Public landing page at "/", admin tool
// at "/admin". API calls go to /admin/api/* (rewritten in lib/api.js); the
// public client feed is /api/updates.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // dev only: proxy both API surfaces to the Node server
      '/admin/api': { target: 'http://localhost:8787', changeOrigin: true },
      '/api': { target: 'http://localhost:8787', changeOrigin: true },
    },
  },
  build: {
    outDir: '../server/public',
    emptyOutDir: true,
  },
});
