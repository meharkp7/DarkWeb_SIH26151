import { useEffect, useState } from 'react';
import { api, formatApiError, healthUrl } from '../api/client';
import type { HealthResponse } from '../api/types';
import { useApi } from '../hooks/useApi';
import { cx, formatClock } from '../lib/format';

type Phase = 'checking' | 'ok' | 'down';

interface ProbeState {
  phase: Phase;
  service: string | null;
  message: string | null;
  checkedAt: Date | null;
}

const POLL_INTERVAL_MS = 15_000;

function chipClass(phase: Phase): string {
  return cx('health__dot', `health__dot--${phase}`);
}

function phaseLabel(phase: Phase): string {
  if (phase === 'checking') return 'checking';
  if (phase === 'ok') return 'ok';
  return 'unreachable';
}

/**
 * Header status indicator: polls `GET /health` every 15s and probes
 * `GET /health/db` once per mount.
 */
export function HealthIndicator() {
  const [apiProbe, setApiProbe] = useState<ProbeState>({
    phase: 'checking',
    service: null,
    message: null,
    checkedAt: null,
  });
  const db = useApi<HealthResponse>(healthUrl('/db'));

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    const probe = () => {
      api
        .health(controller.signal)
        .then((result) => {
          if (!active) return;
          const healthy = result.status === 'ok';
          setApiProbe({
            phase: healthy ? 'ok' : 'down',
            service: result.service,
            message: healthy ? null : `status=${result.status}`,
            checkedAt: new Date(),
          });
        })
        .catch((error: unknown) => {
          if (!active) return;
          setApiProbe({
            phase: 'down',
            service: null,
            message: formatApiError(error),
            checkedAt: new Date(),
          });
        });
    };

    probe();
    const timer = window.setInterval(probe, POLL_INTERVAL_MS);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  const dbPhase: Phase = db.loading ? 'checking' : db.error === null ? 'ok' : 'down';
  const dbTitle = db.error ?? (db.data ? `${db.data.service} ${db.data.status}` : 'Checking…');

  return (
    <div className="health" role="status" aria-live="polite">
      <span className="health__item" title={apiProbe.message ?? 'GET /health'}>
        <span className={chipClass(apiProbe.phase)} aria-hidden="true" />
        <span className="health__label">API {phaseLabel(apiProbe.phase)}</span>
        {apiProbe.service !== null && <span className="health__service">{apiProbe.service}</span>}
      </span>
      <span className="health__sep" aria-hidden="true">
        ·
      </span>
      <span className="health__item" title={dbTitle}>
        <span className={chipClass(dbPhase)} aria-hidden="true" />
        <span className="health__label">DB {phaseLabel(dbPhase)}</span>
      </span>
      {apiProbe.checkedAt !== null && (
        <span className="health__time">
          checked{' '}
          <time dateTime={apiProbe.checkedAt.toISOString()}>{formatClock(apiProbe.checkedAt)}</time>
        </span>
      )}
    </div>
  );
}
