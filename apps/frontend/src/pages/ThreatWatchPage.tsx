import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { authHeaders } from '../api/client';
import { useLive } from '../hooks/useLive';
import { formatDateTime } from '../lib/format';
import type { LiveActivity } from '../api/types';

/**
 * Threat Watch is the operational stream: what changed, on which case, and
 * how urgently.
 *
 * It reads two sources on purpose. The websocket snapshot is the live tail and
 * updates in place; `GET /api/v1/threat-watch/events` is the durable stream
 * with a larger window. Showing only the socket would leave the screen empty
 * whenever the feed is down, which is exactly when an analyst most needs to
 * see what has already been recorded.
 */
const FILTER = {
  all: () => true,
  critical: (item: LiveActivity) => severity(item) === 'critical',
  elevated: (item: LiveActivity) => severity(item) !== 'normal',
  relationship: (item: LiveActivity) => item.action.startsWith('relationship.') || item.action.startsWith('entity.'),
  evidence: (item: LiveActivity) => item.action.startsWith('evidence.'),
  attribution: (item: LiveActivity) => item.action.startsWith('assessment.') || item.action.startsWith('threat.attribution'),
} as const;

type FilterKey = keyof typeof FILTER;

const FILTERS: ReadonlyArray<readonly [FilterKey, string]> = [
  ['all', 'all events'],
  ['critical', 'critical'],
  ['elevated', 'elevated'],
  ['relationship', 'relationships'],
  ['evidence', 'evidence'],
  ['attribution', 'attribution'],
];

/**
 * Severity comes from the recorded payload when the producer set one, and
 * falls back to the action name. A stream where severity is guessed from a
 * substring is a stream where a new action silently arrives as "normal".
 */
export function severity(item: LiveActivity): 'critical' | 'elevated' | 'normal' {
  const declared = item.payload['severity'];
  if (declared === 'critical' || declared === 'high') return 'critical';
  if (declared === 'warning') return 'elevated';
  if (item.action.startsWith('alert.')) return 'critical';
  if (item.action.startsWith('threat.')) return 'elevated';
  return 'normal';
}

function label(item: LiveActivity): string {
  return String(item.payload['message'] ?? item.action.replaceAll('.', ' '));
}

function caseName(item: LiveActivity): string | null {
  const name = item.payload['case_name'];
  return typeof name === 'string' ? name : null;
}

function counts(rows: readonly LiveActivity[]) {
  return {
    critical: rows.filter((item) => severity(item) === 'critical').length,
    elevated: rows.filter((item) => severity(item) === 'elevated').length,
    relationships: rows.filter((item) => item.action.startsWith('relationship.') || item.action.startsWith('entity.')).length,
    evidence: rows.filter((item) => item.action.startsWith('evidence.')).length,
  };
}

