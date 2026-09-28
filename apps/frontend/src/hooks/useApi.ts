import { useCallback, useEffect, useState } from 'react';
import { formatApiError, getJson } from '../api/client';

export interface ApiResource<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly reload: () => void;
}

/**
 * GET a JSON resource with loading / error state and abort-on-change.
 *
 * Pass `url: null` to skip the request (state resets to "no data").
 * The URL string is the effect dependency, so callers can derive it from
 * route params or form state without worrying about callback identity.
 */
export function useApi<T>(url: string | null): ApiResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(url !== null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (url === null) {
      setData(null);
      setError(null);
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    getJson<T>(url, controller.signal)
      .then((result) => {
        if (!active) return;
        setData(result);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(formatApiError(err));
        setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [url, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, loading, error, reload };
}
