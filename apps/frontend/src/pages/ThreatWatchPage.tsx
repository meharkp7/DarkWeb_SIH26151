import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { apiUrl, formatApiError, getJson } from '../api/client';
import { useLive } from '../hooks/useLive';
import { formatDateTime, shortId } from '../lib/format';
import type { LiveActivity } from '../api/types';
import { Badge } from '../components/Badge';
import { InspectorRail } from '../components/InspectorRail';
import type { InspectorFact, InspectorStatus } from '../components/InspectorRail';
import { usePublishAgentContext } from '../components/agent-context';

/**
 * Threat Watch is the operational stream: what changed, on which case, and how
 * urgently.
 *
 * It reads two sources on purpose. The websocket snapshot is the live tail and
 * updates in place; `GET /api/v1/threat-watch/events` is the durable stream
 * with a larger window. Showing only the socket would leave the screen empty
 * whenever the feed is down, which is exactly when an analyst most needs to
 * see what has already been recorded.
 *
 * Every URL goes through `apiUrl`. The console is served from Vercel while the
 * API runs on Render, so a same-origin literal resolves against the static host
 * and 404s — the route exists, the request simply never reaches it.
 */

/** How many events the durable stream is asked for. */
const BACKLOG_LIMIT = 120;

export type Severity = 'critical' | 'elevated' | 'normal';

/**
 * Actions, grouped into the categories an analyst triages by.
 *
 * The prefix is the contract: a producer decides an event's urgency by naming
 * it `alert.*` or `threat.*`, and a new verb under a known prefix is picked up
 * for free. A stream that required every new action to be registered here would
 * quietly file the first new verb as "normal", which is the failure mode this
 * grouping exists to prevent.
 */
const CATEGORIES = [
  { id: 'alert', label: 'Alerts', match: (action: string) => action.startsWith('alert.') || action.startsWith('threat.') },
  { id: 'evidence', label: 'Evidence', match: (action: string) => action.startsWith('evidence.') || action.startsWith('collection.') || action.startsWith('source.') },
  { id: 'linkage', label: 'Linkage', match: (action: string) => action.startsWith('relationship.') || action.startsWith('entity.') || action.startsWith('hypothesis.') },
  { id: 'attribution', label: 'Attribution', match: (action: string) => action.startsWith('assessment.') || action.startsWith('actor.') || action.startsWith('persona.') },
  { id: 'admin', label: 'Administration', match: (action: string) => action.startsWith('admin.') || action.startsWith('auth.') || action.startsWith('case.') },
] as const;

/**
 * The fallback bucket. An action matching no known prefix is *not* filed under
 * the first category and given a plausible-looking label — that would attribute
 * a change to a team that did not make it. It goes to "Other", visibly.
 */
const OTHER_CATEGORY = { id: 'other', label: 'Other', match: () => true } as const;

function categoryFor(action: string): (typeof CATEGORIES)[number] | typeof OTHER_CATEGORY {
  return CATEGORIES.find((category) => category.match(action)) ?? OTHER_CATEGORY;
}

/**
 * The two filter shapes, kept apart on purpose.
 *
 * A category is a property of the *action name*, so it is a function of the
 * string. A severity is a property of the event, because a producer may set
 * the recorded severity in the payload independently of the verb. Writing both
 * as one signature is how a category filter ends up testing
 * `item.action.startsWith('evidence.')` against a `LiveActivity` — always
 * false, and silent about it.
 *
 * Both are normalised to a single predicate at construction, so the filter
 * loop below has exactly one shape to handle and no union to narrow.
 */
const SEVERITY_FILTERS = [
  { id: 'all', label: 'All events', matches: (_item: LiveActivity) => true },
  { id: 'critical', label: 'Critical', matches: (item: LiveActivity) => severity(item) === 'critical' },
  { id: 'elevated', label: 'Elevated', matches: (item: LiveActivity) => severity(item) === 'elevated' },
] as const;

