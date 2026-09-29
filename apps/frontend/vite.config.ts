import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

/**
 * Backend origin used by the dev-server proxy.
 *
 * The API serves `/api/v1/*` and `/health*` at its root (see
 * `src/aegis/api/app.py`), so both prefixes are proxied verbatim.
 */
const API_PROXY_TARGET = process.env['VITE_PROXY_TARGET'] ?? 'http://127.0.0.1:8000';

/**
 * The frontend talks to the API with same-origin relative paths
 * (`/api/v1/*`, `/health*`), so both the dev server *and* the preview server
 * must forward those prefixes. Without the preview proxy a built bundle
 * served by `npm run preview` sends its credentialed requests to the preview
 * origin itself, where they are answered by the static handler — the login
 * POST never reaches the API and every authenticated route comes back
 * 401/404 while the backend log stays empty.
 */
const apiProxy = (target: string) => ({
  target,
  changeOrigin: true,
  // The API answers unauthenticated requests with a bare 401 and never
  // redirects; following one would turn a rejected token into an HTML page.
  autoRewrite: false,
  secure: false,
  // Required for `/api/v1/live`. Without it the proxy forwards HTTP only and
  // the browser's upgrade request is answered by the static handler, so the
  // socket never opens and the console sits on "Reconnecting" forever with no
  // error anywhere. The live snapshot falls back to REST, so the failure
  // looks like a working screen that merely stops updating — which is the
  // worst shape a failure can take here.
  ws: true,
});

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': apiProxy(API_PROXY_TARGET),
      '/health': apiProxy(API_PROXY_TARGET),
    },
  },
  preview: {
    port: 4173,
    strictPort: false,
    proxy: {
      '/api': apiProxy(API_PROXY_TARGET),
      '/health': apiProxy(API_PROXY_TARGET),
    },
  },
  build: {
    outDir: 'dist',
    target: 'es2020',
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    globals: false,
    clearMocks: true,
  },
});