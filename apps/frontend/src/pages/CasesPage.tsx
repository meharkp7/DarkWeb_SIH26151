import { Fragment, useCallback, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, apiUrl, formatApiError } from '../api/client';
import { CASE_PRIORITIES, CASE_SEVERITIES, CASE_STATUSES } from '../api/types';
import type {
  CasePriority,
  CaseQueueEntry,
  CaseSeverity,
  CaseStatus,
  PriorityReason,
  SlaState,
} from '../api/types';
import { RegisterExportButton } from '../components/RegisterExportButton';
import { useApi } from '../hooks/useApi';
import { formatDateTime, shortId } from '../lib/format';
import { Badge } from '../components/Badge';
import type { Tone } from '../components/Badge';
import { InspectorRail } from '../components/InspectorRail';
import type { InspectorFact, InspectorStatus } from '../components/InspectorRail';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { TimeRangeNotice } from '../components/TimeRangeControl';
import { filterByTimeRange, useTimeRange } from '../store/TimeRange';

const PRIORITY_TONE: Record<CasePriority, Tone> = {
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
};

const SEVERITY_TONE: Record<CaseSeverity, Tone> = {
  informational: 'neutral',
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
};

const STATUS_TONE: Record<CaseStatus, Tone> = {
  open: 'info',
  active: 'ok',
  on_hold: 'warn',
  closed: 'neutral',
  archived: 'neutral',
};

const PRIORITY_RANK: Record<CasePriority, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const SEVERITY_RANK: Record<CaseSeverity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  informational: 4,
};

const STATUS_RANK: Record<CaseStatus, number> = {
  active: 0,
  open: 1,
  on_hold: 2,
  closed: 3,
  archived: 4,
};

const SLA_RANK: Record<SlaState, number> = {
  breached: 0,
  at_risk: 1,
  ok: 2,
  none: 3,
};

/** Colour *and* word: an SLA state is never carried by the badge tint alone. */
const SLA_TONE: Record<SlaState, Tone> = {
  breached: 'danger',
  at_risk: 'warn',
  ok: 'ok',
  none: 'neutral',
};

const SLA_TEXT: Record<SlaState, string> = {
  breached: 'breached',
  at_risk: 'at risk',
  ok: 'on track',
  none: 'no deadline',
};

/** Rail pills carry the same four tones the badges use, minus 'info'. */
const STATUS_RAIL_TONE: Record<CaseStatus, InspectorStatus['tone']> = {
  open: 'muted',
  active: 'ok',
  on_hold: 'warn',
  closed: 'muted',
  archived: 'muted',
};

const PRIORITY_RAIL_TONE: Record<CasePriority, InspectorStatus['tone']> = {
  low: 'muted',
  medium: 'muted',
  high: 'warn',
  critical: 'danger',
};

const SEVERITY_RAIL_TONE: Record<CaseSeverity, InspectorStatus['tone']> = {
  informational: 'muted',
  low: 'muted',
  medium: 'muted',
  high: 'warn',
  critical: 'danger',
};

const SLA_RAIL_TONE: Record<SlaState, InspectorStatus['tone']> = {
  breached: 'danger',
  at_risk: 'warn',
  ok: 'ok',
  none: 'muted',
};

const SLA_STATES: readonly SlaState[] = ['breached', 'at_risk', 'ok', 'none'];

type SortKey =
  | 'queue'
  | 'name'
  | 'status'
  | 'priority'
  | 'severity'
  | 'evidence'
  | 'entities'
  | 'relationships'
  | 'contradictions'
  | 'recent_evidence'
  | 'attribution'
  | 'sla'
  | 'activity';

interface Column {
  readonly key: string;
  readonly label: string;
  readonly sort: SortKey | null;
  readonly end?: boolean;
}

const COLUMNS: readonly Column[] = [
  { key: 'case', label: 'Case', sort: 'name' },
  { key: 'threat', label: 'Threat', sort: null },
  { key: 'status', label: 'Status', sort: 'status' },
  { key: 'priority', label: 'Priority', sort: 'priority' },
  { key: 'severity', label: 'Severity', sort: 'severity' },
  { key: 'evidence', label: 'Evidence', sort: 'evidence', end: true },
  { key: 'entities', label: 'Entities', sort: 'entities', end: true },
  { key: 'relationships', label: 'Rel.', sort: 'relationships', end: true },
  { key: 'attribution', label: 'Attrib.', sort: 'attribution', end: true },
  { key: 'sla', label: 'SLA', sort: 'sla' },
  { key: 'activity', label: 'Last activity', sort: 'activity' },
  { key: 'owner', label: 'Owner', sort: null },
];

