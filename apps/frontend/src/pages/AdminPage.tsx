import { useCallback, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiUrl } from '../api/client';
import type { AuditTrailResponse, ModelRegistryResponse, SystemHealth, TeamResponse } from '../api/types';
import { Badge } from '../components/Badge';
import type { Column } from '../components/DataTable';
import { DataTable } from '../components/DataTable';
import type { ModelRunSummary, TeamMember } from '../api/types';
import { ErrorState, LoadingState } from '../components/States';
import { useApi } from '../hooks/useApi';
import { formatDateTime, shortId } from '../lib/format';

const TEAM_URL = apiUrl('/v1/admin/team');
const SYSTEM_URL = apiUrl('/v1/admin/system');
const MODELS_URL = apiUrl('/v1/models');

const PAGE_SIZES = [25, 50, 100] as const;

const TABS = [
  { key: 'team', label: 'Team', hint: 'Analysts, roles and granted permissions' },
  { key: 'audit', label: 'Audit trail', hint: 'Hash-chained ledger of every recorded action' },
  { key: 'system', label: 'System', hint: 'Runtime health, platform counts and model runs' },
] as const;

type TabKey = (typeof TABS)[number]['key'];

function tabFromParam(value: string | null): TabKey {
  return value === 'audit' || value === 'system' ? value : 'team';
}

function auditUrl(limit: number, offset: number, action: string): string {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (action) query.set('action', action);
  return apiUrl(`/v1/admin/audit?${query.toString()}`);
}

