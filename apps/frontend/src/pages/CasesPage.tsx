import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, formatApiError } from '../api/client';
import { CASE_PRIORITIES, CASE_SEVERITIES, CASE_STATUSES } from '../api/types';
import type {
  CasePriority,
  CaseSeverity,
  CaseStatus,
  CaseSummary,
} from '../api/types';
import { useApi } from '../hooks/useApi';
import { formatDateTime, shortId } from '../lib/format';
import { Badge } from '../components/Badge';
import type { Tone } from '../components/Badge';
import { Panel } from '../components/Panel';
import { EmptyState, LoadingState } from '../components/States';

/** Visual weight per priority. Severity is rendered separately. */
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

type SortKey = 'priority' | 'sla' | 'recent' | 'activity';

interface Filters {
  query: string;
  status: CaseStatus | 'all';
  priority: CasePriority | 'all';
  severity: CaseSeverity | 'all';
  tag: string | 'all';
  overdueOnly: boolean;
  unassignedOnly: boolean;
}

const EMPTY_FILTERS: Filters = {
  query: '',
  status: 'all',
  priority: 'all',
  severity: 'all',
  tag: 'all',
  overdueOnly: false,
  unassignedOnly: false,
};

function matches(item: CaseSummary, filters: Filters): boolean {
  const needle = filters.query.trim().toLowerCase();
  if (needle !== '') {
    const haystack = `${item.name} ${item.description ?? ''} ${item.tags.join(' ')}`.toLowerCase();
    if (!haystack.includes(needle)) return false;
  }
  if (filters.status !== 'all' && item.status !== filters.status) return false;
  if (filters.priority !== 'all' && item.priority !== filters.priority) return false;
  if (filters.severity !== 'all' && item.severity !== filters.severity) return false;
  if (filters.tag !== 'all' && !item.tags.includes(filters.tag)) return false;
  if (filters.overdueOnly && !item.sla_overdue) return false;
  if (filters.unassignedOnly && item.assigned_to !== null) return false;
  return true;
}

function slaLabel(item: CaseSummary): { text: string; tone: Tone } {
  if (item.sla_due_at === null) return { text: 'no SLA', tone: 'neutral' };
  if (item.closed_at !== null || item.status === 'closed') {
    return { text: `closed ${formatDateTime(item.closed_at)}`, tone: 'neutral' };
  }
  if (item.sla_overdue) return { text: `overdue ${formatDateTime(item.sla_due_at)}`, tone: 'danger' };
  return { text: `due ${formatDateTime(item.sla_due_at)}`, tone: 'info' };
}

function NewCaseDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
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

