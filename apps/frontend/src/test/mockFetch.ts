import { vi } from 'vitest';

/**
 * Small fetch-stubbing helpers shared by the test suite.
 *
 * The suite's policy is: never hit the network — every test installs a fetch
 * stub (via `installFetch`) and the setup file installs a failing guard as the
 * default, so an un-stubbed request fails loudly instead of leaking to the
 * network.
 */

export interface StubJsonInit {
  readonly status?: number;
  readonly statusText?: string;
}

/**
 * A minimal Response-shaped object sufficient for `client.ts` (it only reads
 * `ok`, `status`, `statusText` and `json()`). Avoids depending on which
 * Response implementation (Node vs jsdom) is present in the test env.
 */
export function jsonResponse(body: unknown, init: StubJsonInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: init.statusText ?? (status >= 200 && status < 300 ? 'OK' : 'Error'),
    json: async () => body,
  } as unknown as Response;
}

/** A response whose body is not JSON, so `response.json()` rejects. */
export function nonJsonResponse(status: number, statusText: string): Response {
  return {
    ok: false,
    status,
    statusText,
    json: async () => {
      throw new SyntaxError('Unexpected token < in JSON at position 0');
    },
  } as unknown as Response;
}

export type FetchInput = Parameters<typeof fetch>[0];

export type FetchHandler = (
  input: FetchInput,
  init?: RequestInit,
) => Promise<Response> | Response;

/**
 * Replace the global fetch with a vi.fn() around `handler` for one test.
 * `vi.unstubAllGlobals()` (run in the setup file's afterEach) restores the
 * real global afterwards.
 */
export function installFetch(handler: FetchHandler): ReturnType<typeof vi.fn> {
  const mock = vi.fn(handler);
  vi.stubGlobal('fetch', mock);
  return mock;
}

/** Default guard: any request that was not explicitly stubbed fails hard. */
export const rejectAllFetch: FetchHandler = async () => {
  throw new Error(
    'Unexpected fetch() in tests — no fetch stub installed for this request.',
  );
};