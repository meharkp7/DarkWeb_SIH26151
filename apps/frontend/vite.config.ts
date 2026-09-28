import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Backend origin used by the dev-server proxy.
 *
 * The API serves `/api/v1/*` and `/health*` at its root (see
 * `src/aegis/api/app.py`), so both prefixes are proxied verbatim.
 */
const API_PROXY_TARGET = process.env['VITE_PROXY_TARGET'] ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
      },
      '/health': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
  },
  build: {
    outDir: 'dist',
    target: 'es2020',
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
});