const CATEGORY_FILTERS = [
  ...CATEGORIES.map((category) => ({
    id: category.id,
    label: category.label,
    matches: (item: LiveActivity) => category.match(item.action),
  })),
  {
    id: 'other',
    label: 'Other',
    matches: (item: LiveActivity) => categoryFor(item.action).id === 'other',
  },
] as const;

const FILTERS = [...SEVERITY_FILTERS, ...CATEGORY_FILTERS];

type FilterId = (typeof FILTERS)[number]['id'];

function isFilter(value: string | null): value is FilterId {
  return value !== null && FILTERS.some((filter) => filter.id === value);
}

/**
 * Severity comes from the recorded payload when the producer set one, and
 * falls back to the action name. A stream where severity is guessed from a
 * substring is a stream where a new action silently arrives as "normal".
 */
export function severity(item: LiveActivity): Severity {
  const declared = item.payload['severity'];
  if (declared === 'critical' || declared === 'high') return 'critical';
  if (declared === 'warning') return 'elevated';
  if (item.action.startsWith('alert.')) return 'critical';
  if (item.action.startsWith('threat.')) return 'elevated';
  return 'normal';
}

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'Critical',
  elevated: 'Elevated',
  normal: 'Normal',
};

const SEVERITY_TONE: Record<Severity, 'danger' | 'warn' | 'muted'> = {
  critical: 'danger',
  elevated: 'warn',
  normal: 'muted',
};

function label(item: LiveActivity): string {
  const message = item.payload['message'];
  if (typeof message === 'string' && message !== '') return message;
  return item.action.replaceAll('.', ' ');
}

/**
 * The specific thing the event is about, in the analyst's vocabulary.
 *
 * Producers put different keys in the payload depending on the action, so this
 * checks them in order of how much they identify the subject. Falling back to
 * the action name is honest; falling back to "an event" is not.
 */
function subjectOf(item: LiveActivity): string | null {
  for (const key of ['entity_name', 'actor_name', 'case_name', 'target', 'subject', 'label', 'title']) {
    const value = item.payload[key];
    if (typeof value === 'string' && value !== '') return value;
  }
  return null;
}

function caseName(item: LiveActivity): string | null {
  const name = item.payload['case_name'];
  return typeof name === 'string' && name !== '' ? name : null;
}

function isFlagged(item: LiveActivity | null): boolean {
  if (item === null) return false;
  return item.payload['flagged'] === true || item.payload['injected'] === true;
}

/**
 * Reads a payload field as displayable text, so the inspector can show whatever
 * the producer recorded without hard-coding the schema. Objects and arrays are
 * rendered as compact JSON rather than as `[object Object]`.
 */
function payloadText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value === '' ? null : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    const parts = value.map(payloadText).filter((part): part is string => part !== null);
    return parts.length === 0 ? null : parts.join(', ');
  }
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return null;
}

/** Payload keys promoted to inspector facts, in display order. */
const PROMOTED_KEYS = [
  'entity_name',
  'actor_name',
  'target',
  'subject',
  'case_name',
  'network',
  'source',
  'confidence',
  'method',
  'reason',
  'detail',
] as const;

function useThreatWatchBacklog(reloadKey: number) {
  const [backlog, setBacklog] = useState<readonly LiveActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    // `getJson` rather than a bare `fetch`: the durable stream is behind the
    // auth middleware, and a request without the bearer token comes back 401
    // and leaves this page permanently empty for a reason nothing on screen
    // would explain.
    getJson<LiveActivity[]>(apiUrl(`/v1/threat-watch/events?limit=${BACKLOG_LIMIT}`), controller.signal)
      .then((rows) => {
        if (!active) return;
        setBacklog(rows);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(formatApiError(cause));
        setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadKey]);

  return { backlog, loading, error };
}

