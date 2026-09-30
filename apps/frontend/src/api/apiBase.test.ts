import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { installFetch, jsonResponse } from '../test/mockFetch';

/**
 * The API base is decided in exactly one place.
 *
 * The console is served from Vercel and the API runs on Render, so a request
 * built from a same-origin literal (`/api/v1/...`) resolves against the static
 * host and comes back 404 — while the route exists, the backend log stays
 * empty, and the failure is invisible from the API side. Every other page has
 * used `apiUrl` from the start, which is why only two screens broke; nothing in
 * the type system or the test suite caught it, because `/api/v1/...` is a
 * perfectly valid URL to construct.
 *
 * So this is a source-level guard rather than a behavioural one. It asserts the
 * *absence* of a construct, which no runtime test can do.
 */
// `import.meta.url`, not `location`: this file runs in jsdom, where
// `self.location` is `http://localhost/` and resolves to the filesystem root.
const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(path));
    else if (/\.tsx?$/.test(entry.name)) out.push(path);
  }
  return out;
}

/**
 * A hardcoded API path: a string literal that *begins* with `/api/`.
 *
 * Anchored at the opening quote so a longer path that merely contains the
 * prefix (`apiUrl('/v1/...')`, or a test asserting on a captured URL) is not
 * flagged. Template literals are included because the infrastructure page built
 * its URLs that way.
 */
const HARDCODED_API_PATH = /(['"`])\/api\//;

describe('API base discipline', () => {
  it('never hardcodes an /api path outside the base-URL module', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SOURCE_ROOT)) {
      if (file.endsWith('.test.ts') || file.endsWith('.test.tsx')) continue;
      // Ambient declarations are documentation. `vite-env.d.ts` describes
      // `VITE_API_BASE` as "base URL for `/api/v1/*` routes", which is a
      // description of the base, not a URL being built.
      if (file.endsWith('.d.ts')) continue;
      // `client.ts` is where the base is *defined*; `apiUrl` is what consumes
      // it. Everything else must go through the helper.
      if (file.endsWith(`${join('api', 'client.ts')}`)) continue;

      const text = readFileSync(file, 'utf8');
      text.split('\n').forEach((line, index) => {
        // A comment explaining the rule is not a violation of it.
        if (line.trimStart().startsWith('*') || line.trimStart().startsWith('//')) return;
        if (HARDCODED_API_PATH.test(line)) offenders.push(`${file}:${index + 1}`);
      });
    }

    expect(
      offenders,
      `these files build URLs from a literal /api path, which bypasses VITE_API_BASE and 404s in production:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('serves Threat Watch from the shared client so the bearer token is attached', async () => {
    // The durable stream sits behind the auth middleware. A bare `fetch` here
    // would 401 and leave the page permanently empty for a reason nothing on
    // screen would explain — the previous implementation did exactly that,
    // then swallowed the error, so it looked like "no events yet".
    const fetchMock = installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/v1/threat-watch/events')) return jsonResponse([]);
      return jsonResponse({});
    });

    const { getJson } = await import('./client');
    await getJson('/v1/threat-watch/events?limit=120');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toBeDefined();
  });
});
