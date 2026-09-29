import { useMemo } from 'react';
import { formatDateTime, formatPercent, scoreTone, shortId } from '../../lib/format';
import { Badge } from '../Badge';
import { EmptyState, ErrorState, LoadingState } from '../States';
import type { ApiResource } from '../../hooks/useApi';
import type { CaseHypothesis } from '../../api/types';

export interface HypothesisBoardProps {
  readonly hypotheses: ApiResource<CaseHypothesis[]>;
  /** Open a cited evidence record in the drawer. */
  readonly onSelectEvidence: (evidenceId: string) => void;
}

const HYPOTHESIS_ENDPOINT = 'GET /api/v1/cases/{id}/hypotheses';

function scoreOf(hypothesis: CaseHypothesis): number | null {
  if (hypothesis.calibrated_confidence !== null) return hypothesis.calibrated_confidence;
  return hypothesis.raw_score;
}

/**
 * Share of the cited evidence that points *against* a hypothesis.
 *
 * The API exposes the two id lists and no "contradiction score", so the ratio
 * is computed here from the same evidence the model saw — and is labelled as a
 * share of citations, never as a probability.
 */
function contradictionShare(hypothesis: CaseHypothesis): number | null {
  const support = hypothesis.supporting_evidence_ids.length;
  const contradict = hypothesis.contradictory_evidence_ids.length;
  if (support + contradict === 0) return null;
  return contradict / (support + contradict);
}

function SignalCell({ value }: { value: number | undefined }) {
  if (value === undefined || !Number.isFinite(value)) {
    return <span className="inv-cell is-none">—</span>;
  }
  if (value === 0) return <span className="inv-cell is-none">0.00</span>;
  return (
    <span className={`inv-cell ${value > 0 ? 'is-pos' : 'is-neg'}`}>
      {value > 0 ? '+' : '−'}
      {Math.abs(value).toFixed(2)}
    </span>
  );
}

function SupportSummary({ score, contradiction }: { score: number | null; contradiction: number | null }) {
  return (
    <span>
      {score === null ? 'unscored' : `${formatPercent(score)} support`}
      {' · '}
      {contradiction === null ? 'no citations' : `${formatPercent(contradiction)} contradicting`}
    </span>
  );
}

/** Stable empty list so `?? []` does not hand useMemo a fresh array each render. */
const NO_HYPOTHESES: readonly CaseHypothesis[] = [];

/**
 * Competing hypotheses: a board of the candidates and a modality matrix
 * comparing them side by side.
 *
 * The board never shows a bare percentage. Every number is placed next to the
 * evidence counts and independent source groups behind it, because "81%" with
 * one citation and "81%" with nine independent ones are not the same claim.
 */
