/**
 * WebSocket instrumentation for the live-feed specs.
 *
 * Bug 1 — the dev proxy forwarding HTTP only — had no symptom a unit test could
 * see. `useLive` seeds its snapshot from REST and only *enhances* it with the
 * socket, so every figure on screen was correct, every unit test passed, and the
 * only evidence was a sidebar chip reading "Reconnecting" forever. The socket's
 * `connect` event never fired, and nothing anywhere raised an error.
 *
 * So the guard has to read the socket itself. This wraps the `WebSocket`
 * constructor before any application code runs and keeps a live record of every
 * socket the page opens: its URL, its current `readyState` and how many frames it
 * has received. `readyState === 1` (OPEN) is the assertion that matters — it is
 * the only place the handshake's success is observable at all.
 */

import type { Page } from '@playwright/test';

export interface TrackedSocket {
  /** The URL as the page opened it, including the proxied `/api/v1/live` path. */
  readonly url: string;
  /** `WebSocket.readyState`: 0 CONNECTING, 1 OPEN, 2 CLOSING, 3 CLOSED. */
  readonly readyState: number;
  /** Frames received. A socket that opens and then delivers nothing is not live. */
  readonly messages: number;
}

/** Only the platform feed; Vite's own HMR socket lives on `/?token=…`. */
export const LIVE_PATH = '/api/v1/live';

export interface SocketProbe {
  /** Every socket the page has opened, in the order it opened them. */
  read(): Promise<readonly TrackedSocket[]>;
  /** Just the platform feed sockets. */
  live(): Promise<readonly TrackedSocket[]>;
}

/**
 * Install the recorder. Must be called before the first navigation: the
 * constructor is patched on document load, so a socket opened by the app's very
 * first effect is captured like any other.
 */
export async function trackSockets(page: Page): Promise<SocketProbe> {
  await page.addInitScript(() => {
    interface Tracked {
      url: string;
      readyState: number;
      messages: number;
    }
    const store: Tracked[] = [];
    (window as unknown as { __aegisSockets: Tracked[] }).__aegisSockets = store;

    const Native = window.WebSocket;
    window.WebSocket = class extends Native {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        const entry: Tracked = { url: String(url), readyState: 0, messages: 0 };
        store.push(entry);
        this.addEventListener('open', () => { entry.readyState = this.readyState; });
        this.addEventListener('message', () => { entry.messages += 1; });
        this.addEventListener('close', () => { entry.readyState = this.readyState; });
        this.addEventListener('error', () => { entry.readyState = this.readyState; });
      }
    } as unknown as typeof WebSocket;
  });

  const read = async (): Promise<readonly TrackedSocket[]> =>
    page.evaluate(
      () => (window as unknown as { __aegisSockets?: TrackedSocket[] }).__aegisSockets ?? [],
    );

  return {
    read,
    live: async () => (await read()).filter((socket) => socket.url.includes(LIVE_PATH)),
  };
}
