import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, apiUrl, formatApiError } from '../api/client';
import type { InvestigationCase } from '../api/types';
import { Badge } from '../components/Badge';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { Panel } from '../components/Panel';
import { formatDate } from '../lib/format';
import { useApi } from '../hooks/useApi';

interface ScreenLink {
  readonly to: string;
  readonly label: string;
  readonly description: string;
  readonly status: 'live' | 'session' | 'planned';
  readonly statusLabel: string;
}

const SCREEN_LINKS: readonly ScreenLink[] = [
  {
    to: '/evidence',
    label: 'Evidence explorer',
    description: 'Fetch, ingest and inspect evidence with provenance.',
    status: 'live',
    statusLabel: 'live API',
  },
  {
    to: '/timeline',
    label: 'Timeline',
    description: 'Observed → collected intervals from session evidence.',
    status: 'session',
    statusLabel: 'session data',
  },
  {
    to: '/graph',
    label: 'Graph',
    description: 'Actor relationship layout from analysis hypotheses.',
    status: 'session',
    statusLabel: 'session data',
  },
  {
    to: '/attribution',
    label: 'Attribution',
    description: 'Raw, support, contradiction and final scores.',
    status: 'session',
    statusLabel: 'session data',
  },
  {
    to: '/hypotheses',
    label: 'Hypotheses',
    description: 'Run the synthetic analysis and compare hypotheses.',
    status: 'live',
    statusLabel: 'live API',
  },
  {
    to: '/sources',
    label: 'Sources',
    description: 'Register sources and track reliability.',
    status: 'live',
    statusLabel: 'live API',
  },
  {
    to: '/reports',
    label: 'Reports',
    description: 'Section checklist and export plan.',
    status: 'planned',
    statusLabel: 'export planned',
  },
];

function linkTone(status: ScreenLink['status']): 'ok' | 'info' | 'warn' {
  if (status === 'live') return 'ok';
  if (status === 'session') return 'info';
  return 'warn';
}

/**
 * Screen 1 — case list + "New case" form.
 *
 * Durable case registry backed by the API. A case is the analyst's entry
 * point into all evidence and assessment work; creation immediately opens its
 * workspace rather than leaving a dead-end form.
 */
export function CasesPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [openId, setOpenId] = useState('');
  const [submission, setSubmission] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const { data: cases, loading, error, reload } = useApi<InvestigationCase[]>(apiUrl('/v1/cases'));

  const caseColumns: ReadonlyArray<Column<InvestigationCase>> = [
    {
      key: 'name',
      header: 'Investigation',
      render: (item) => (
        <Link className="table-link" to={`/cases/${encodeURIComponent(item.case_id)}`}>
          {item.name}
        </Link>
      ),
    },
    { key: 'status', header: 'Status', render: (item) => <Badge tone="info">{item.status}</Badge> },
    { key: 'created', header: 'Created', render: (item) => formatDate(item.created_at) },
  ];

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === '') {
      setSubmission('A case name is required.');
      return;
    }
    const payload = {
      name: trimmed,
      description: description.trim() === '' ? null : description.trim(),
    };
    setCreating(true);
    setSubmission(null);
    api.createCase(payload)
      .then((created) => {
        reload();
        navigate(`/cases/${encodeURIComponent(created.case_id)}`);
      })
      .catch((reason: unknown) => setSubmission(formatApiError(reason)))
      .finally(() => setCreating(false));
  };

  const handleOpenWorkspace = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = openId.trim();
    if (trimmed !== '') navigate(`/cases/${encodeURIComponent(trimmed)}`);
  };

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Cases</h1>
          <p className="page-sub">
            A durable evidence-first workspace for each authorized investigation.
          </p>
        </div>
      </header>

      <div className="grid-2">
        <Panel title="Active investigations" description="Name · status · created">
          {loading && <LoadingState label="Loading investigations…" />}
          {error !== null && <ErrorState message={error} onRetry={reload} />}
          {!loading && error === null && <DataTable<InvestigationCase>
            columns={caseColumns}
            rows={cases ?? []}
            rowKey={(item) => item.case_id}
            caption="Cases"
            empty={
              <EmptyState
                title="No investigations yet"
                message="Create the first case to establish an auditable investigation workspace."
                endpoint="GET /api/v1/cases"
              />
            }
          />}
          <form className="inline-form" onSubmit={handleOpenWorkspace}>
            <div className="field">
              <label htmlFor="open-case-id">Open a case workspace by ID</label>
              <input
                id="open-case-id"
                name="caseId"
                type="text"
                value={openId}
                onChange={(event) => setOpenId(event.target.value)}
                placeholder="case UUID"
                autoComplete="off"
              />
            </div>
            <button type="submit" className="btn">
              Open workspace
            </button>
          </form>
        </Panel>

        <Panel title="Open an investigation" description="Creates a durable case and audit event.">
          <form className="form" onSubmit={handleCreate}>
            <div className="field">
              <label htmlFor="case-name">Case name (required)</label>
              <input
                id="case-name"
                name="name"
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Forum marketplace fraud ring"
                required
                maxLength={256}
                autoComplete="off"
              />
            </div>
            <div className="field">
              <label htmlFor="case-description">Description</label>
              <textarea
                id="case-description"
                name="description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                placeholder="Scope, hypotheses under test, data-source caveats…"
              />
            </div>
            <div className="form-actions">
              <button type="submit" className="btn btn--primary" disabled={creating}>
                {creating ? 'Creating…' : 'Create case'}
              </button>
              <span className="hint">Synthetic and authorized data only.</span>
            </div>
          </form>
          {submission !== null && (
            <p className="status status--error" role="alert">
              {submission}
            </p>
          )}
        </Panel>
      </div>

      <Panel title="Data surfaces" description="What each screen can actually show today.">
        <ul className="link-cards">
          {SCREEN_LINKS.map((screen) => (
            <li key={screen.to} className="link-card">
              <div className="link-card__head">
                <Link to={screen.to} className="link-card__title">
                  {screen.label}
                </Link>
                <Badge tone={linkTone(screen.status)}>{screen.statusLabel}</Badge>
              </div>
              <p className="link-card__desc">{screen.description}</p>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