const SORT_OPTIONS: ReadonlyArray<{ id: SortKey; label: string }> = [
  { id: 'queue', label: 'Queue score' },
  { id: 'recent_evidence', label: 'Newest evidence' },
  { id: 'contradictions', label: 'Open contradictions' },
  { id: 'activity', label: 'Last activity' },
  { id: 'sla', label: 'SLA state' },
  { id: 'name', label: 'Case name' },
  { id: 'evidence', label: 'Evidence count' },
  { id: 'entities', label: 'Entity count' },
  { id: 'relationships', label: 'Relationship count' },
  { id: 'attribution', label: 'Attribution confidence' },
  { id: 'status', label: 'Status' },
  { id: 'priority', label: 'Priority' },
  { id: 'severity', label: 'Severity' },
];

/** Sorting by name is the only column whose natural order is ascending. */
const ASCENDING: ReadonlySet<SortKey> = new Set<SortKey>(['name']);

function isSortKey(value: string | null): value is SortKey {
  return value !== null && SORT_OPTIONS.some((option) => option.id === value);
}

function isStatus(value: string | null): value is CaseStatus {
  return value !== null && (CASE_STATUSES as readonly string[]).includes(value);
}

function isPriority(value: string | null): value is CasePriority {
  return value !== null && (CASE_PRIORITIES as readonly string[]).includes(value);
}

function isSeverity(value: string | null): value is CaseSeverity {
  return value !== null && (CASE_SEVERITIES as readonly string[]).includes(value);
}

function isSlaState(value: string | null): value is SlaState {
  return value !== null && (SLA_STATES as readonly string[]).includes(value);
}

/*
 * The register row is `CaseQueueEntry`, but a queue endpoint that predates the
 * reasons/sla_state columns still answers with the older summary shape. These
 * readers keep a missing column reading as "not reported" rather than as zero,
 * so the register cannot show a case as clean because the API said nothing.
 */
