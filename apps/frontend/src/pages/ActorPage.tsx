import { Link, useParams } from 'react-router-dom';
import { Badge } from '../components/Badge';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { SectionCard } from '../components/SectionCard';
import { formatPercent, shortId } from '../lib/format';
import { useSession } from '../store/session';
import type { SyntheticHypothesis } from '../api/types';

interface SectionSpec {
  readonly key: string;
  readonly title: string;
  /** Endpoint that would back this section once the actor API ships. */
  readonly endpoint: string;
}

/** Actor profile sections required by plan §23. */
const SECTIONS: readonly SectionSpec[] = [
  { key: 'aliases', title: 'Aliases', endpoint: 'GET /api/v1/actors/{id}/aliases' },
  { key: 'identifiers', title: 'Identifiers', endpoint: 'GET /api/v1/actors/{id}/identifiers' },
  { key: 'confidence', title: 'Confidence', endpoint: 'GET /api/v1/actors/{id}/confidence' },
  {
    key: 'evidence-matrix',
    title: 'Evidence matrix',
    endpoint: 'GET /api/v1/actors/{id}/evidence',
  },
  { key: 'timeline', title: 'Timeline', endpoint: 'GET /api/v1/timeline?entity_id={id}' },
  { key: 'graph', title: 'Graph', endpoint: 'GET /api/v1/graph?entity_id={id}' },
  { key: 'stylometry', title: 'Stylometry', endpoint: 'GET /api/v1/actors/{id}/stylometry' },
  { key: 'behavior', title: 'Behaviour', endpoint: 'GET /api/v1/actors/{id}/behaviour' },
  {
    key: 'infrastructure',
    title: 'Infrastructure',
    endpoint: 'GET /api/v1/actors/{id}/infrastructure',
  },
  { key: 'financial', title: 'Financial indicators', endpoint: 'GET /api/v1/actors/{id}/financial' },
  { key: 'contradictions', title: 'Contradictions', endpoint: 'GET /api/v1/actors/{id}/contradictions' },
  { key: 'model-explanation', title: 'Model explanation', endpoint: 'GET /api/v1/actors/{id}/explanations' },
  { key: 'audit', title: 'Audit trail', endpoint: 'GET /api/v1/actors/{id}/audit' },
];

function hypothesesForActor(
  actorId: string,
  hypotheses: readonly SyntheticHypothesis[],
): Array<SyntheticHypothesis & { role: string }> {
  return hypotheses
    .filter(
      (item) => item.source_actor_id === actorId || item.target_actor_id === actorId,
    )
    .map((item) => ({
      ...item,
      role:
        item.source_actor_id === actorId && item.target_actor_id === actorId
          ? 'self'
          : item.source_actor_id === actorId
            ? 'source'
            : 'target',
    }));
}

/**
 * Screen 4 — actor profile.
 *
 * No actor endpoints exist yet, so each of the 13 sections renders an
 * explicit "not available via API" state naming its planned route — except
 * the sections that can honestly use session analysis output (scores and
 * explanations from `POST /api/v1/analysis/synthetic`).
 */
export function ActorPage() {
  const { actorId = 'unknown' } = useParams();
  const { analysis, evidence } = useSession();

  const actorHypotheses =
    analysis === null ? [] : hypothesesForActor(actorId, analysis.hypotheses);
  const hasSessionData = actorHypotheses.length > 0;

  const scoreColumns: ReadonlyArray<Column<SyntheticHypothesis & { role: string }>> = [
    { key: 'id', header: 'Hypothesis', render: (row) => <span className="mono">{shortId(row.hypothesis_id, 8)}</span> },
    { key: 'role', header: 'Actor role', render: (row) => <Badge tone="info">{row.role}</Badge> },
    { key: 'support', header: 'Support', align: 'end', render: (row) => formatPercent(row.support_score) },
    {
      key: 'contradiction',
      header: 'Contradiction',
      align: 'end',
      render: (row) => formatPercent(row.contradiction_score),
    },
    { key: 'final', header: 'Final', align: 'end', render: (row) => <strong>{formatPercent(row.final_score)}</strong> },
    { key: 'status', header: 'Status', render: (row) => <Badge tone="neutral">{row.status}</Badge> },
    {
      key: 'evidence',
      header: 'Evidence',
      align: 'end',
      render: (row) => row.evidence_count,
    },
  ];

  const renderSectionContent = (section: SectionSpec) => {
    switch (section.key) {
      case 'confidence':
      case 'model-explanation':
        if (!hasSessionData) return undefined;
        if (section.key === 'confidence') {
          return (
            <>
              <p className="hint">
                Live scores returned by <code>POST /api/v1/analysis/synthetic</code> for this actor
                (calibrated confidence itself needs the attribution endpoint).
              </p>
              <DataTable
                columns={scoreColumns}
                rows={actorHypotheses}
                rowKey={(row) => row.hypothesis_id}
                caption="Session scores involving this actor"
              />
            </>
          );
        }
        return (
          <>
            <p className="hint">Model explanations attached to this actor&apos;s hypotheses.</p>
            <ul className="bullet-list">
              {actorHypotheses.flatMap((row) =>
                row.explanations.length === 0
                  ? [<li key={`${row.hypothesis_id}-none`} className="hint">No explanations in this hypothesis.</li>]
                  : row.explanations.map((text, index) => (
                      <li key={`${row.hypothesis_id}-${index}`}>{text}</li>
                    )),
              )}
            </ul>
          </>
        );
      case 'timeline':
        if (evidence.length === 0) return undefined;
        return (
          <p>
            {evidence.length} evidence record{evidence.length === 1 ? '' : 's'} in this session.{' '}
            <Link to="/timeline">Open the session timeline →</Link>
          </p>
        );
      case 'graph':
        if (analysis === null) return undefined;
        return (
          <p>
            {analysis.hypotheses.length} hypotheses available to lay out.{' '}
            <Link to="/graph">Open the graph →</Link>
          </p>
        );
      default:
        return undefined;
    }
  };

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="page-eyebrow">Actor profile</p>
          <h1 className="page-title mono">{actorId}</h1>
          <p className="page-sub">
            Actor records are not exposed by the API yet — each section below names the endpoint
            that will fill it. Scores and explanations from a session analysis run render where
            they exist.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/graph">
            Back to graph
          </Link>
          <Link className="btn" to="/hypotheses">
            Run analysis
          </Link>
        </div>
      </header>

      <Panel
        title="Session model output"
        description="Hypotheses from POST /api/v1/analysis/synthetic that involve this actor ID."
      >
        {hasSessionData ? (
          <DataTable
            columns={scoreColumns}
            rows={actorHypotheses}
            rowKey={(row) => row.hypothesis_id}
            caption="Session scores involving this actor"
          />
        ) : (
          <EmptyState
            title="No session analysis for this actor"
            message="Run the synthetic analysis to populate scores for actor IDs, or open this page from a graph node after a run."
            endpoint="POST /api/v1/analysis/synthetic"
          >
            <Link className="btn btn--primary" to="/hypotheses">
              Go to hypotheses
            </Link>
          </EmptyState>
        )}
      </Panel>

      <div className="section-grid">
        {SECTIONS.map((section) => {
          const content = renderSectionContent(section);
          return (
            <SectionCard
              key={section.key}
              title={section.title}
              endpoint={section.endpoint}
              emptyMessage={`No endpoint serves “${section.title}” yet, so this panel stays empty instead of guessing.`}
            >
              {content}
            </SectionCard>
          );
        })}
      </div>
    </div>
  );
}
