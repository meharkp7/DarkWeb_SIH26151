import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

/**
 * Where the API listens.
 *
 * The e2e suite is only meaningful against a live API, so the address is
 * resolved the same way `vite.config.ts` resolves its proxy target and is
 * overridable with the same variable.
 */
export const API_ORIGIN = process.env['AEGIS_API_ORIGIN'] ?? 'http://127.0.0.1:8000';

/**
 * Locate the repository-root `.env`.
 *
 * The API reads its analyst credential from that file at startup, so the suite
 * reads it from the same place rather than from a second copy of the value
 * that can drift out of sync with the running server.
 */
function findRepoEnv(): Record<string, string> {
  const candidates = [
    process.env['AEGIS_ENV_FILE'],
    path.resolve(process.cwd(), '../../.env'),
    path.resolve(process.cwd(), '../.env'),
    path.resolve(process.cwd(), '.env'),
  ].filter((candidate): candidate is string => typeof candidate === 'string');

  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue;
    const values: Record<string, string> = {};
    for (const line of readFileSync(candidate, 'utf8').split('\n')) {
      const match = /^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)$/.exec(line);
      if (match?.[1] === undefined) continue;
      let value = (match[2] ?? '').trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      values[match[1]] = value;
    }
    return values;
  }
  return {};
}

const fromEnvFile = findRepoEnv();

/**
 * The analyst the suite signs in as.
 *
 * Precedence is explicit override → the API's own `.env` → the documented demo
 * default. A missing credential must fail here, loudly, rather than as a
 * login form that silently never authenticates.
 */
export const ANALYST_EMAIL =
  process.env['AEGIS_E2E_EMAIL'] ?? fromEnvFile['AEGIS_AUTH_EMAIL'] ?? 'analyst@aegis-intelligence.com';

export const ANALYST_PASSWORD =
  process.env['AEGIS_E2E_PASSWORD'] ?? fromEnvFile['AEGIS_AUTH_PASSWORD'] ?? 'AEGIS-Demo-2026!';
