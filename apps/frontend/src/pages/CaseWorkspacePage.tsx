import { Link, useParams } from 'react-router-dom';
import { Badge } from '../components/Badge';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
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
 * No case-detail endpoint exists (`GET /api/v1/cases/{id}`), so the overview
 * panels state that plainly and link to the sub-screens, which do have live
 * or session-backed data.
 */
export function CaseWorkspacePage() {
  const { caseId = 'unknown' } = useParams();
  const { evidence, sources, analysis } = useSession();

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="page-eyebrow">Case workspace</p>
          <h1 className="page-title">
            <span className="mono">{caseId}</span>
          </h1>
          <p className="page-sub">
            Case metadata requires <code>GET /api/v1/cases/{'{id}'}</code>, which is not implemented
            yet. Sub-screens below show real API or session data.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/">
            ← All cases
          </Link>
        </div>
      </header>

      <div className="grid-2">
        <Panel title="Overview">
          <dl className="kv">
            <dt>Case ID</dt>
            <dd className="mono">{caseId}</dd>
            <dt>Name</dt>
            <dd>
              <Badge tone="warn">unavailable</Badge>
            </dd>
            <dt>Status</dt>
            <dd>
              <Badge tone="warn">unavailable</Badge>
            </dd>
            <dt>Created</dt>
            <dd>
              <Badge tone="warn">unavailable</Badge>
            </dd>
          </dl>
          <EmptyState
            title="Case record not exposed"
            message="Neither the case name, status nor timestamps can be read back: the API has no case routes yet. The workspace is addressable by ID so navigation and sub-screens work end to end."
            endpoint="GET /api/v1/cases/{id}"
          />
        </Panel>

        <Panel title="Session data" description="Everything loaded or created in this browser session.">
          <dl className="kv">
            <dt>Evidence records</dt>
            <dd>{evidence.length}</dd>
            <dt>Sources registered</dt>
            <dd>{sources.length}</dd>
            <dt>Analysis runs</dt>
            <dd>{analysis === null ? 0 : 1}</dd>
            <dt>Hypotheses returned</dt>
            <dd>{analysis === null ? 0 : analysis.hypotheses.length}</dd>
          </dl>
          <p className="hint">
            Session state resets on reload — the backend exposes no list endpoints to re-read it.
          </p>
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
