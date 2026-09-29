import { useCallback, useEffect, useRef, useState } from 'react';
import { api, getApiKey, getSessionToken, liveUrl } from '../api/client';
import type { DashboardSnapshot, LiveControlFrame } from '../api/types';

/** Reconnect backoff. Doubles up to {@link MAX_RETRY_MS} so a restarted API is
 *  picked up quickly while an API that stays down is not hammered. */
const BASE_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

/**
 * Subscribe to the derived live state.
 *
 * The websocket is an optimisation, never a requirement: `snapshot` is seeded
 * from a REST call and every consumer degrades to it when `connected` is false.
 * That is why a refused socket is not an error state — the console is still
 * correct, just no longer live.
 */
export function useLive() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [degradedReason, setDegradedReason] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const refresh = useCallback(() => {
    void api.dashboard().then(setSnapshot).catch(() => undefined);
  }, []);

  useEffect(() => {
    let disposed = false;
    let retry: number | undefined;
    let attempt = 0;
    const connect = () => {
      if (disposed) return;
      const credential = getSessionToken() || getApiKey();
      // The credential rides in the handshake subprotocol so it never reaches
      // an access log or browser history the way a query parameter would.
      const socket = credential
        ? new WebSocket(liveUrl(), ['aegis', credential])
        : new WebSocket(liveUrl());
      socketRef.current = socket;
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
        setDegradedReason(null);
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as DashboardSnapshot | LiveControlFrame;
          if (payload.type === 'snapshot') {
            setSnapshot(payload);
            return;
          }
          if (payload.type === 'degraded') {
            // Keep the last good snapshot on screen and say why it is stale
            // rather than blanking the console on a transient database fault.
            setDegradedReason(
              payload.detail ?? 'Live updates are delayed — the platform is degraded.',
            );
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onerror = () => setConnected(false);
      socket.onclose = () => {
        setConnected(false);
        if (disposed) return;
        const delay = Math.min(BASE_RETRY_MS * 2 ** attempt, MAX_RETRY_MS);
        attempt += 1;
        retry = window.setTimeout(connect, delay);
      };
    };
    refresh();
    connect();
    return () => {
      disposed = true;
      if (retry !== undefined) window.clearTimeout(retry);
      socketRef.current?.close();
    };
  }, [refresh]);
  return { snapshot, connected, degradedReason, refresh };
}
