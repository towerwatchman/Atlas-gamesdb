import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, the API runs on :8787 and Vite on :5173; proxy /api through so
// cookies work same-origin. In prod, `npm run build` emits into
// ../server/public, which the Express server serves directly.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8787', changeOrigin: true },
    },
  },
  build: {
    outDir: '../server/public',
    emptyOutDir: true,
  },
});