export function ThreatWatchPage() {
  const { snapshot, connected, degradedReason } = useLive();
  const [params, setParams] = useSearchParams();
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);

  usePublishAgentContext({ place: 'Threat Watch' });

  const { backlog, loading, error } = useThreatWatchBacklog(reloadKey);

  const filterParam = params.get('filter');
  const filter: FilterId = isFilter(filterParam) ? filterParam : 'all';
  const caseFilter = params.get('case') ?? '';

  // Merge by `seq` so an event seen on both paths is not listed twice. The
  // socket tail is the live edge; the backlog is the durable window behind it.
  const rows = useMemo(() => {
    const merged = new Map<number, LiveActivity>();
    for (const item of [...(snapshot?.activity ?? []), ...backlog]) {
      if (!merged.has(item.seq)) merged.set(item.seq, item);
    }
    return [...merged.values()].sort((a, b) => b.seq - a.seq);
  }, [snapshot, backlog]);

  // Counts are computed over the whole window, not the filtered slice, so the
  // strip keeps reporting the shape of the feed while a filter is applied.
  const totals = useMemo(() => {
    const counts: Record<FilterId, number> = {
      all: rows.length,
      critical: 0,
      elevated: 0,
      alert: 0,
      evidence: 0,
      linkage: 0,
      attribution: 0,
      admin: 0,
      other: 0,
    };
    for (const item of rows) {
      const level = severity(item);
      if (level === 'critical') counts.critical += 1;
      if (level !== 'normal') counts.elevated += 1;
      const category = categoryFor(item.action);
      if (category.id !== 'other') counts[category.id] += 1;
      else counts.other += 1;
    }
    return counts;
  }, [rows]);

  const caseScoped = useMemo(
    () => (caseFilter === '' ? rows : rows.filter((item) => item.case_id === caseFilter)),
    [rows, caseFilter],
  );

  const filtered = useMemo(() => {
    const active = FILTERS.find((entry) => entry.id === filter);
    // `FILTERS` covers every `FilterId`, so `active` is only undefined if the
    // address bar holds a value this build no longer knows. Falling back to
    // "show everything" beats rendering an empty stream for a stale query
    // parameter, which is indistinguishable from a genuinely empty feed.
    if (active === undefined) return caseScoped;
    return caseScoped.filter(active.matches);
  }, [caseScoped, filter]);

  const cases = useMemo(() => {
    const seen = new Map<string, string>();
    for (const item of rows) {
      if (item.case_id === null) continue;
      seen.set(item.case_id, caseName(item) ?? shortId(item.case_id));
    }
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);

  const selected = useMemo(
    () => (selectedSeq === null ? null : rows.find((item) => item.seq === selectedSeq) ?? null),
    [rows, selectedSeq],
  );

  const patch = useCallback(
    (next: Record<string, string | null>): void => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          for (const [key, value] of Object.entries(next)) {
            if (value === null || value === '') updated.delete(key);
            else updated.set(key, value);
          }
          return updated;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // Selecting an event that a filter change removes must not leave the rail
  // open on an event the list no longer shows.
  useEffect(() => {
    if (selectedSeq === null) return;
    if (!filtered.some((item) => item.seq === selectedSeq)) setSelectedSeq(null);
  }, [filtered, selectedSeq]);

  const inspectorStatus: InspectorStatus[] | undefined = selected
    ? [
        { label: SEVERITY_LABEL[severity(selected)], tone: SEVERITY_TONE[severity(selected)] },
        { label: categoryFor(selected.action).label, tone: 'muted' },
      ]
    : undefined;

  const inspectorFacts: InspectorFact[] = selected
    ? [
        { label: 'Event', value: label(selected) },
        { label: 'Action', value: selected.action, mono: true },
        {
          label: 'Recorded',
          value: `${formatDateTime(selected.occurred_at)} · #${selected.seq}`,
        },
        ...(selected.case_id !== null
          ? [
              {
                label: 'Case',
                value: (
                  <Link to={`/cases/${selected.case_id}`} className="watch-inspector__case">
                    {caseName(selected) ?? shortId(selected.case_id)}
                  </Link>
                ),
              },
            ]
          : []),
        ...(selected.entity_type !== null || selected.entity_id !== null
          ? [
              {
                label: 'Entity',
                value:
                  selected.entity_type !== null && selected.entity_id !== null
                    ? `${selected.entity_type} · ${shortId(selected.entity_id)}`
                    : (selected.entity_id ?? selected.entity_type ?? '—'),
                mono: true,
              },
            ]
          : []),
        ...PROMOTED_KEYS.filter((key) => key !== 'case_name' && payloadText(selected.payload[key]) !== null).map(
          (key) => ({
            label: key.replaceAll('_', ' '),
            value: payloadText(selected.payload[key]) ?? '—',
          }),
        ),
      ]
    : [];

  // Everything the producer recorded, so an action can be understood even when
  // this page has never seen its key. Rendered as text, never as markup.
  const inspectorPayload = selected
    ? Object.entries(selected.payload).filter(([key]) => key !== 'case_name')
    : [];

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
      {error !== null ? (
        <p className="watch-degraded" role="alert">
          The recorded event stream could not be read: {error}{' '}
          <button type="button" className="link-button" onClick={() => setReloadKey((key) => key + 1)}>
            Retry
          </button>
        </p>
      ) : null}

      <section className="watch-summary" aria-label="Event counts">
        {SEVERITY_FILTERS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={filter === entry.id ? 'is-active' : ''}
            aria-pressed={filter === entry.id}
            onClick={() => patch({ filter: entry.id === 'all' ? null : entry.id })}
          >
            <b className={entry.id === 'critical' ? 'is-danger' : entry.id === 'elevated' ? 'is-blue' : undefined}>
              {totals[entry.id]}
            </b>
            <span>{entry.label}</span>
          </button>
        ))}
        <div className="watch-summary__static">
          <b className="is-green">{Math.max(0, rows.length - totals.elevated)}</b>
          <span>routine</span>
        </div>
      </section>

      <div className="watch-filters">
        <div className="watch-filters__group" role="group" aria-label="Filter by category">
          {CATEGORY_FILTERS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={filter === entry.id ? 'is-active' : ''}
              aria-pressed={filter === entry.id}
              onClick={() => patch({ filter: entry.id })}
            >
              {entry.label}
              <b>{totals[entry.id]}</b>
            </button>
          ))}
        </div>
        <div className="watch-filters__case">
          <label className="sr-only" htmlFor="watch-case">Filter by case</label>
          <select
            id="watch-case"
            value={caseFilter}
            onChange={(event) => patch({ case: event.target.value === '' ? null : event.target.value })}
          >
            <option value="">All cases</option>
            {cases.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <section className={selected !== null ? 'watch-layout has-inspector' : 'watch-layout'}>
        <div className="watch-stream">
          <div className="watch-stream__head">
            <span>Event</span>
            <span>Case</span>
            <span>Time</span>
          </div>
          {loading && rows.length === 0 ? (
            <div className="watch-empty" role="status">
              <span className="spinner" aria-hidden="true" /> Reading the recorded event stream…
            </div>
          ) : null}
          {!loading && filtered.length === 0 ? (
            <div className="watch-empty">
              {rows.length === 0
                ? 'No events have been recorded yet. Anything the platform does will appear here as it happens.'
                : 'No events match this filter. '}
              {rows.length > 0 ? (
                <button type="button" className="link-button" onClick={() => setReloadKey((key) => key + 1)}>
                  Replay recorded events
                </button>
              ) : null}
            </div>
          ) : null}
          {filtered.map((item) => {
            const level = severity(item);
            const name = caseName(item);
            const subject = subjectOf(item);
            const category = categoryFor(item.action);
            return (
              <button
                type="button"
                className={[
                  'watch-event',
                  `watch-event--${level}`,
                  selectedSeq === item.seq ? 'is-selected' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                key={item.seq}
                onClick={() => setSelectedSeq(item.seq)}
                aria-pressed={selectedSeq === item.seq}
              >
                <div className="watch-event__main">
                  {/* The glyph and the word both carry the level: a colour
                      alone tells a colourblind analyst nothing, and nothing at
                      all to a screen reader. */}
                  <span className="watch-event__marker" aria-hidden="true">
                    {level === 'critical' ? '!' : level === 'elevated' ? '↗' : '·'}
                  </span>
                  <div className="watch-event__body">
                    <b>{label(item)}</b>
                    <small>
                      <span className="sr-only">{level} severity. </span>
                      {SEVERITY_LABEL[level].toUpperCase()} · {category.label} ·{' '}
                      {item.action.replaceAll('.', ' / ')}
                    </small>
                    {isFlagged(item) ? (
                      <Badge tone="danger" title="This event carried a prompt-injection indicator.">
                        flagged
                      </Badge>
                    ) : null}
                  </div>
                </div>
                <span className="watch-event__case">
                  {name ?? (item.case_id ? shortId(item.case_id) : 'SYSTEM')}
                  {subject !== null ? <small>{subject}</small> : null}
                </span>
                <span className="watch-event__time">
                  {formatDateTime(item.occurred_at)}
                  <small>#{item.seq}</small>
                </span>
              </button>
            );
          })}
        </div>

        {selected === null ? (
          <aside className="watch-aside">
            <div className="watch-aside__head">
              <span className="eyebrow">Signal posture</span>
              <b>Now</b>
            </div>
            <div className="watch-meter">
              <span>Critical events</span>
              <b>{totals.critical}</b>
              <i>
                <em style={{ width: `${Math.min(100, totals.critical * 12)}%` }} />
              </i>
            </div>
            <div className="watch-meter">
              <span>Elevated events</span>
              <b>{totals.elevated}</b>
              <i>
                <em style={{ width: `${Math.min(100, totals.elevated * 10)}%` }} />
              </i>
            </div>
            {CATEGORIES.map((category) => (
              <div className="watch-meter" key={category.id}>
                <span>{category.label}</span>
                <b>{totals[category.id]}</b>
                <i>
                  <em style={{ width: `${Math.min(100, totals[category.id] * 6)}%` }} />
                </i>
              </div>
            ))}
            <div className="watch-note">
              <span>Operational note</span>
              <p>Signals are synthetic demonstration data. Follow the linked case to inspect provenance before drawing conclusions.</p>
            </div>
          </aside>
        ) : null}
      </section>

      <InspectorRail
        open={selected !== null}
        onClose={() => setSelectedSeq(null)}
        title={selected === null ? 'Event' : label(selected)}
        subtitle={selected === null ? undefined : selected.action}
        status={inspectorStatus}
        facts={inspectorFacts}
        summary={isFlagged(selected) ? 'This event carried a prompt-injection indicator. Treat its payload as untrusted text.' : undefined}
        tabs={
          inspectorPayload.length === 0
            ? undefined
            : [
                { id: 'payload', label: 'Recorded payload' },
                { id: 'context', label: 'Context' },
              ]
        }
        activeTab="payload"
        tabPanels={{
          payload: (
            <dl className="insp-facts">
              {inspectorPayload.map(([key, value]) => (
                <div className="insp-facts__row" key={key}>
                  <dt className="insp-facts__label">{key.replaceAll('_', ' ')}</dt>
                  <dd className="insp-facts__value insp-facts__value--mono">{payloadText(value) ?? '—'}</dd>
                </div>
              ))}
            </dl>
          ),
          context: (
            <div className="watch-inspector__context">
              <p>
                This event is row <code>#{selected?.seq}</code> of the append-only audit log. Every entry
                is hash-chained to the one before it, so a gap or an edit in this stream is detectable
                rather than merely suspicious.
              </p>
              {selected?.case_id != null ? (
                <p>
                  <Link to={`/cases/${selected.case_id}`} className="link-button">
                    Open the case this belongs to
                  </Link>
                </p>
              ) : (
                <p className="watch-inspector__muted">
                  This event is not attached to a case. It records platform activity rather than a
                  change to an investigation.
                </p>
              )}
            </div>
          ),
        }}
        actions={
          <button type="button" className="btn btn--ghost" onClick={() => setReloadKey((key) => key + 1)}>
            Replay recorded events
          </button>
        }
      />
    </div>
  );
}