function countOf(
  entry: CaseQueueEntry,
  key: 'evidence' | 'entities' | 'relationships' | 'contradictions' | 'recent_evidence' | 'assessments',
): number {
  const value = (entry.counts as Readonly<Record<string, number | undefined>>)[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function queueScoreOf(entry: CaseQueueEntry): number {
  return typeof entry.queue_score === 'number' && Number.isFinite(entry.queue_score) ? entry.queue_score : 0;
}

function attributionOf(entry: CaseQueueEntry): number | null {
  return typeof entry.attribution === 'number' && Number.isFinite(entry.attribution) ? entry.attribution : null;
}

function reasonsOf(entry: CaseQueueEntry): readonly PriorityReason[] {
  return Array.isArray(entry.reasons) ? entry.reasons : [];
}

function slaStateOf(entry: CaseQueueEntry): SlaState {
  if (typeof entry.sla_state === 'string') return entry.sla_state;
  if (entry.sla_due_at === null) return 'none';
  return entry.sla_overdue === true ? 'breached' : 'ok';
}

function lastActivityOf(entry: CaseQueueEntry): string {
  return entry.last_activity ?? '';
}

function sortRows(rows: readonly CaseQueueEntry[], sort: SortKey, direction: 'asc' | 'desc'): CaseQueueEntry[] {
  // Each comparator below is written as "descending" and flipped for ascending
  // sorts, so a new column cannot accidentally ship with the wrong direction.
  const sign = direction === 'asc' ? -1 : 1;
  const sorted = [...rows];
  sorted.sort((left, right) => {
    switch (sort) {
      case 'queue':
        return sign * (queueScoreOf(right) - queueScoreOf(left));
      case 'name':
        return sign * left.name.localeCompare(right.name);
      case 'status':
        return sign * (STATUS_RANK[left.status] - STATUS_RANK[right.status]);
      case 'priority':
        return sign * (PRIORITY_RANK[left.priority] - PRIORITY_RANK[right.priority]);
      case 'severity':
        return sign * (SEVERITY_RANK[left.severity] - SEVERITY_RANK[right.severity]);
      case 'evidence':
        return sign * (countOf(right, 'evidence') - countOf(left, 'evidence'));
      case 'entities':
        return sign * (countOf(right, 'entities') - countOf(left, 'entities'));
      case 'relationships':
        return sign * (countOf(right, 'relationships') - countOf(left, 'relationships'));
      case 'contradictions':
        return sign * (countOf(right, 'contradictions') - countOf(left, 'contradictions'));
      case 'recent_evidence':
        return sign * (countOf(right, 'recent_evidence') - countOf(left, 'recent_evidence'));
      case 'attribution': {
        const a = attributionOf(left);
        const b = attributionOf(right);
        // Unscored cases sink below scored ones instead of sorting as zero.
        if (a === null && b === null) return 0;
        if (a === null) return 1;
        if (b === null) return -1;
        return sign * (b - a);
      }
      case 'sla':
        return sign * (SLA_RANK[slaStateOf(left)] - SLA_RANK[slaStateOf(right)]);
      case 'activity':
        return sign * lastActivityOf(right).localeCompare(lastActivityOf(left));
      default:
        return 0;
    }
  });
  return sorted;
}

function NewCaseDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<CasePriority>('medium');
  const [severity, setSeverity] = useState<CaseSeverity>('medium');
  const [tags, setTags] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = name.trim();
    if (trimmed === '') {
      setError('A case name is required.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createCase({
        name: trimmed,
        description: description.trim() === '' ? null : description.trim(),
        priority,
        severity,
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter((tag) => tag !== ''),
      });
      onCreated();
    } catch (err: unknown) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-case-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal__head">
          <h2 id="new-case-title">New investigation</h2>
          <button type="button" className="btn btn--icon" onClick={onClose} aria-label="Cancel">
            <span aria-hidden="true">✕</span>
          </button>
        </header>
        <div className="modal__body">
          <div className="field">
            <label htmlFor="nc-name">Name (required)</label>
            <input
              id="nc-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
              placeholder="Operation …"
            />
          </div>
          <div className="field">
            <label htmlFor="nc-description">Description</label>
            <textarea
              id="nc-description"
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What is being investigated, and why?"
            />
          </div>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="nc-priority">Priority</label>
              <select
                id="nc-priority"
                value={priority}
                onChange={(event) => setPriority(event.target.value as CasePriority)}
              >
                {CASE_PRIORITIES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="nc-severity">Severity</label>
              <select
                id="nc-severity"
                value={severity}
                onChange={(event) => setSeverity(event.target.value as CaseSeverity)}
              >
                {CASE_SEVERITIES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
            <div className="field field--wide">
              <label htmlFor="nc-tags">Tags (comma separated)</label>
              <input
                id="nc-tags"
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="financial, marketplace, vpn"
              />
            </div>
          </div>
          {error !== null && <p className="status status--error">{error}</p>}
        </div>
        <footer className="modal__foot">
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn--primary" onClick={() => void submit()} disabled={busy}>
            {busy ? 'Creating…' : 'Create investigation'}
          </button>
        </footer>
      </div>
    </div>
  );
}

/**
 * The "why prioritised" expansion.
 *
 * A queue position that cannot be explained is a queue position an analyst
 * cannot argue with, so every driver is listed with its own weight next to the
 * total it contributes to.
 */
function WhyPrioritised({ entry }: { entry: CaseQueueEntry }) {
  const reasons = reasonsOf(entry);
  const total = Math.max(
    1,
    reasons.reduce((sum, reason) => sum + (Number.isFinite(reason.weight) ? reason.weight : 0), 0),
  );
  return (
    <div>
      <div className="inv-reasons__head">
        <strong>Why {entry.name} is positioned here</strong>
        <span className="inv-reasons__score">
          {`queue score ${queueScoreOf(entry).toFixed(1)}`}
          {typeof entry.queue_reason === 'string' && entry.queue_reason !== '' ? ` · ${entry.queue_reason}` : ''}
        </span>
        <Link className="link-button" to={`/cases/${encodeURIComponent(entry.case_id)}`}>
          Open workspace →
        </Link>
      </div>
      {reasons.length === 0 ? (
        <p className="hint">
          The API returned no priority reasons for this case, so its position in the register is not
          explained by any driver it reported.
        </p>
      ) : (
        <ul className="inv-reasons__list">
          {reasons.map((reason) => {
            const weight = Number.isFinite(reason.weight) ? reason.weight : 0;
            return (
              <li className="inv-reason" key={reason.key}>
                <span className="inv-reason__label">{reason.label}</span>
                <span className="inv-reason__meta">
                  <span>{reason.key}</span>
                  <span>{weight.toFixed(1)}</span>
                </span>
                <span className="inv-reason__bar" aria-hidden="true">
                  <i style={{ width: `${Math.round((Math.abs(weight) / total) * 100)}%` }} />
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="hint">
        {`Evidence ${countOf(entry, 'evidence')} · new ${countOf(entry, 'recent_evidence')} · contradictions ${countOf(
          entry,
          'contradictions',
        )} · entities ${countOf(entry, 'entities')} · relationships ${countOf(entry, 'relationships')}`}
      </p>
    </div>
  );
}

/** Which of the selected case's fields live in a tab panel rather than the fact list. */
const RAIL_TABS = [
  { id: 'priority', label: 'Priority' },
  { id: 'counts', label: 'Counts' },
] as const;

/**
 * Rail content for one register row.
 *
 * The reasons expansion is not re-implemented here: the rail renders the same
 * {@link WhyPrioritised} block the inline row expansion renders, so "why is this
 * case positioned here" cannot drift between the two places an analyst reads it.
 */
function caseRailProps(entry: CaseQueueEntry, onClose: () => void, activeTab: string, onTabChange: (id: string) => void) {
  const state = slaStateOf(entry);
  const attribution = attributionOf(entry);
  const owner = entry.assigned_to === null ? 'unassigned' : shortId(entry.assigned_to, 8);

  const status: InspectorStatus[] = [
    { label: entry.status.replace('_', ' '), tone: STATUS_RAIL_TONE[entry.status] },
    { label: entry.priority, tone: PRIORITY_RAIL_TONE[entry.priority] },
    { label: entry.severity, tone: SEVERITY_RAIL_TONE[entry.severity] },
    { label: SLA_TEXT[state], tone: SLA_RAIL_TONE[state] },
  ];

  const facts: InspectorFact[] = [
    { label: 'Queue score', value: queueScoreOf(entry).toFixed(1), mono: true },
    { label: 'Owner', value: owner, mono: entry.assigned_to !== null },
    {
      label: 'SLA',
      value:
        entry.sla_due_at === null
          ? 'no deadline set'
          : `due ${formatDateTime(entry.sla_due_at)}${entry.sla_overdue === true ? ' · overdue' : ''}`,
    },
    { label: 'Last activity', value: formatDateTime(lastActivityOf(entry) || null) },
    { label: 'Case ID', value: entry.case_id, mono: true },
  ];

  const counts: InspectorFact[] = [
    { label: 'Evidence', value: countOf(entry, 'evidence'), mono: true },
    { label: 'New evidence', value: countOf(entry, 'recent_evidence'), mono: true },
    { label: 'Entities', value: countOf(entry, 'entities'), mono: true },
    { label: 'Relationships', value: countOf(entry, 'relationships'), mono: true },
    { label: 'Contradictions', value: countOf(entry, 'contradictions'), mono: true },
    { label: 'Assessments', value: countOf(entry, 'assessments'), mono: true },
    {
      label: 'Attribution',
      value: attribution === null ? 'unscored' : `${Math.round(attribution * 1000) / 10}%`,
    },
  ];

  const tabPanels: Record<string, ReactNode> = {
    priority: <WhyPrioritised entry={entry} />,
    counts: (
      <dl className="insp-facts">
        {counts.map((fact) => (
          <div className="insp-facts__row" key={fact.label}>
            <dt className="insp-facts__label">{fact.label}</dt>
            <dd className={fact.mono === true ? 'insp-facts__value insp-facts__value--mono' : 'insp-facts__value'}>
              {fact.value}
            </dd>
          </div>
        ))}
      </dl>
    ),
  };

  return {
    open: true,
    onClose,
    title: entry.name,
    subtitle: entry.tags.length === 0 ? 'Untagged investigation' : entry.tags.join(' · '),
    status,
    facts,
    identifiers:
      entry.assigned_to === null ? undefined : [{ kind: 'owner', value: entry.assigned_to }],
    // Attribution is stored by the platform, not guessed at render time; the
    // badge is what stops it reading as a model opinion.
    confidence: attribution === null ? undefined : { value: attribution, kind: 'recorded' as const },
    summary:
      typeof entry.queue_reason === 'string' && entry.queue_reason !== ''
        ? `Queue note: ${entry.queue_reason}`
        : undefined,
    tabs: RAIL_TABS,
    activeTab,
    onTabChange,
    tabPanels,
    actions: (
      <Link className="btn btn--primary insp-rail__action" to={`/cases/${encodeURIComponent(entry.case_id)}`}>
        Open investigation →
      </Link>
    ),
    empty: 'No entity selected.',
  };
}

/**
 * Investigations register.
 *
 * Every filter, toggle and sort lives in the query string rather than in
 * component state: the Command Center tiles deep-link here (`?priority=critical`,
 * `?sla=at_risk`, `?sort=contradictions`), an analyst can paste a filtered
 * register into a handover note, and the browser back button steps through
 * filter changes the way an analyst expects it to.
 *
 * Selection behaves the same way: `?inspect={caseId}` is the selection, so the
 * exact register view an analyst was looking at — filters, sort *and* the row
 * under inspection — is one link.
 */
export function CasesPage() {
  const [params, setParams] = useSearchParams();
  const { data, reload, loading, error } = useApi<CaseQueueEntry[]>(apiUrl('/v1/dashboard/cases'));
  const [creating, setCreating] = useState(false);
  const { from, to, label: windowLabel, isActive, setWindow } = useTimeRange();

  const query = params.get('q') ?? '';
  const status = isStatus(params.get('status')) ? (params.get('status') as CaseStatus) : 'all';
  const priority = isPriority(params.get('priority')) ? (params.get('priority') as CasePriority) : 'all';
  const severity = isSeverity(params.get('severity')) ? (params.get('severity') as CaseSeverity) : 'all';
  const tag = params.get('tag') ?? 'all';
  const sla = isSlaState(params.get('sla')) ? (params.get('sla') as SlaState) : 'all';
  const overdueOnly = params.get('overdue') === 'true';
  const unassignedOnly = params.get('unassigned') === 'true';
  const sort: SortKey = isSortKey(params.get('sort')) ? (params.get('sort') as SortKey) : 'queue';
  const dirParam = params.get('dir');
  const dir: 'asc' | 'desc' = dirParam === 'asc' || dirParam === 'desc' ? dirParam : ASCENDING.has(sort) ? 'asc' : 'desc';
  const expanded = params.get('row');
  const inspect = params.get('inspect');
  const [railTab, setRailTab] = useState('priority');

  /** Every filter change is a URL change; `replace` keeps typing out of history. */
  const update = useCallback((patch: Readonly<Record<string, string | null>>, replace = true) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace });
  }, [params, setParams]);

  const toggleSort = (key: SortKey) => {
    if (key === sort) update({ dir: dir === 'desc' ? 'asc' : 'desc' }, false);
    else update({ sort: key, dir: ASCENDING.has(key) ? 'asc' : 'desc' }, false);
  };

  const allTags = useMemo(() => {
    const seen = new Set<string>();
    for (const entry of data ?? []) for (const value of entry.tags) seen.add(value);
    return [...seen].sort();
  }, [data]);

  /**
   * The window, applied first and to the whole loaded set.
   *
   * The register endpoint takes no time bound, so this is a browser-side slice
   * over the rows already fetched — which is why the notice under the heading
   * says so. It is measured by *last activity* rather than by creation: the
   * question the window answers is "what did I learn in the last week", and a
   * case opened in March and worked on yesterday belongs to last week.
   */
  const inWindow = useMemo(
    () => filterByTimeRange(data ?? [], (entry) => entry.last_activity, from, to),
    [data, from, to],
  );

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = inWindow.rows.filter((entry) => {
      if (needle !== '') {
        const haystack = `${entry.name} ${entry.case_id} ${entry.tags.join(' ')}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      if (status !== 'all' && entry.status !== status) return false;
      if (priority !== 'all' && entry.priority !== priority) return false;
      if (severity !== 'all' && entry.severity !== severity) return false;
      if (tag !== 'all' && !entry.tags.includes(tag)) return false;
      if (sla !== 'all' && slaStateOf(entry) !== sla) return false;
      if (overdueOnly && entry.sla_overdue !== true) return false;
      if (unassignedOnly && entry.assigned_to !== null) return false;
      return true;
    });
    return sortRows(filtered, sort, dir);
  }, [inWindow, query, status, priority, severity, tag, sla, overdueOnly, unassignedOnly, sort, dir]);

  const total = inWindow.total;

  // Looked up in the unfiltered list, so narrowing the register while a case is
  // under inspection does not silently empty the rail the analyst is reading.
  const selectedEntry = useMemo(
    () => (data ?? []).find((entry) => entry.case_id === inspect) ?? null,
    [data, inspect],
  );

  const select = useCallback(
    (caseId: string | null) => {
      update({ inspect: caseId }, false);
      setRailTab('priority');
    },
    [update],
  );

  /**
   * Roving tabindex over the register.
   *
   * A grid of 200 cases must not be 200 tab stops: one stop enters the grid and
   * the arrow keys move within it, which is what `role="grid"` promises.
   */
  const [focusIndex, setFocusIndex] = useState(0);
  const bodyRef = useRef<HTMLTableSectionElement>(null);

  const moveFocus = (from: number, delta: number) => {
    const next = Math.min(rows.length - 1, Math.max(0, from + delta));
    setFocusIndex(next);
    // Selected by attribute, not by sibling index: an expanded reasons row is a
    // sibling `<tr>` in the same tbody and would shift every index below it.
    const stops = bodyRef.current?.querySelectorAll<HTMLElement>('tr[aria-selected]');
    const target = stops?.[next];
    if (target !== undefined) target.focus();
  };

  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, index: number, caseId: string) => {
    switch (event.key) {
      case 'Enter':
      case ' ':
        // Selecting never navigates; the case name link is the way in.
        event.preventDefault();
        select(caseId);
        break;
      case 'ArrowDown':
        event.preventDefault();
        moveFocus(index, 1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        moveFocus(index, -1);
        break;
      case 'Home':
        event.preventDefault();
        moveFocus(index, -index);
        break;
      case 'End':
        event.preventDefault();
        moveFocus(index, rows.length - 1 - index);
        break;
      default:
        break;
    }
  };

  const rail = selectedEntry === null ? null : caseRailProps(selectedEntry, () => select(null), railTab, setRailTab);

  const filtersActive =
    query.trim() !== '' ||
    status !== 'all' ||
    priority !== 'all' ||
    severity !== 'all' ||
    tag !== 'all' ||
    sla !== 'all' ||
    overdueOnly ||
    unassignedOnly;

  return (
    <div className="page-stack inv-page">
      <header className="inv-page__head">
        <div>
          <span className="eyebrow">Register</span>
          <h1>Investigations</h1>
          <p>
            Every investigation, its triage state and the evidence standing behind it. Filters live
            in the address bar, so a view of the register can be linked, bookmarked or handed over.{' '}
            <TimeRangeNotice
              window={windowLabel}
              shown={rows.length}
              total={total}
              basis={`in the browser over ${total} loaded ${
                total === 1 ? 'record' : 'records'
              }, by last activity — GET /v1/dashboard/cases takes no time bound`}
              undated={inWindow.undated}
            />
          </p>
        </div>
        <div className="inv-page__actions">
          {/* Export sits with the register it exports, not on a page of its
              own. Selecting a case is a click away and the menu carries the
              selection. */}
          <RegisterExportButton />
          <button className="button button--dark" onClick={() => setCreating(true)}>
            + New investigation
          </button>
        </div>
      </header>

      <div className="inv-toolbar" role="search" aria-label="Filter the investigations register">
        <div className="inv-toolbar__search">
          <span aria-hidden="true">⌕</span>
          <input
            value={query}
            onChange={(event) => update({ q: event.target.value })}
            placeholder="Search name, id or tag…"
            aria-label="Search cases"
          />
        </div>

        <label className="sr-only" htmlFor="inv-filter-status">
          Filter by status
        </label>
        <select
          id="inv-filter-status"
          className="inv-select"
          value={status}
          onChange={(event) => update({ status: event.target.value === 'all' ? null : event.target.value })}
          aria-label="Filter by status"
        >
          <option value="all">All statuses</option>
          {CASE_STATUSES.map((value) => (
            <option key={value} value={value}>
              {value.replace('_', ' ')}
            </option>
          ))}
        </select>

        <label className="sr-only" htmlFor="inv-filter-priority">
          Filter by priority
        </label>
        <select
          id="inv-filter-priority"
          className="inv-select"
          value={priority}
          onChange={(event) => update({ priority: event.target.value === 'all' ? null : event.target.value })}
          aria-label="Filter by priority"
        >
          <option value="all">All priorities</option>
          {CASE_PRIORITIES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>

        <label className="sr-only" htmlFor="inv-filter-severity">
          Filter by severity
        </label>
        <select
          id="inv-filter-severity"
          className="inv-select"
          value={severity}
          onChange={(event) => update({ severity: event.target.value === 'all' ? null : event.target.value })}
          aria-label="Filter by severity"
        >
          <option value="all">All severities</option>
          {CASE_SEVERITIES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>

        <label className="sr-only" htmlFor="inv-filter-tag">
          Filter by tag
        </label>
        <select
          id="inv-filter-tag"
          className="inv-select"
          value={tag}
          onChange={(event) => update({ tag: event.target.value === 'all' ? null : event.target.value })}
          aria-label="Filter by tag"
        >
          <option value="all">All tags</option>
          {allTags.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>

        <label className="sr-only" htmlFor="inv-filter-sla">
          Filter by SLA state
        </label>
        <select
          id="inv-filter-sla"
          className="inv-select"
          value={sla}
          onChange={(event) => update({ sla: event.target.value === 'all' ? null : event.target.value })}
          aria-label="Filter by SLA state"
        >
          <option value="all">All SLA states</option>
          {SLA_STATES.map((value) => (
            <option key={value} value={value}>
              {SLA_TEXT[value]}
            </option>
          ))}
        </select>

        <label className="inv-toggle">
          <input
            type="checkbox"
            checked={overdueOnly}
            onChange={(event) => update({ overdue: event.target.checked ? 'true' : null })}
          />
          SLA breached
        </label>

        <label className="inv-toggle">
          <input
            type="checkbox"
            checked={unassignedOnly}
            onChange={(event) => update({ unassigned: event.target.checked ? 'true' : null })}
          />
          Unassigned
        </label>

        <label className="sr-only" htmlFor="inv-sort">
          Sort investigations
        </label>
        <select
          id="inv-sort"
          className="inv-select"
          value={sort}
          onChange={(event) => {
            const next = event.target.value;
            if (isSortKey(next)) update({ sort: next === 'queue' ? null : next, dir: ASCENDING.has(next) ? 'asc' : 'desc' });
          }}
          aria-label="Sort cases"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {`Sort: ${option.label}`}
            </option>
          ))}
        </select>

        <button
          type="button"
          className="btn btn--ghost btn--small inv-toolbar__clear"
          // The window lives in the same query string, so a Reset that left it
          // standing would re-apply itself a frame later and leave the analyst
          // looking at a filtered register they believe they just cleared.
          onClick={() => {
            setParams(new URLSearchParams(), { replace: true });
            setWindow('all');
          }}
        >
          Reset
        </button>
      </div>

      {error !== null && <ErrorState message={error} onRetry={reload} />}
      {loading && <LoadingState label="Loading investigations…" />}

      {!loading && error === null && total === 0 && (
        <EmptyState
          title="No investigations yet"
          message="Create an investigation to start collecting evidence against it."
          endpoint="GET /api/v1/dashboard/cases"
        />
      )}

      {!loading && error === null && total > 0 && (
        <div className={rail === null ? 'insp-shell' : 'insp-shell has-rail'}>
        <div className="table-wrap">
          <table className="inv-register" role="grid" aria-label="Investigations register">
            <caption className="sr-only">
              Investigations register: {rows.length} of {total} investigations, sorted by{' '}
              {SORT_OPTIONS.find((option) => option.id === sort)?.label ?? sort}. Use the arrow keys to
              move between rows and Enter to inspect a case without leaving the register.
            </caption>
            <thead>
              <tr>
                {COLUMNS.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    style={{ textAlign: column.end === true ? 'end' : 'start' }}
                    aria-sort={
                      column.sort === null
                        ? undefined
                        : column.sort === sort
                          ? dir === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                    }
                  >
                    {column.sort === null ? (
                      column.label
                    ) : (
                      <button
                        type="button"
                        className="inv-sort"
                        onClick={() => toggleSort(column.sort as SortKey)}
                      >
                        {column.label}
                        <span className="inv-sort__arrow" aria-hidden="true" />
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody ref={bodyRef}>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={COLUMNS.length} className="data-table__empty">
                    <EmptyState
                      title="No matches"
                      message={
                        isActive
                          ? `No investigation matches the current filters inside ${windowLabel}. An investigation with no recorded activity cannot be shown to fall in a window, so it is not listed. Reset the window, or widen it, to see more.`
                          : 'No investigation matches the current filters. Reset to see the full register.'
                      }
                    />
                  </td>
                </tr>
              )}
              {rows.map((entry, index) => {
                const state = slaStateOf(entry);
                const isOpen = expanded === entry.case_id;
                const isSelected = selectedEntry?.case_id === entry.case_id;
                const reasonId = `inv-reasons-${entry.case_id}`;
                return (
                  <Fragment key={entry.case_id}>
                    <tr
                      className={[isOpen ? 'is-expanded' : '', isSelected ? 'insp-selected-row' : '']
                        .filter(Boolean)
                        .join(' ') || undefined}
                      aria-selected={isSelected}
                      tabIndex={index === focusIndex ? 0 : -1}
                      onFocus={() => setFocusIndex(index)}
                      onClick={() => select(entry.case_id)}
                      onKeyDown={(event) => onRowKeyDown(event, index, entry.case_id)}
                      style={{ cursor: 'pointer' }}
                    >
                      {COLUMNS.map((column) => {
                      switch (column.key) {
                        case 'case':
                          return (
                            <td key={column.key} className="inv-case-cell">
                              <div className="inv-case-cell__top">
                                <button
                                  type="button"
                                  className="inv-expand"
                                  aria-expanded={isOpen}
                                  aria-controls={isOpen ? reasonId : undefined}
                                  onClick={(event) => {
                                    // The row selects on click; the disclosure
                                    // must not also steal the selection.
                                    event.stopPropagation();
                                    update({ row: isOpen ? null : entry.case_id }, false);
                                  }}
                                >
                                  <span aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
                                  <span className="sr-only">
                                    {isOpen ? 'Hide' : 'Show'} why {entry.name} is prioritised
                                  </span>
                                </button>
                                <Link
                                  className="inv-case-cell__name"
                                  to={`/cases/${encodeURIComponent(entry.case_id)}`}
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  {entry.name}
                                </Link>
                                <span className="inv-case-cell__id" title={entry.case_id}>
                                  {shortId(entry.case_id, 8)}
                                </span>
                              </div>
                            </td>
                          );
                        case 'threat':
                          return (
                            <td key={column.key}>
                              {entry.tags.length === 0 ? (
                                <span className="hint">—</span>
                              ) : (
                                <span className="inv-tags">
                                  {entry.tags.map((value) => (
                                    <span className="inv-tag" key={value}>
                                      {value}
                                    </span>
                                  ))}
                                </span>
                              )}
                            </td>
                          );
                        case 'status':
                          return (
                            <td key={column.key}>
                              <Badge tone={STATUS_TONE[entry.status]}>{entry.status.replace('_', ' ')}</Badge>
                            </td>
                          );
                        case 'priority':
                          return (
                            <td key={column.key}>
                              <Badge tone={PRIORITY_TONE[entry.priority]} title="Triage priority">
                                {entry.priority}
                              </Badge>
                            </td>
                          );
                        case 'severity':
                          return (
                            <td key={column.key}>
                              <Badge tone={SEVERITY_TONE[entry.severity]} title="Impact severity">
                                {entry.severity}
                              </Badge>
                            </td>
                          );
                        case 'evidence':
                          return (
                            <td key={column.key} className="inv-num">
                              {countOf(entry, 'evidence')}
                              <small className="table-sub" style={{ display: 'block' }}>
                                {countOf(entry, 'recent_evidence')} new
                              </small>
                            </td>
                          );
                        case 'entities':
                          return (
                            <td key={column.key} className="inv-num">
                              {countOf(entry, 'entities')}
                            </td>
                          );
                        case 'relationships':
                          return (
                            <td key={column.key} className="inv-num">
                              {countOf(entry, 'relationships')}
                            </td>
                          );
                        case 'attribution': {
                          const attribution = attributionOf(entry);
                          const contradictions = countOf(entry, 'contradictions');
                          return (
                            <td key={column.key} className="inv-num">
                              {attribution === null ? (
                                <span className="hint">unscored</span>
                              ) : (
                                `${Math.round(attribution * 1000) / 10}%`
                              )}
                              <small className="table-sub" style={{ display: 'block' }}>
                                {contradictions === 0 ? 'no contradictions' : `${contradictions} contradiction(s)`}
                              </small>
                            </td>
                          );
                        }
                        case 'sla':
                          return (
                            <td key={column.key}>
                              <Badge tone={SLA_TONE[state]}>{SLA_TEXT[state]}</Badge>
                              <small className="inv-sla__due">
                                {entry.sla_due_at === null
                                  ? 'no deadline set'
                                  : `due ${formatDateTime(entry.sla_due_at)}`}
                              </small>
                            </td>
                          );
                        case 'activity':
                          return (
                            <td key={column.key}>
                              {formatDateTime(lastActivityOf(entry) || null)}
                            </td>
                          );
                        case 'owner':
                          return (
                            <td key={column.key}>
                              {entry.assigned_to === null ? (
                                <Badge tone="warn">unassigned</Badge>
                              ) : (
                                <span className="mono" title={entry.assigned_to}>
                                  {shortId(entry.assigned_to, 8)}
                                </span>
                              )}
                            </td>
                          );
                        default:
                          return <td key={column.key}>—</td>;
                      }
                    })}
                    </tr>
                    {isOpen && (
                      <tr className="inv-reasons-row">
                        <td colSpan={COLUMNS.length} className="inv-reasons" id={reasonId}>
                          <WhyPrioritised entry={entry} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
          {rail !== null && <InspectorRail {...rail} />}
        </div>
      )}

      <p className="inv-foot">
        <span>
          {isActive
            ? `${rows.length.toLocaleString('en-GB')} of ${total.toLocaleString('en-GB')} in window · ${windowLabel}`
            : `${rows.length} of ${total} shown · live from PostgreSQL`}
        </span>
        <span>
          {filtersActive ? 'Filters applied from the address bar — Reset clears them.' : 'No filters applied.'}
        </span>
      </p>

      {creating && (
        <NewCaseDialog
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            reload();
          }}
        />
      )}
    </div>
  );
}