export function HypothesisBoard({ hypotheses, onSelectEvidence }: HypothesisBoardProps) {
  const rows = hypotheses.data ?? NO_HYPOTHESES;

  const ordered = useMemo(
    () =>
      [...rows].sort((left, right) => {
        const a = scoreOf(left);
        const b = scoreOf(right);
        if (a === null && b === null) return left.hypothesis_id.localeCompare(right.hypothesis_id);
        if (a === null) return 1;
        if (b === null) return -1;
        return b - a;
      }),
    [rows],
  );

  const modalities = useMemo(() => {
    const keys = new Set<string>();
    for (const row of rows) for (const key of Object.keys(row.signals)) keys.add(key);
    return [...keys].sort();
  }, [rows]);

  const labels = useMemo(
    () => new Map(ordered.map((row, index) => [row.hypothesis_id, `H-${String(index + 1).padStart(2, '0')}`])),
    [ordered],
  );

  if (hypotheses.loading) return <LoadingState label="Loading hypotheses…" />;
  if (hypotheses.error !== null) return <ErrorState message={hypotheses.error} onRetry={hypotheses.reload} />;
  if (ordered.length === 0) {
    return (
      <EmptyState
        title="No competing hypotheses"
        message="No attribution hypotheses have been raised for this investigation, so there is nothing to compare. The absence of hypotheses is not evidence of absence."
        endpoint={HYPOTHESIS_ENDPOINT}
      />
    );
  }

  return (
    <>
      <div className="panel">
        <div className="panel__head">
          <div className="panel__headings">
            <h2 className="panel__title">Hypothesis board</h2>
            <p className="panel__desc">
              Every candidate attribution, strongest first, with the evidence and the independent
              source groups behind its score.
            </p>
          </div>
          <div className="panel__actions">
            <span className="surface-meta">{ordered.length} hypotheses</span>
          </div>
        </div>
        <div className="panel__body">
          <div className="inv-hyp-grid">
            {ordered.map((hypothesis) => {
              const score = scoreOf(hypothesis);
              const contradiction = contradictionShare(hypothesis);
              const support = hypothesis.supporting_evidence_ids.length;
              const contradict = hypothesis.contradictory_evidence_ids.length;
              return (
                <article className="inv-hyp" key={hypothesis.hypothesis_id}>
                  <div className="inv-hyp__head">
                    <span className="inv-hyp__id">
                      {labels.get(hypothesis.hypothesis_id)} ·{' '}
                      <span title={hypothesis.hypothesis_id}>
                        {shortId(hypothesis.hypothesis_id, 10)}
                      </span>
                    </span>
                    <Badge tone={hypothesis.status === 'accepted' ? 'ok' : 'neutral'}>{hypothesis.status}</Badge>
                  </div>
                  <p className="inv-hyp__route">
                    <span title={hypothesis.subject_entity_id}>
                      {shortId(hypothesis.subject_entity_id, 12)}
                    </span>
                    <span aria-hidden="true">→</span>
                    <span title={hypothesis.object_entity_id}>
                      {shortId(hypothesis.object_entity_id, 12)}
                    </span>
                    <span className="hint">{hypothesis.kind}</span>
                  </p>

                  <div className="inv-hyp__bars">
                    <div className="inv-hyp__bar-row">
                      <span>Support (calibrated confidence)</span>
                      <b>{score === null ? '—' : formatPercent(score)}</b>
                      <span className="inv-hyp__track">
                        <i
                          className={`is-${score === null ? 'warn' : scoreTone(score)}`}
                          style={{ width: `${Math.round((score ?? 0) * 100)}%` }}
                        />
                      </span>
                    </div>
                    <div className="inv-hyp__bar-row">
                      <span>Contradiction share of cited evidence</span>
                      <b>{contradiction === null ? '—' : formatPercent(contradiction)}</b>
                      <span className="inv-hyp__track">
                        <i
                          className={`is-${contradiction === null ? 'warn' : contradiction >= 0.5 ? 'danger' : 'ok'}`}
                          style={{ width: `${Math.round((contradiction ?? 0) * 100)}%` }}
                        />
                      </span>
                    </div>
                  </div>

                  <dl className="kv kv--tight">
                    <dt>Raw score</dt>
                    <dd>
                      {hypothesis.raw_score === null ? (
                        <span className="hint">not recorded</span>
                      ) : (
                        formatPercent(hypothesis.raw_score)
                      )}
                    </dd>
                    <dt>Supporting evidence</dt>
                    <dd>{support} record{support === 1 ? '' : 's'}</dd>
                    <dt>Contradicting evidence</dt>
                    <dd>{contradict} record{contradict === 1 ? '' : 's'}</dd>
                    <dt>Independent source groups</dt>
                    <dd>{hypothesis.independent_source_groups}</dd>
                  </dl>

                  {hypothesis.missing_evidence.length > 0 && (
                    <>
                      <p className="eyebrow" style={{ marginTop: 14 }}>
                        Missing evidence
                      </p>
                      <ul className="bullet-list">
                        {hypothesis.missing_evidence.map((note) => (
                          <li key={note}>{note}</li>
                        ))}
                      </ul>
                    </>
                  )}

                  {support + contradict > 0 && (
                    <>
                      <p className="eyebrow" style={{ marginTop: 14 }}>
                        Cited records
                      </p>
                      <ul className="inv-cites">
                        {hypothesis.supporting_evidence_ids.map((id) => (
                          <li key={`s-${hypothesis.hypothesis_id}-${id}`}>
                            <button
                              type="button"
                              className="inv-cite inv-cite--support"
                              onClick={() => onSelectEvidence(id)}
                            >
                              + {shortId(id, 8)}
                            </button>
                          </li>
                        ))}
                        {hypothesis.contradictory_evidence_ids.map((id) => (
                          <li key={`c-${hypothesis.hypothesis_id}-${id}`}>
                            <button
                              type="button"
                              className="inv-cite inv-cite--contradict"
                              onClick={() => onSelectEvidence(id)}
                            >
                              − {shortId(id, 8)}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  <p className="inv-hyp__foot">
                    {hypothesis.analyst_disposition === null ? (
                      <span className="hint">No analyst disposition recorded.</span>
                    ) : (
                      <>
                        <strong>Disposition:</strong> {hypothesis.analyst_disposition}
                      </>
                    )}
                    <br />
                    <span className="hint">
                      Raised {formatDateTime(hypothesis.created_at)} · updated{' '}
                      {formatDateTime(hypothesis.updated_at ?? hypothesis.created_at)}
                    </span>
                  </p>
                </article>
              );
            })}
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel__head">
          <div className="panel__headings">
            <h2 className="panel__title">Hypothesis matrix</h2>
            <p className="panel__desc">
              The same hypotheses across every modality the model scored. A cell is a signed signal
              weight — a hypothesis that is strong on one modality and negative on another is a
              different claim from one that is uniformly weak.
            </p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="inv-matrix">
            <caption className="sr-only">
              Competing hypotheses compared across modalities, with current support
            </caption>
            <thead>
              <tr>
                <th scope="col">
                  Modality
                  <small className="hint" style={{ display: 'block', fontWeight: 400 }}>
                    signal strength by modality
                  </small>
                </th>
                {ordered.map((hypothesis) => (
                  <th scope="col" key={hypothesis.hypothesis_id}>
                    {labels.get(hypothesis.hypothesis_id)}
                    <small className="hint" style={{ display: 'block', fontWeight: 400 }}>
                      {`${hypothesis.independent_source_groups} group(s)`}
                    </small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {modalities.map((modality) => (
                <tr key={modality}>
                  <th scope="row" className="inv-matrix__modality">
                    {modality.replaceAll('_', ' ')}
                  </th>
                  {ordered.map((hypothesis) => (
                    <td key={`${hypothesis.hypothesis_id}-${modality}`}>
                      <SignalCell value={hypothesis.signals[modality]} />
                    </td>
                  ))}
                </tr>
              ))}
              {modalities.length === 0 && (
                <tr>
                  <th scope="row" className="inv-matrix__modality">
                    No per-modality signals
                  </th>
                  {ordered.map((hypothesis) => (
                    <td key={hypothesis.hypothesis_id}>
                      <span className="inv-cell is-none">—</span>
                    </td>
                  ))}
                </tr>
              )}
              <tr className="inv-matrix__row-total">
                <th scope="row">Current support</th>
                {ordered.map((hypothesis) => {
                  const score = scoreOf(hypothesis);
                  return (
                    <td key={`support-${hypothesis.hypothesis_id}`}>
                      {score === null ? (
                        <span className="inv-cell is-none">unscored</span>
                      ) : (
                        <Badge tone={scoreTone(score)}>{formatPercent(score)}</Badge>
                      )}
                    </td>
                  );
                })}
              </tr>
              <tr className="inv-matrix__row-total">
                <th scope="row">Cited evidence (support / contradict)</th>
                {ordered.map((hypothesis) => (
                  <td key={`cites-${hypothesis.hypothesis_id}`}>
                    <span className="inv-cell">
                      {hypothesis.supporting_evidence_ids.length} /{' '}
                      {hypothesis.contradictory_evidence_ids.length}
                    </span>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        <div className="panel__body">
          <p className="caution" style={{ marginTop: 14 }}>
            A calibrated confidence is a model output conditioned on the evidence collected when the
            assessment ran. It is not a probability that the attribution is true, and support that
            draws on a single independence group is one signal, not several.
          </p>
          <dl className="kv kv--tight" style={{ marginTop: 14 }}>
            {ordered.map((hypothesis) => (
              <div key={`total-${hypothesis.hypothesis_id}`} style={{ display: 'contents' }}>
                <dt>{labels.get(hypothesis.hypothesis_id)}</dt>
                <dd>
                  <SupportSummary
                    score={scoreOf(hypothesis)}
                    contradiction={contradictionShare(hypothesis)}
                  />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </>
  );
}