/** Any JSON value, rendered for a dense read-only cell. */
function scalar(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value.length > 0 ? value : '—';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** Seconds as `2h 15m` / `45m` / `30s`; the API reports the raw TTL. */
function duration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function elapsed(from: string | null, to: string | null): string {
  if (!from || !to) return '—';
  const start = new Date(from).getTime();
  const end = new Date(to).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return '—';
  return duration((end - start) / 1000);
}

// ---------------------------------------------------------------------------
// Team
// ---------------------------------------------------------------------------

function TeamTab() {
  const { data, loading, error, reload } = useApi<TeamResponse>(TEAM_URL);
  const members = useMemo(() => data?.members ?? [], [data]);

  const maxLoad = useMemo(
    () => members.reduce((peak, member) => Math.max(peak, member.assigned_cases), 0),
    [members],
  );

  const roleCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const member of members) counts.set(member.role, (counts.get(member.role) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [members]);

  // Roles the API advertises but nobody currently holds — usually a dormant
  // role that still has permissions attached, which is worth seeing.
  const declaredRoles = useMemo(
    () => (data?.roles ?? []).filter((role) => !roleCounts.some(([held]) => held === role)),
    [data, roleCounts],
  );

  const columns: ReadonlyArray<Column<TeamMember>> = [
    {
      key: 'name',
      header: 'Name',
      render: (row) => (
        <div className="adm-identity">
          <b>{row.display_name}</b>
          <small className="adm-identity__id mono">{shortId(row.user_id)}</small>
        </div>
      ),
    },
    { key: 'email', header: 'Email', render: (row) => <span className="adm-mono">{row.email}</span> },
    { key: 'role', header: 'Role', render: (row) => <Badge tone="info">{row.role}</Badge> },
    {
      key: 'permissions',
      header: 'Permissions',
      render: (row) =>
        row.permissions.length === 0 ? (
          <span className="adm-faint">No permissions granted</span>
        ) : (
          <div className="adm-chips">
            {row.permissions.map((permission) => (
              <Badge key={permission} tone="neutral" title={permission}>
                {permission}
              </Badge>
            ))}
          </div>
        ),
    },
    {
      key: 'status',
      header: 'Status',
      // State is spelled out, not only coloured — colour alone is not an
      // accessible encoding of "this account cannot sign in".
      render: (row) => (
        <span className={row.is_active ? 'adm-state adm-state--active' : 'adm-state adm-state--inactive'}>
          <span aria-hidden="true" className="adm-state__dot" />
          {row.is_active ? 'Active' : 'Inactive'}
        </span>
      ),
    },
    {
      key: 'last_login',
      header: 'Last login',
      render: (row) => <span className="adm-mono">{formatDateTime(row.last_login_at)}</span>,
    },
    {
      key: 'load',
      header: 'Assigned cases',
      align: 'end',
      render: (row) => {
        const width = maxLoad > 0 ? Math.round((row.assigned_cases / maxLoad) * 100) : 0;
        return (
          <div className="adm-load">
            <span className="adm-load__track" aria-hidden="true">
              <span className="adm-load__fill" style={{ width: `${width}%` }} />
            </span>
            <b>{row.assigned_cases}</b>
          </div>
        );
      },
    },
  ];

  if (loading && data === null) return <LoadingState label="Loading team roster…" />;
  if (error !== null) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="adm-stack">
      <section className="adm-roles" aria-label="Role distribution">
        {roleCounts.length === 0 && <p className="adm-faint">No members are registered on this deployment.</p>}
        {roleCounts.map(([role, count]) => (
          <div className="adm-role" key={role}>
            <b>{count}</b>
            <span>{role}</span>
          </div>
        ))}
        <div className="adm-role adm-role--declared">
          <b>{data?.roles.length ?? 0}</b>
          <span>Declared roles</span>
        </div>
        {declaredRoles.length > 0 && (
          <p className="adm-roles__note">
            Declared with no holder: <span className="adm-mono">{declaredRoles.join(', ')}</span>
          </p>
        )}
      </section>

      <DataTable
        columns={columns}
        rows={members}
        rowKey={(row) => row.user_id}
        caption="Team roster with effective permissions and current case load"
        empty="No team members returned by /v1/admin/team."
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audit trail
// ---------------------------------------------------------------------------

function AuditTab() {
  const [limit, setLimit] = useState<number>(PAGE_SIZES[0]);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);
  const url = useMemo(() => auditUrl(limit, offset, action), [limit, offset, action]);
  const { data, loading, error, reload } = useApi<AuditTrailResponse>(url);

  const entries = useMemo(() => data?.entries ?? [], [data]);
  const actions = useMemo(() => data?.actions ?? [], [data]);
  const total = data?.total ?? 0;
  const first = total === 0 ? 0 : offset + 1;
  const last = offset + entries.length;
  const hasPrev = offset > 0;
  const hasNext = last < total;

  const setActionFilter = useCallback((value: string) => {
    setAction(value);
    setOffset(0);
    setExpanded(null);
  }, []);

  const chainValid = data?.chain_valid ?? null;

  return (
    <div className="adm-stack">
      {/*
        `chain_valid` is recomputed by walking the stored entry hashes server
        side on every read, so this banner reports the result of that
        recomputation rather than a flag the UI set itself.
      */}
      <section
        className={chainValid === false ? 'adm-chain adm-chain--failed' : 'adm-chain adm-chain--ok'}
        role="status"
        aria-live="polite"
      >
        <span className="adm-chain__mark" aria-hidden="true">
          {chainValid === false ? '✕' : '✓'}
        </span>
        <div>
          <b>
            {chainValid === false
              ? 'CHAIN INTEGRITY FAILED'
              : chainValid === true
                ? 'Hash chain verified by recomputation'
                : 'Chain status not yet read'}
          </b>
          <small>
            {chainValid === false
              ? 'Entry hashes do not reconstruct the stored chain. Treat the ledger as untrustworthy and escalate.'
              : chainValid === true
                ? `Each entry hash was recomputed against its predecessor across the ${total} recorded entries.`
                : 'Verifying the ledger against the API…'}
          </small>
        </div>
      </section>

      <div className="adm-toolbar">
        <div className="adm-field">
          <label htmlFor="adm-audit-action">Action</label>
          <select
            id="adm-audit-action"
            className="adm-select"
            value={action}
            onChange={(event) => setActionFilter(event.target.value)}
          >
            <option value="">All actions</option>
            {actions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="adm-field">
          <label htmlFor="adm-audit-limit">Rows</label>
          <select
            id="adm-audit-limit"
            className="adm-select"
            value={limit}
            onChange={(event) => {
              setLimit(Number(event.target.value));
              setOffset(0);
            }}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </div>
        <div className="adm-pager">
          <button
            type="button"
            className="adm-btn"
            disabled={!hasPrev || loading}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            <span aria-hidden="true">←</span> Previous
          </button>
          <span className="adm-pager__count" role="status">
            {total === 0 ? 'No entries' : `${first}–${last} of ${total}`}
          </span>
          <button
            type="button"
            className="adm-btn"
            disabled={!hasNext || loading}
            onClick={() => setOffset(offset + limit)}
          >
            Next <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>

      {loading && data === null && <LoadingState label="Loading audit trail…" />}
      {error !== null && <ErrorState message={error} onRetry={reload} />}

      {data !== null && error === null && (
        <div className="table-wrap">
          <table className="data-table adm-audit">
            <caption className="data-table__caption">
              Ledger entries, oldest first. Each entry hash is derived from the previous entry, so any edit
              breaks the chain.
            </caption>
            <thead>
              <tr>
                <th scope="col" className="adm-narrow">Seq</th>
                <th scope="col">Time</th>
                <th scope="col">Action</th>
                <th scope="col">Actor</th>
                <th scope="col">Entity</th>
                <th scope="col">Case</th>
                <th scope="col">Entry hash</th>
              </tr>
            </thead>
            <tbody>
              {entries.length === 0 ? (
                <tr>
                  <td colSpan={7} className="data-table__empty">
                    No ledger entries match this filter.
                  </td>
                </tr>
              ) : (
                entries.flatMap((entry) => {
                  const isOpen = expanded === entry.seq;
                  return [
                    <tr key={`row-${entry.seq}`} className="adm-audit__row">
                      <td className="adm-mono adm-narrow">{entry.seq}</td>
                      <td className="adm-mono adm-nowrap">{formatDateTime(entry.occurred_at)}</td>
                      <td>
                        <span className="adm-action">{entry.action}</span>
                      </td>
                      <td className="adm-mono">{entry.actor ?? '—'}</td>
                      <td>
                        {entry.entity_type === null && entry.entity_id === null ? (
                          <span className="adm-faint">—</span>
                        ) : (
                          <span className="adm-mono" title={entry.entity_id ?? undefined}>
                            {entry.entity_type ?? 'entity'}
                            {entry.entity_id ? ` / ${shortId(entry.entity_id)}` : ''}
                          </span>
                        )}
                      </td>
                      <td>
                        {entry.case_id === null ? (
                          <span className="adm-faint">—</span>
                        ) : (
                          <span className="adm-mono" title={entry.case_name ?? entry.case_id}>
                            {entry.case_name ?? shortId(entry.case_id)}
                          </span>
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="adm-hash"
                          aria-expanded={isOpen}
                          aria-controls={`adm-payload-${entry.seq}`}
                          onClick={() => setExpanded(isOpen ? null : entry.seq)}
                          title={entry.entry_hash}
                        >
                          <span className="adm-mono">{shortId(entry.entry_hash, 10)}</span>
                          <span className="adm-hash__hint" aria-hidden="true">
                            {isOpen ? '−' : '+'}
                          </span>
                        </button>
                      </td>
                    </tr>,
                    isOpen ? (
                      <tr key={`payload-${entry.seq}`} className="adm-audit__payload-row">
                        <td colSpan={7}>
                          <div className="adm-payload" id={`adm-payload-${entry.seq}`}>
                            <p className="adm-payload__meta">
                              <span>
                                Previous hash: <span className="adm-mono">{entry.prev_hash ?? 'genesis (first entry)'}</span>
                              </span>
                              <span>
                                Entry hash: <span className="adm-mono">{entry.entry_hash}</span>
                              </span>
                            </p>
                            <pre className="adm-json">{JSON.stringify(entry.payload, null, 2)}</pre>
                          </div>
                        </td>
                      </tr>
                    ) : null,
                  ];
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

const PLATFORM_COUNTS: ReadonlyArray<{ key: keyof SystemHealth['counts']; label: string }> = [
  { key: 'cases', label: 'Cases' },
  { key: 'evidence', label: 'Evidence' },
  { key: 'entities', label: 'Entities' },
  { key: 'relationships', label: 'Relationships' },
  { key: 'assessments', label: 'Assessments' },
];

function ModelRuns() {
  const { data, loading, error, reload } = useApi<ModelRegistryResponse>(MODELS_URL);
  const runs = useMemo(() => data?.runs ?? [], [data]);

  const columns: ReadonlyArray<Column<ModelRunSummary>> = [
    {
      key: 'model',
      header: 'Model',
      render: (row) => (
        <div className="adm-identity">
          <b>{row.model_id}</b>
          {/* The run id is what an assessment record cites, so it stays on
              screen rather than only in a tooltip. */}
          <small className="adm-identity__id mono" title={`Run ${row.run_id}`}>
            {shortId(row.run_id)}
          </small>
        </div>
      ),
    },
    { key: 'version', header: 'Version', render: (row) => <span className="adm-mono">{row.model_version}</span> },
    { key: 'dataset', header: 'Dataset', render: (row) => <span className="adm-mono">{row.dataset_version}</span> },
    { key: 'features', header: 'Feature version', render: (row) => <span className="adm-mono">{row.feature_version}</span> },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <Badge tone={row.status === 'succeeded' || row.status === 'completed' ? 'ok' : row.status === 'failed' ? 'danger' : 'neutral'}>
          {row.status}
        </Badge>
      ),
    },
    { key: 'seed', header: 'Seed', align: 'end', render: (row) => <span className="adm-mono">{row.seed}</span> },
    {
      key: 'duration',
      header: 'Duration',
      align: 'end',
      render: (row) => (
        <span className="adm-mono" title={`${row.started_at ?? '—'} → ${row.finished_at ?? '—'}`}>
          {elapsed(row.started_at, row.finished_at)}
        </span>
      ),
    },
  ];

  if (loading && data === null) return <LoadingState label="Loading model registry…" />;
  if (error !== null) return <ErrorState message={error} onRetry={reload} />;

  return (
    <>
      <DataTable
        columns={columns}
        rows={runs}
        rowKey={(row) => row.run_id}
        caption="Model runs — the dataset, feature version and seed an attribution number was produced under"
        empty="No model runs are recorded on this deployment."
      />
      <details className="adm-details">
        <summary>Run metrics ({data?.total ?? runs.length} recorded)</summary>
        {runs.length === 0 ? (
          <p className="adm-faint">No run metrics to show.</p>
        ) : (
          <ul className="adm-metric-list">
            {runs.map((row) => (
              <li key={row.run_id}>
                <b className="adm-mono">{shortId(row.run_id)}</b>
                <span className="adm-mono">{row.model_id}</span>
                <pre className="adm-json adm-json--inline">{JSON.stringify(row.metrics, null, 2)}</pre>
              </li>
            ))}
          </ul>
        )}
      </details>
    </>
  );
}

function SystemTab() {
  const { data, loading, error, reload } = useApi<SystemHealth>(SYSTEM_URL);

  if (loading && data === null) return <LoadingState label="Reading system health…" />;
  if (error !== null) return <ErrorState message={error} onRetry={reload} />;
  if (data === null) return <ErrorState message="No system health payload was returned." onRetry={reload} />;

  const facts: ReadonlyArray<{ label: string; value: string; tone?: 'ok' | 'danger' | 'neutral' }> = [
    { label: 'API status', value: data.api_status, tone: data.api_status === 'ok' ? 'ok' : 'danger' },
    { label: 'Database status', value: data.database_status, tone: data.database_status === 'ok' ? 'ok' : 'danger' },
    { label: 'Environment', value: data.environment },
    { label: 'Auth mode', value: data.auth_mode },
    { label: 'Session TTL', value: duration(data.auth_session_ttl_s) },
    { label: 'Live socket', value: data.live_socket, tone: data.live_socket === 'connected' ? 'ok' : 'neutral' },
    {
      label: 'Audit chain',
      value: data.chain_valid ? 'Verified by recomputation' : 'FAILED',
      tone: data.chain_valid ? 'ok' : 'danger',
    },
  ];

  const adapters = Object.entries(data.adapters);
  const metrics = Object.entries(data.metrics);

  return (
    <div className="adm-stack">
      <dl className="adm-facts">
        {facts.map((fact) => (
          <div className="adm-fact" key={fact.label}>
            <dt>{fact.label}</dt>
            <dd>
              <Badge tone={fact.tone ?? 'neutral'}>{fact.value}</Badge>
            </dd>
          </div>
        ))}
      </dl>

      <section className="adm-block" aria-label="Platform counts">
        <h3 className="adm-block__title">Platform counts</h3>
        <div className="adm-counts">
          {PLATFORM_COUNTS.map(({ key, label }) => (
            <div className="adm-count" key={key}>
              <b>{data.counts[key]}</b>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="adm-block" aria-label="Adapters">
        <h3 className="adm-block__title">Adapters</h3>
        {adapters.length === 0 ? (
          <p className="adm-faint">No adapters are registered on this deployment.</p>
        ) : (
          <ul className="adm-adapters">
            {adapters.map(([name, state]) => (
              <li key={name}>
                <b>{name}</b>
                <span className="adm-mono">{state}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="adm-block" aria-label="Runtime metrics">
        <h3 className="adm-block__title">Metrics</h3>
        {metrics.length === 0 ? (
          <p className="adm-faint">The runtime reported no metrics.</p>
        ) : (
          <dl className="adm-metrics">
            {metrics.map(([name, value]) => (
              <div className="adm-metric" key={name}>
                <dt className="adm-mono">{name}</dt>
                <dd className="adm-mono">{scalar(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section className="adm-block" aria-label="Model runs">
        <h3 className="adm-block__title">Model runs</h3>
        <p className="adm-block__desc">
          Every attribution score is produced by one of these runs. Quote the run id, dataset version and seed
          alongside a number to make it traceable.
        </p>
        <ModelRuns />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function AdminPage() {
  const [params, setParams] = useSearchParams();
  const tab = tabFromParam(params.get('tab'));
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const select = useCallback(
    (key: TabKey) => {
      setParams({ tab: key }, { replace: true });
    },
    [setParams],
  );

  const onTabKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>) => {
      const index = TABS.findIndex((entry) => entry.key === tab);
      let next: number | null = null;
      if (event.key === 'ArrowRight') next = (index + 1) % TABS.length;
      else if (event.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = TABS.length - 1;
      if (next === null) return;
      event.preventDefault();
      const key = TABS[next]?.key;
      if (key === undefined) return;
      select(key);
      tabRefs.current[key]?.focus();
    },
    [select, tab],
  );

  const active = TABS.find((entry) => entry.key === tab) ?? TABS[0];

  return (
    <div className="page-stack adm-page">
      <header className="hero-head">
        <div>
          <span className="eyebrow">System administration</span>
          <h1>Administration</h1>
          <p>Who is on the platform, what the ledger recorded, and what the runtime currently reports.</p>
        </div>
      </header>

      <div className="adm-tabs" role="tablist" aria-label="Administration sections">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            id={`adm-tab-${entry.key}`}
            aria-selected={entry.key === tab}
            aria-controls={`adm-panel-${entry.key}`}
            tabIndex={entry.key === tab ? 0 : -1}
            ref={(node) => {
              tabRefs.current[entry.key] = node;
            }}
            className={entry.key === tab ? 'adm-tab adm-tab--active' : 'adm-tab'}
            onClick={() => select(entry.key)}
            onKeyDown={onTabKeyDown}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`adm-panel-${tab}`}
        aria-labelledby={`adm-tab-${tab}`}
        className="adm-panel"
        tabIndex={0}
      >
        <p className="adm-panel__hint">{active?.hint}</p>
        {tab === 'team' && <TeamTab />}
        {tab === 'audit' && <AuditTab />}
        {tab === 'system' && <SystemTab />}
      </div>
    </div>
  );
}
