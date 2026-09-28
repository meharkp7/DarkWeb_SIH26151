import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api, formatApiError } from '../api/client';
import type { SyntheticAnalysisRequest } from '../api/types';
import { Badge } from '../components/Badge';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { Sparkline } from '../components/Sparkline';
import { formatPercent, shortId } from '../lib/format';
import { useSession } from '../store/session';

type Status =
  | { readonly kind: 'idle' }
  | { readonly kind: 'busy' }
  | { readonly kind: 'ok'; readonly message: string }
  | { readonly kind: 'error'; readonly message: string };

/**
 * Screen 8 — hypothesis comparison.
 *
 * Runs `POST /api/v1/analysis/synthetic` (live endpoint) and lays the
 * returned hypotheses out side by side with support vs contradiction scores.
 */
export function HypothesesPage() {
  const { analysis, setAnalysis } = useSession();
  const [seed, setSeed] = useState('26151');
  const [actorCount, setActorCount] = useState('4');
  const [minScore, setMinScore] = useState('0');
  const [status, setStatus] = useState<Status>({ kind: 'idle' });

  const handleRun = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const seedValue = Number(seed);
    const actorCountValue = Number(actorCount);
    const minScoreValue = Number(minScore);

    if (!Number.isInteger(seedValue)) {
      setStatus({ kind: 'error', message: 'Seed must be an integer.' });
      return;
    }
    if (!Number.isInteger(actorCountValue) || actorCountValue < 2 || actorCountValue > 50) {
      setStatus({ kind: 'error', message: 'Actor count must be an integer between 2 and 50.' });
      return;
    }
    if (!Number.isFinite(minScoreValue) || minScoreValue < 0 || minScoreValue > 1) {
      setStatus({ kind: 'error', message: 'min_score must be between 0 and 1.' });
      return;
    }

    const payload: SyntheticAnalysisRequest = {
      seed: seedValue,
      actor_count: actorCountValue,
      min_score: minScoreValue,
    };
    setStatus({ kind: 'busy' });
    api
      .runSyntheticAnalysis(payload)
      .then((response) => {
        setAnalysis(response);
        setStatus({
          kind: 'ok',
          message: `Run complete: ${response.actor_count} actors, ${response.evidence_count} evidence, ${response.persisted_hypothesis_count} hypotheses persisted.`,
        });
      })
      .catch((error: unknown) => {
        setStatus({ kind: 'error', message: formatApiError(error) });
      });
  };

  const finalScores =
    analysis === null ? [] : analysis.hypotheses.map((hypothesis) => hypothesis.final_score);

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Hypothesis comparison</h1>
          <p className="page-sub">
            Competing explanations with their support and contradiction evidence. Results come from
            a live <code>POST /api/v1/analysis/synthetic</code> run and stay in this session — the
            API has no endpoint to read persisted hypotheses back yet.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/attribution">Attribution view</Link>
          <Link className="btn" to="/graph">Graph view</Link>
        </div>
      </header>

      <Panel
        title="Run synthetic analysis"
        description="Generates actors + evidence, persists hypotheses, returns scores."
      >
        <form className="form" onSubmit={handleRun}>
          <div className="form-grid form-grid--narrow">
            <div className="field">
              <label htmlFor="run-seed">Seed</label>
              <input
                id="run-seed"
                type="number"
                step={1}
                value={seed}
                onChange={(event) => setSeed(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="run-actors">Actor count (2–50)</label>
              <input
                id="run-actors"
                type="number"
                min={2}
                max={50}
                step={1}
                value={actorCount}
                onChange={(event) => setActorCount(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="run-min-score">min_score (0–1)</label>
              <input
                id="run-min-score"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={minScore}
                onChange={(event) => setMinScore(event.target.value)}
              />
            </div>
          </div>
          <div className="form-actions">
            <button type="submit" className="btn btn--primary" disabled={status.kind === 'busy'}>
              {status.kind === 'busy' ? 'Running…' : 'Run analysis'}
            </button>
            <span className="hint">Requires the API and its database.</span>
          </div>
          {status.kind === 'ok' && (
            <p className="status status--ok" role="status">
              {status.message}
            </p>
          )}
          {status.kind === 'error' && (
            <p className="status status--error" role="alert">
              {status.message}
            </p>
          )}
        </form>
      </Panel>

      {analysis === null ? (
        <Panel title="Comparison">
          <EmptyState
            title="No run yet"
            message="Run the synthetic analysis above to populate hypothesis comparisons. Nothing is pre-filled because no data has been produced."
            endpoint="POST /api/v1/analysis/synthetic"
          />
        </Panel>
      ) : (
        <>
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
              <dt>Returned hypotheses</dt>
              <dd>{analysis.hypotheses.length}</dd>
              <dt>Final scores</dt>
              <dd>
                {finalScores.length > 0 ? (
                  <Sparkline
                    values={finalScores}
                    label="Final score per hypothesis, in run order"
                  />
                ) : (
                  <span className="hint">No scores returned</span>
                )}
              </dd>
            </dl>
          </Panel>

          <Panel
            title="Side-by-side comparison"
            description="Support vs contradiction for every returned hypothesis."
          >
            {analysis.hypotheses.length === 0 ? (
              <EmptyState
                title="No hypotheses returned"
                message="The run completed but the candidate engine produced no hypotheses — lower min_score and run again."
                endpoint="POST /api/v1/analysis/synthetic"
              />
            ) : (
              <div className="card-grid">
                {analysis.hypotheses.map((hypothesis) => (
                  <article className="score-card" key={hypothesis.hypothesis_id}>
                    <header className="score-card__head">
                      <span className="mono" title={hypothesis.hypothesis_id}>
                        {shortId(hypothesis.hypothesis_id, 8)}
                      </span>
                      <Badge tone="neutral">{hypothesis.status}</Badge>
                    </header>
                    <p className="score-card__route">
                      <Link className="mono" to={`/actors/${encodeURIComponent(hypothesis.source_actor_id)}`}>
                        {shortId(hypothesis.source_actor_id, 8)}
                      </Link>
                      <span aria-hidden="true"> → </span>
                      <Link className="mono" to={`/actors/${encodeURIComponent(hypothesis.target_actor_id)}`}>
                        {shortId(hypothesis.target_actor_id, 8)}
                      </Link>
                    </p>

                    <div className="score-pair">
                      <div className="score-pair__col">
                        <span className="score-pair__label">Support</span>
                        <span className="bar">
                          <span
                            className="bar__fill bar__fill--ok"
                            style={{ width: `${Math.round(hypothesis.support_score * 100)}%` }}
                          />
                        </span>
                        <span className="score-pair__value">{formatPercent(hypothesis.support_score)}</span>
                      </div>
                      <div className="score-pair__col">
                        <span className="score-pair__label">Contradiction</span>
                        <span className="bar">
                          <span
                            className="bar__fill bar__fill--danger"
                            style={{ width: `${Math.round(hypothesis.contradiction_score * 100)}%` }}
                          />
                        </span>
                        <span className="score-pair__value">
                          {formatPercent(hypothesis.contradiction_score)}
                        </span>
                      </div>
                    </div>

                    <dl className="kv kv--tight">
                      <dt>Raw</dt>
                      <dd>{formatPercent(hypothesis.raw_score)}</dd>
                      <dt>Final</dt>
                      <dd>
                        <strong>{formatPercent(hypothesis.final_score)}</strong>
                      </dd>
                      <dt>Evidence</dt>
                      <dd>{hypothesis.evidence_count} items</dd>
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
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
