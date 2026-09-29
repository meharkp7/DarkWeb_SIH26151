import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { installFetch, rejectAllFetch } from './mockFetch';

/**
 * Test setup for the frontend suite.
 *
 * - Register the jest-dom matchers (`toBeInTheDocument`, …).
 * - Unmount rendered trees and restore stubbed globals after every test.
 * - Install a fetch guard so an un-stubbed request never reaches the network.
 * - Provide a no-op WebSocket: `AppShell` opens a live feed socket on mount,
 *   and neither jsdom nor Node 20 ships a usable WebSocket global.
 */

// No-op WebSocket so `useLive` (AppShell, Command Center, CaseWorkspace) can
// mount without dialling out or scheduling reconnect timers.
class StubWebSocket {
  readonly url: string;
  readonly readyState = 0;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  close(): void {}
  send(): void {}
}

globalThis.WebSocket = StubWebSocket as unknown as typeof WebSocket;

beforeEach(() => {
  installFetch(rejectAllFetch);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});