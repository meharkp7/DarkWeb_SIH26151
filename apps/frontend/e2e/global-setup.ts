import { API_ORIGIN, ANALYST_EMAIL } from './fixtures/environment';

/**
 * Preconditions for the whole run.
 *
 * The suite drives the real application against the real API, so a missing API
 * is the single most likely reason for the run to fail. Reported here, once, as
 * a sentence; left to Playwright it becomes an identical stack of timeouts on
 * every test in every project, which reads like a broken suite rather than a
 * missing service.
 */
const API_PROBE_TIMEOUT_MS = 5_000;

async function assertApiReachable(): Promise<void> {
  const failures: string[] = [];
  for (const path of ['/health', '/openapi.json']) {
    try {
      const response = await fetch(`${API_ORIGIN}${path}`, {
        signal: AbortSignal.timeout(API_PROBE_TIMEOUT_MS),
      });
      if (response.status >= 500) failures.push(`${path} answered ${response.status}`);
    } catch (error) {
      failures.push(`${path} unreachable (${(error as Error).message})`);
    }
  }

  if (failures.length > 0) {
    throw new Error(
      [
        '',
        'AEGIS e2e requires a running API.',
        '',
        `  Expected it at : ${API_ORIGIN}`,
        `  Observed:       ${failures.join('; ')}`,
        '',
        'Start it with:  make run      (uvicorn aegis.api.app:app --port 8000)',
        'Or point the suite elsewhere with AEGIS_API_ORIGIN=http://host:port.',
        '',
      ].join('\n'),
    );
  }
}

async function assertWebServerIsAegis(baseUrl: string): Promise<void> {
  try {
    const response = await fetch(`${baseUrl}/`, { signal: AbortSignal.timeout(API_PROBE_TIMEOUT_MS) });
    const html = await response.text();
    if (!html.includes('AEGIS')) {
      throw new Error(
        `${baseUrl} is serving something other than the AEGIS frontend. ` +
          'Another process is holding the e2e port; free it and re-run.',
      );
    }
  } catch (error) {
    if ((error as Error).message.includes('other than the AEGIS frontend')) throw error;
    throw new Error(
      `The Playwright web server did not come up on ${baseUrl}: ${(error as Error).message}`,
    );
  }
}

export default async function globalSetup(): Promise<void> {
  await assertApiReachable();

  // `reuseExistingServer` means the port may have been served by a previous
  // run's Vite; confirm it is this app before the first test trusts it.
  await assertWebServerIsAegis('http://127.0.0.1:4179');

  if (ANALYST_EMAIL.trim() === '') {
    throw new Error('No analyst email resolved; set AEGIS_E2E_EMAIL or AEGIS_AUTH_EMAIL.');
  }
  // Printed once so a failing auth spec can be read against the identity that
  // was actually used.
  console.log(`[e2e] API ${API_ORIGIN} · analyst ${ANALYST_EMAIL}`);
}
