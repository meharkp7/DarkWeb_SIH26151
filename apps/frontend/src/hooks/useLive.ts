import { useCallback, useEffect, useRef, useState } from 'react';
import { api, getApiKey, getSessionToken, liveUrl } from '../api/client';
import type { DashboardSnapshot } from '../api/types';

export function useLive() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const refresh = useCallback(() => { void api.dashboard().then(setSnapshot).catch(() => undefined); }, []);

  useEffect(() => {
    let disposed = false;
    let retry: number | undefined;
    const connect = () => {
      if (disposed) return;
      const credential = getSessionToken() || getApiKey();
      const socket = credential ? new WebSocket(liveUrl(), ['aegis', credential]) : new WebSocket(liveUrl());
      socketRef.current = socket;
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => { try { const payload = JSON.parse(event.data) as DashboardSnapshot; if (payload.type === 'snapshot') setSnapshot(payload); } catch { /* ignore malformed frames */ } };
      socket.onerror = () => setConnected(false);
      socket.onclose = () => { setConnected(false); if (!disposed) retry = window.setTimeout(connect, 2500); };
    };
    refresh();
    connect();
    return () => { disposed = true; if (retry) window.clearTimeout(retry); socketRef.current?.close(); };
  }, [refresh]);
  return { snapshot, connected, refresh };
}
