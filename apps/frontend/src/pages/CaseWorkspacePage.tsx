import { Link, useParams } from 'react-router-dom';
import { apiUrl } from '../api/client';
import type { CaseWorkspace, InvestigationCase } from '../api/types';
import { Badge } from '../components/Badge';
import { Panel } from '../components/Panel';
import { ErrorState, LoadingState } from '../components/States';
import { useApi } from '../hooks/useApi';
import { formatDateTime } from '../lib/format';
import { useSession } from '../store/session';

interface WorkspaceTile {
  readonly to: string;
  readonly label: string;
  readonly description: string;
}

const TILES: readonly WorkspaceTile[] = [
  {
    to: '/evidence',
    label: 'Evidence',
    description: 'Fetch by ID, ingest new records, inspect provenance.',
  },
  { to: '/timeline', label: 'Timeline', description: 'Observed → collected intervals.' },
  { to: '/graph', label: 'Graph', description: 'Actor links from analysis hypotheses.' },
  { to: '/attribution', label: 'Attribution', description: 'Scores, explanations, evidence counts.' },
  { to: '/hypotheses', label: 'Hypotheses', description: 'Run and compare competing explanations.' },
  { to: '/sources', label: 'Sources', description: 'Registry entries and reliability.' },
  { to: '/reports', label: 'Reports', description: 'Section checklist and export plan.' },
];

/**
 * Screen 2 — case workspace.
 *
 * Case metadata is loaded from the durable case registry while sub-screens
 * progressively surface the evidence and analysis services.
 */
export function CaseWorkspacePage() {
  const { caseId = 'unknown' } = useParams();
  const { evidence, sources, analysis } = useSession();
  const workspace = useApi<CaseWorkspace>(
    caseId === 'unknown' ? null : apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/workspace`),
  );
  const caseResource = useApi<InvestigationCase>(
    caseId === 'unknown' ? null : apiUrl(`/v1/cases/${encodeURIComponent(caseId)}`),
  );
  const investigation = caseResource.data;

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="page-eyebrow">Case workspace</p>
          <h1 className="page-title">
            {investigation?.name ?? <span className="mono">{caseId}</span>}
          </h1>
          <p className="page-sub">
            Evidence-first analysis workspace with a durable case record and auditable activity.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/">
            ← All cases
          </Link>
        </div>
      </header>

      <div className="grid-2">
        <Panel title="Case overview" description="Durable investigation record.">
          {caseResource.loading && <LoadingState label="Loading case details…" />}
          {caseResource.error !== null && <ErrorState message={caseResource.error} onRetry={caseResource.reload} />}
          {investigation !== null && (
            <dl className="kv">
              <dt>Case ID</dt>
              <dd className="mono">{investigation.case_id}</dd>
              <dt>Name</dt>
              <dd>{investigation.name}</dd>
              <dt>Status</dt>
              <dd>
                <Badge tone="info">{investigation.status}</Badge>
              </dd>
              <dt>Created</dt>
              <dd>{formatDateTime(investigation.created_at)}</dd>
              {investigation.description !== null && (
                <>
                  <dt>Scope</dt>
                  <dd>{investigation.description}</dd>
                </>
              )}
            </dl>
          )}
        </Panel>

        <Panel title="Session data" description="Everything loaded or created in this browser session.">
          <dl className="kv">
            <dt>Evidence records</dt>
            <dd>{workspace.data?.counts.evidence ?? evidence.length}</dd>
            <dt>Sources registered</dt>
            <dd>{sources.length}</dd>
            <dt>Analysis runs</dt>
            <dd>{analysis === null ? 0 : 1}</dd>
            <dt>Hypotheses returned</dt>
            <dd>{analysis === null ? 0 : analysis.hypotheses.length}</dd>
          </dl>
          <p className="hint">Durable workspace counts are loaded from the case API; session data remains available for interactive runs.</p>
        </Panel>
      </div>

      <Panel title="Sub-screens" description="Jump into the investigation views.">
        <ul className="link-cards">
          {TILES.map((tile) => (
            <li key={tile.to} className="link-card">
              <Link className="link-card__title" to={tile.to}>
                {tile.label}
              </Link>
              <p className="link-card__desc">{tile.description}</p>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
