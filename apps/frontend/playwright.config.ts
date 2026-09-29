import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end configuration.
 *
 * These specs drive the real application against the real API. There is no
 * mock layer and no seeded fixture server: the four defects this suite exists
 * to keep fixed — a WebSocket that never opened, a graph with overlapping
 * nodes, a register with a silently clipped column, an invalid `<p>` nesting —
 * were all invisible to 113 unit tests precisely because the unit tests render
 * components in isolation. Only a browser talking to a live backend reproduces
 * them, so the backend is a hard dependency of this suite and a missing one is
 * reported as a missing one rather than as a wall of timeouts
 * (see `e2e/global-setup.ts`).
 */

/** 4179 rather than the dev default 5173, which is frequently already held. */
const PORT = 4179;
const BASE_URL = `http://127.0.0.1:${PORT}`;

/** The API the dev-server proxy forwards `/api/*` and `/health*` to. */
const API_ORIGIN = process.env['AEGIS_API_ORIGIN'] ?? 'http://127.0.0.1:8000';

/**
 * Vite is started through its own CLI rather than a custom node wrapper so the
 * e2e run uses the same dev server, and therefore the same proxy
 * configuration, as a developer. `--strictPort` matters: without it Vite
 * silently falls back to another port, `reuseExistingServer` then probes the
 * wrong origin, and the suite reports connection failures for a server that is
 * up and healthy on 4179.
 */
const WEB_SERVER_COMMAND = `npm run dev -- --port ${PORT} --strictPort --host 127.0.0.1`;

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  forbidOnly: Boolean(process.env['CI']),
  retries: process.env['CI'] ? 1 : 0,
  workers: 1,
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never' }]] : [['list']],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 15_000,
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'laptop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
  ],
  webServer: {
    command: WEB_SERVER_COMMAND,
    url: `${BASE_URL}/`,
    reuseExistingServer: true,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: { VITE_PROXY_TARGET: API_ORIGIN },
  },
});