export function ThreatWatchPage() {
  const { snapshot, connected, degradedReason } = useLive();
  const [params, setParams] = useSearchParams();
  const [backlog, setBacklog] = useState<readonly LiveActivity[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  const filterParam = params.get('filter');
  const filter: FilterKey = filterParam !== null && filterParam in FILTER
    ? (filterParam as FilterKey)
    : 'all';

  // The durable stream, refreshed whenever the caller asks or the filter
  // changes. Failures are silent by design: the socket tail is still live, and
  // an error banner here would compete with the degraded-feed notice the
  // shell already shows for the real failure case.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        // A bare `fetch` cannot carry the Authorization header, so this would
        // 401 and leave the durable stream permanently empty. The shared
        // header set is the reason a single authenticated client exists.
        const response = await fetch('/api/v1/threat-watch/events?limit=80', {
          credentials: 'include',
          headers: { ...authHeaders(), Accept: 'application/json' },
        });
        if (!response.ok) return;
        const body = (await response.json()) as readonly LiveActivity[];
        if (!cancelled) setBacklog(body);
      } catch {
        /* socket tail remains authoritative */
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [reloadKey]);

  // Merge by `seq` so an event seen on both paths is not listed twice.
  const rows = useMemo(() => {
    const merged = new Map<number, LiveActivity>();
    for (const item of [...(snapshot?.activity ?? []), ...backlog]) {
      if (!merged.has(item.seq)) merged.set(item.seq, item);
    }
    return [...merged.values()].sort((a, b) => b.seq - a.seq);
  }, [snapshot, backlog]);

  const totals = useMemo(() => counts(rows), [rows]);
  const filtered = useMemo(() => rows.filter(FILTER[filter]), [rows, filter]);
  const setFilter = (next: FilterKey) => {
    const updated = new URLSearchParams(params);
    if (next === 'all') updated.delete('filter');
    else updated.set('filter', next);
    setParams(updated, { replace: true });
  };

  return (
    <div className="page-stack watch-page">
      <header className="watch-hero">
        <div>
          <span className="eyebrow">Continuous monitoring / live channel</span>
          <h1>Threat <i>Watch.</i></h1>
          <p>Watch the investigation state change in real time. Every event remains tied to its case and audit record.</p>
        </div>
        <div className="watch-live-card">
          <span className={connected ? 'live-dot live-dot--on' : 'live-dot'} />
          <div>
            <b>{connected ? 'Streaming' : 'Replaying recorded events'}</b>
            <small>{rows.length} events in current window</small>
          </div>
        </div>
      </header>

      {degradedReason ? <p className="watch-degraded" role="status">{degradedReason}</p> : null}

      <section className="watch-summary">
        {FILTERS.map(([key, labelText]) => {
          const value = key === 'all' ? rows.length
            : key === 'critical' ? totals.critical
            : key === 'elevated' ? totals.elevated
            : key === 'relationship' ? totals.relationships
            : totals.evidence;
          return (
            <button
              key={key}
              type="button"
              className={filter === key ? 'is-active' : ''}
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              <b>{value}</b>
              <span>{labelText}</span>
            </button>
          );
        })}
      </section>

      <section className="watch-layout">
        <div className="watch-stream">
          <div className="watch-stream__head"><span>Event</span><span>Case</span><span>Time</span></div>
          {filtered.map((item) => {
            const level = severity(item);
            const name = caseName(item);
            return (
              <Link
                to={item.case_id ? `/cases/${item.case_id}` : '/threat-watch'}
                className={`watch-event watch-event--${level}`}
                key={item.seq}
              >
                <div className="watch-event__main">
                  {/* The glyph and the word both carry the level: a colour
                      alone tells a colourblind analyst nothing, and nothing at
                      all to a screen reader. */}
                  <span className="watch-event__marker" aria-hidden="true">
                    {level === 'critical' ? '!' : level === 'elevated' ? '↗' : '·'}
                  </span>
                  <div>
                    <b>{label(item)}</b>
                    <small>
                      <span className="sr-only">{level} severity. </span>
                      {level.toUpperCase()} · {item.action.replaceAll('.', ' / ')}
                    </small>
                  </div>
                </div>
                <span className="watch-event__case">
                  {name ?? (item.case_id ? item.case_id.slice(0, 8).toUpperCase() : 'SYSTEM')}
                </span>
                <span className="watch-event__time">
                  {formatDateTime(item.occurred_at)}
                  <small>#{item.seq}</small>
                </span>
              </Link>
            );
          })}
          {filtered.length === 0 && (
            <div className="watch-empty">
              No events match this filter.{' '}
              <button type="button" className="link-button" onClick={() => setReloadKey((k) => k + 1)}>
                Replay recorded events
              </button>
            </div>
          )}
        </div>

        <aside className="watch-aside">
          <div className="watch-aside__head"><span className="eyebrow">Signal posture</span><b>Now</b></div>
          <div className="watch-meter"><span>Critical events</span><b>{totals.critical}</b><i><em style={{ width: `${Math.min(100, totals.critical * 12)}%` }} /></i></div>
          <div className="watch-meter"><span>Elevated events</span><b>{totals.elevated}</b><i><em style={{ width: `${Math.min(100, totals.elevated * 10)}%` }} /></i></div>
          <div className="watch-meter"><span>Relationship movement</span><b>{totals.relationships}</b><i><em style={{ width: `${Math.min(100, totals.relationships * 10)}%` }} /></i></div>
          <div className="watch-meter"><span>Evidence movement</span><b>{totals.evidence}</b><i><em style={{ width: `${Math.min(100, totals.evidence * 10)}%` }} /></i></div>
          <div className="watch-note"><span>Operational note</span><p>Signals are synthetic demonstration data. Follow the linked case to inspect provenance before drawing conclusions.</p></div>
        </aside>
      </section>
    </div>
  );
}
