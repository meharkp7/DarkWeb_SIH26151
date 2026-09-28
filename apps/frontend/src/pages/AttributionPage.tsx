import { Link } from 'react-router-dom';
import { ScoreBars } from '../components/ScoreBars';
import { Badge } from '../components/Badge';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { formatPercent, shortId } from '../lib/format';
import { useSession } from '../store/session';

/**
 * Screen 7 — attribution assessment.
 *
 * Scores come from the session analysis run (`POST /api/v1/analysis/synthetic`,
 * which persists hypotheses). Model version, calibrated confidence and the
 * per-assessment evidence IDs live in `AttributionAssessment`, for which no
 * endpoint exists yet — those panels say so instead of inventing values.
 */
export function AttributionPage() {
  const { analysis } = useSession();

  if (analysis === null) {
    return (
      <div className="stack">
        <header className="page-header">
          <div>
            <h1 className="page-title">Attribution assessment</h1>
            <p className="page-sub">
              Transparent scores with their evidence — no black boxes.
            </p>
          </div>
        </header>
        <Panel title="Assessment">
          <EmptyState
            title="No assessment to show"
            message="Attribution scores appear after a synthetic analysis run in this session. The dedicated attribution endpoint does not exist yet."
            endpoint="POST /api/v1/analysis/synthetic"
          >
            <Link className="btn btn--primary" to="/hypotheses">
              Run synthetic analysis
            </Link>
          </EmptyState>
        </Panel>
      </div>
    );
  }

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Attribution assessment</h1>
          <p className="page-sub">
            Scores from run <span className="mono">seed={analysis.seed}</span>. Every value here was
            returned by the API — fields the API does not serve yet are marked below.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/hypotheses">
            Run configuration
          </Link>
          <Link className="btn" to="/graph">
            View graph
          </Link>
        </div>
      </header>

      <div className="grid-2">
        <Panel title="Run summary">
          <dl className="kv">
            <dt>Seed</dt>
            <dd className="mono">{analysis.seed}</dd>
            <dt>Actors</dt>
            <dd>{analysis.actor_count}</dd>
            <dt>Evidence</dt>
            <dd>{analysis.evidence_count}</dd>
            <dt>Relationships</dt>
            <dd>{analysis.relationship_count}</dd>
            <dt>Candidate links</dt>
            <dd>{analysis.candidate_count}</dd>
            <dt>Hypotheses persisted</dt>
            <dd>{analysis.persisted_hypothesis_count}</dd>
          </dl>
        </Panel>

        <Panel title="Not available via API yet" description="AttributionAssessment fields.">
          <EmptyState
            title="Calibrated confidence, model version and evidence IDs"
            message="The schema (AttributionAssessment in src/aegis/schemas/hypothesis.py) defines model_id, model_version, calibrated_confidence, calibration_version, per-modality signals and supporting/contradictory evidence IDs — but no route returns them."
            endpoint="GET /api/v1/assessments/{hypothesis_id}"
          />
        </Panel>
      </div>

      <Panel
        title="Score breakdown"
        description="Raw, support, contradiction and final score per hypothesis."
      >
        <div className="card-grid">
          {analysis.hypotheses.length === 0 && (
            <EmptyState
              title="No hypotheses returned"
              message="The candidate-link engine produced no hypotheses for this configuration — lower min_score (or raise actor_count) and re-run."
              endpoint="POST /api/v1/analysis/synthetic"
            />
          )}
          {analysis.hypotheses.map((hypothesis) => (
            <article className="score-card" key={hypothesis.hypothesis_id}>
              <header className="score-card__head">
                <span className="mono" title={hypothesis.hypothesis_id}>
                  {shortId(hypothesis.hypothesis_id, 8)}
                </span>
                <Badge tone={hypothesis.contradiction_score > hypothesis.support_score ? 'danger' : 'ok'}>
                  {hypothesis.status}
                </Badge>
              </header>
              <p className="score-card__route">
                <span className="mono">{shortId(hypothesis.source_actor_id, 8)}</span>
                <span aria-hidden="true"> → </span>
                <span className="mono">{shortId(hypothesis.target_actor_id, 8)}</span>
              </p>
              <ScoreBars
                label={`Scores for hypothesis ${hypothesis.hypothesis_id}`}
                rows={[
                  { label: 'raw', value: hypothesis.raw_score, tone: 'neutral' },
                  { label: 'support', value: hypothesis.support_score, tone: 'ok' },
                  { label: 'contradiction', value: hypothesis.contradiction_score, tone: 'danger' },
                  { label: 'final', value: hypothesis.final_score, tone: 'info' },
                ]}
              />
              <dl className="kv kv--tight">
                <dt>Evidence items</dt>
                <dd>{hypothesis.evidence_count}</dd>
                <dt>Final</dt>
                <dd>
                  <strong>{formatPercent(hypothesis.final_score)}</strong>
                </dd>
              </dl>
              {hypothesis.explanations.length > 0 && (
                <ul className="bullet-list">
                  {hypothesis.explanations.map((text, index) => (
                    <li key={`${hypothesis.hypothesis_id}-${index}`}>{text}</li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}