export function CasesPage() {
  const { data, reload, loading, error } = useApi<CaseSummary[]>('/api/v1/dashboard/cases');
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<SortKey>('priority');
  const [creating, setCreating] = useState(false);

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    for (const item of data ?? []) for (const tag of item.tags) tags.add(tag);
    return [...tags].sort();
  }, [data]);

  const rows = useMemo(() => {
    const filtered = (data ?? []).filter((item) => matches(item, filters));
    const sorted = [...filtered];
    sorted.sort((a, b) => {
      switch (sort) {
        case 'priority':
          return (
            PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] ||
            a.name.localeCompare(b.name)
          );
        case 'sla': {
          // Breached deadlines float to the top, soonest next.
          if (a.sla_overdue !== b.sla_overdue) return a.sla_overdue ? -1 : 1;
          const aDue = a.sla_due_at ?? '9999';
          const bDue = b.sla_due_at ?? '9999';
          return aDue.localeCompare(bDue);
        }
        case 'activity': {
          const aAt = a.last_activity ?? '';
          const bAt = b.last_activity ?? '';
          return bAt.localeCompare(aAt);
        }
        case 'recent':
        default: {
          const aAt = a.updated_at ?? a.created_at ?? '';
          const bAt = b.updated_at ?? b.created_at ?? '';
          return bAt.localeCompare(aAt);
        }
      }
    });
    return sorted;
  }, [data, filters, sort]);

  const overdueCount = (data ?? []).filter((item) => item.sla_overdue).length;
  const unassignedCount = (data ?? []).filter((item) => item.assigned_to === null).length;
  const activeCount = (data ?? []).filter(
    (item) => item.status === 'open' || item.status === 'active',
  ).length;

  const filtersActive =
    filters.status !== 'all' ||
    filters.priority !== 'all' ||
    filters.severity !== 'all' ||
    filters.tag !== 'all' ||
    filters.overdueOnly ||
    filters.unassignedOnly ||
    filters.query.trim() !== '';

  return (
    <div className="page-stack">
      <header className="hero-head">
        <div>
          <span className="eyebrow">Investigations</span>
          <h1>Cases</h1>
          <p>
            One workspace per investigation. Evidence, network, hypotheses and notes stay
            together.
          </p>
        </div>
        <div className="hero-actions">
          <button className="button button--dark" onClick={() => setCreating(true)}>
            + New investigation
          </button>
        </div>
      </header>

      <div className="metric-grid">
        <div className="metric metric-blue">
          <div className="metric-value">{activeCount}</div>
          <div className="metric-label">Open or active</div>
        </div>
        <div className={`metric ${overdueCount > 0 ? 'metric-red' : 'metric-violet'}`}>
          <div className="metric-value">{overdueCount}</div>
          <div className="metric-label">SLA breached</div>
        </div>
        <div className="metric metric-violet">
          <div className="metric-value">{unassignedCount}</div>
          <div className="metric-label">Unassigned</div>
        </div>
        <div className="metric">
          <div className="metric-value">{(data ?? []).length}</div>
          <div className="metric-label">Total investigations</div>
        </div>
      </div>

      <Panel
        title="Filters"
        description="Narrow the queue by triage state."
        actions={
          filtersActive ? (
            <button type="button" className="btn btn--ghost btn--small" onClick={() => setFilters(EMPTY_FILTERS)}>
              Clear
            </button>
          ) : undefined
        }
      >
        <div className="filter-bar">
          <div className="search-field">
            <span>⌕</span>
            <input
              value={filters.query}
              onChange={(event) => setFilters({ ...filters, query: event.target.value })}
              placeholder="Search name, description or tag…"
              aria-label="Search cases"
            />
          </div>
          <select
            className="filter-select"
            value={filters.status}
            onChange={(event) => setFilters({ ...filters, status: event.target.value as Filters['status'] })}
            aria-label="Filter by status"
          >
            <option value="all">All statuses</option>
            {CASE_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value.replace('_', ' ')}
              </option>
            ))}
          </select>
          <select
            className="filter-select"
            value={filters.priority}
            onChange={(event) => setFilters({ ...filters, priority: event.target.value as Filters['priority'] })}
            aria-label="Filter by priority"
          >
            <option value="all">All priorities</option>
            {CASE_PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <select
            className="filter-select"
            value={filters.severity}
            onChange={(event) => setFilters({ ...filters, severity: event.target.value as Filters['severity'] })}
            aria-label="Filter by severity"
          >
            <option value="all">All severities</option>
            {CASE_SEVERITIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <select
            className="filter-select"
            value={filters.tag}
            onChange={(event) => setFilters({ ...filters, tag: event.target.value as Filters['tag'] })}
            aria-label="Filter by tag"
          >
            <option value="all">All tags</option>
            {allTags.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>
          <select
            className="filter-select"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortKey)}
            aria-label="Sort cases"
          >
            <option value="priority">Sort: priority</option>
            <option value="sla">Sort: SLA deadline</option>
            <option value="activity">Sort: last activity</option>
            <option value="recent">Sort: recently updated</option>
          </select>
          <label className="filter-toggle">
            <input
              type="checkbox"
              checked={filters.overdueOnly}
              onChange={(event) => setFilters({ ...filters, overdueOnly: event.target.checked })}
            />
            Overdue only
          </label>
          <label className="filter-toggle">
            <input
              type="checkbox"
              checked={filters.unassignedOnly}
              onChange={(event) => setFilters({ ...filters, unassignedOnly: event.target.checked })}
            />
            Unassigned only
          </label>
        </div>
      </Panel>

      {error !== null && (
        <div className="inline-error">
          {error} <button type="button" className="btn btn--small" onClick={reload}>Retry</button>
        </div>
      )}

      {loading && <LoadingState label="Loading investigations…" />}

      {!loading && (data ?? []).length === 0 && (
        <EmptyState
          title="No investigations yet"
          message="Create an investigation to start collecting evidence against it."
          endpoint="GET /api/v1/dashboard/cases"
        />
      )}

      {!loading && (data ?? []).length > 0 && rows.length === 0 && (
        <EmptyState
          title="No matches"
          message="No investigation matches the current filters. Clear them to see the full queue."
        />
      )}

      {rows.length > 0 && (
        <section className="case-list">
          {rows.map((item) => {
            const sla = slaLabel(item);
            return (
              <Link className="case-row" to={`/cases/${item.case_id}`} key={item.case_id}>
                <div className="case-row__identity">
                  <span className="case-icon">◇</span>
                  <div>
                    <h3>{item.name}</h3>
                    <p>{item.description ?? <span className="hint">No description</span>}</p>
                    {item.tags.length > 0 && (
                      <p className="tag-row">
                        {item.tags.map((tag) => (
                          <span className="tag" key={tag}>
                            {tag}
                          </span>
                        ))}
                      </p>
                    )}
                  </div>
                </div>
                <div className="case-row__badges">
                  <Badge tone={STATUS_TONE[item.status]}>{item.status.replace('_', ' ')}</Badge>
                  <Badge tone={PRIORITY_TONE[item.priority]} title="Triage priority">
                    {item.priority}
                  </Badge>
                  <Badge tone={SEVERITY_TONE[item.severity]} title="Impact severity">
                    {item.severity}
                  </Badge>
                  <Badge tone={sla.tone} title="SLA status">
                    {sla.text}
                  </Badge>
                  {item.assigned_to === null ? (
                    <Badge tone="warn" title="No owner assigned">
                      unassigned
                    </Badge>
                  ) : (
                    <Badge tone="neutral" title={`Owner ${item.assigned_to}`}>
                      {shortId(item.assigned_to, 8)}
                    </Badge>
                  )}
                </div>
                <div className="case-row__metrics">
                  <span>
                    <b>{item.counts.evidence}</b> evidence
                  </span>
                  <span>
                    <b>{item.counts.entities}</b> entities
                  </span>
                  <span>
                    <b>{item.counts.relationships}</b> links
                  </span>
                  <span className="case-row__arrow">→</span>
                </div>
              </Link>
            );
          })}
        </section>
      )}

      <p className="toolbar-note">
        {rows.length} of {(data ?? []).length} shown · live from PostgreSQL
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
