import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Badge } from '../components/Badge';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import type { CaseCreate } from '../api/types';

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
 * `GET /api/v1/cases` and `POST /api/v1/cases` do not exist yet
 * (`src/aegis/api/app.py`), so the table shows an honest empty state and the
 * form prepares (but does not send) its payload.
 */
export function CasesPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [openId, setOpenId] = useState('');
  const [submission, setSubmission] = useState<string | null>(null);

  const caseColumns: ReadonlyArray<Column<never>> = [
    { key: 'name', header: 'Name', render: () => null },
    { key: 'status', header: 'Status', render: () => null },
    { key: 'created', header: 'Created', render: () => null },
  ];

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === '') {
      setSubmission('A case name is required.');
      return;
    }
    const payload: CaseCreate = {
      name: trimmed,
      description: description.trim() === '' ? null : description.trim(),
    };
    setSubmission(
      `POST /api/v1/cases is not implemented yet, so nothing was sent. Payload prepared: ${JSON.stringify(payload)}`,
    );
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
            Investigation workspaces. Case listing needs <code>GET /api/v1/cases</code>, which the
            backend does not serve yet — nothing is fabricated here.
          </p>
        </div>
      </header>

      <div className="grid-2">
        <Panel title="Case list" description="Name · status · created">
          <DataTable<never>
            columns={caseColumns}
            rows={[]}
            rowKey={() => ''}
            caption="Cases"
            empty={
              <EmptyState
                title="No cases available"
                message="The API serves no case-listing endpoint, so this table stays empty instead of showing mock rows."
                endpoint="GET /api/v1/cases"
              />
            }
          />
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

        <Panel title="New case" description="Prepares the CaseCreate payload for the API.">
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
              <button type="submit" className="btn btn--primary">
                Create case
              </button>
              <span className="hint">Schema: CaseCreate (src/aegis/schemas/evidence.py)</span>
            </div>
          </form>
          {submission !== null && (
            <p className="status status--info" role="status">
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
