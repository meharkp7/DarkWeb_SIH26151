import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { formatDateTime, formatPercent, scoreTone, shortId } from '../../lib/format';
import type { ApiResource } from '../../hooks/useApi';
import { Badge } from '../Badge';
import type { Tone } from '../Badge';
import { DataTable } from '../DataTable';
import type { Column } from '../DataTable';
import { Panel } from '../Panel';
import { ScoreBars } from '../ScoreBars';
import { Sparkline } from '../Sparkline';
import { EmptyState, ErrorState, LoadingState } from '../States';
import type { CaseHypothesis, CaseWorkspace, WorkspaceAssessment } from '../../api/types';
import { entityLabel, indexEntities, metaTitle } from './workspaceFormat';
import { ScoreRing } from './ScoreRing';

export interface AssessmentPanelProps {
  /** Already-resolved workspace payload — the page gates its own loading/error. */
  readonly workspace: CaseWorkspace;
  /**
   * Case-scoped hypotheses, already fetched by the page. Passed in rather than
   * re-requested so opening this tab costs no extra round trip.
   */
  readonly hypotheses: ApiResource<CaseHypothesis[]>;
  /** Jump to the Evidence tab with the ledger record open. */
  readonly onSelectEvidence: (evidenceId: string) => void;
}

type Stance = 'supporting' | 'contradicting';

interface CitedEvidence {
  readonly evidenceId: string;
  readonly stance: Stance;
  readonly title: string | null;
  readonly sourceType: string | null;
  readonly reliability: number | null;
  readonly collectedAt: string | null;
}

const STANCE_TONE: Record<Stance, Tone> = {
  supporting: 'ok',
  contradicting: 'danger',
};

const ASSESSMENT_ENDPOINT = 'GET /api/v1/assessments/{hypothesis_id}';
const HYPOTHESIS_ENDPOINT = 'GET /api/v1/cases/{id}/hypotheses';

/** The Overview ring uses `assessments[0]`; the Assessment tab must agree with it. */
function leadAssessment(workspace: CaseWorkspace): WorkspaceAssessment | undefined {
  return workspace.assessments[0];
}

function finiteSignals(assessment: WorkspaceAssessment): Array<{ name: string; value: number }> {
  return Object.entries(assessment.signals)
    .filter((entry): entry is [string, number] => Number.isFinite(entry[1]))
    .map(([name, value]) => ({ name, value }));
}

/** Distinct evidence ids cited by any assessment, with the strongest stance. */
function collectCitations(workspace: CaseWorkspace): Map<string, Stance> {
  const stances = new Map<string, Stance>();
  for (const assessment of workspace.assessments) {
    for (const id of assessment.supporting_evidence_ids) stances.set(id, 'supporting');
  }
  // Contradiction wins a tie: it is the more decision-relevant signal.
  for (const assessment of workspace.assessments) {
    for (const id of assessment.contradictory_evidence_ids) stances.set(id, 'contradicting');
  }
  return stances;
}

function citedRows(
  workspace: CaseWorkspace,
  stances: ReadonlyMap<string, Stance>,
): CitedEvidence[] {
  const ledger = new Map(workspace.evidence.map((item) => [item.evidence_id, item]));
  return Array.from(stances.entries())
    .map(([evidenceId, stance]) => {
      const item = ledger.get(evidenceId);
      return {
        evidenceId,
        stance,
        title: item === undefined ? null : metaTitle(item.metadata),
        sourceType: item === undefined ? null : item.source_type,
        reliability: item === undefined ? null : item.reliability,
        collectedAt: item === undefined ? null : item.collected_at,
      };
    })
    .sort((left, right) => {
      if (left.stance !== right.stance) return left.stance === 'contradicting' ? -1 : 1;
      return (right.reliability ?? -1) - (left.reliability ?? -1);
    });
}

function uniqueStrings(values: ReadonlyArray<readonly string[]>): string[] {
  const seen = new Set<string>();
  for (const list of values) {
    for (const value of list) {
      if (value.trim() !== '') seen.add(value);
    }
  }
  return Array.from(seen);
}

function hypothesisScore(hypothesis: CaseHypothesis): number | null {
  if (hypothesis.calibrated_confidence !== null) return hypothesis.calibrated_confidence;
  return hypothesis.raw_score;
}

/**
 * Workspace Assessment tab — "what does the evidence support, and how certain
 * is it?".
 *
 * Attribution hypotheses and the analytic assessment are the same artefact, so
 * they live together here: confidence, the model's own signal decomposition,
 * every competing hypothesis with its supporting and contradicting evidence,
 * and an explicit statement of what the score does not establish.
 */
export function AssessmentPanel({
  workspace,
  hypotheses,
  onSelectEvidence,
}: AssessmentPanelProps) {
  const byId = useMemo(() => indexEntities(workspace.entities), [workspace.entities]);
  const rows = hypotheses.data ?? [];
  const lead = leadAssessment(workspace);
  const signals = lead === undefined ? [] : finiteSignals(lead);
  const stances = useMemo(() => collectCitations(workspace), [workspace]);
  const citations = useMemo(() => citedRows(workspace, stances), [workspace, stances]);

  const assessmentByHypothesis = useMemo(() => {
    const map = new Map<string, WorkspaceAssessment>();
    for (const assessment of workspace.assessments) {
      if (!map.has(assessment.hypothesis_id)) map.set(assessment.hypothesis_id, assessment);
    }
    return map;
  }, [workspace.assessments]);

  const confidence = lead?.calibrated_confidence ?? lead?.raw_score ?? null;
  const missingEvidence = uniqueStrings(rows.map((row) => row.missing_evidence));
  const limitationNotes = lead?.limitations ?? [];
  const citedCount = stances.size;
  const coverage =
    workspace.evidence.length === 0
      ? null
      : Math.round((citedCount / workspace.evidence.length) * 100);
  const scoredRows = rows
    .map((row) => hypothesisScore(row))
    .filter((value): value is number => value !== null && Number.isFinite(value));

  const citationColumns: ReadonlyArray<Column<CitedEvidence>> = [
    {
      key: 'evidence',
      header: 'Evidence',
      render: (row) => (
        <>
          <b>{row.title ?? shortId(row.evidenceId, 12)}</b>
          <small className="table-sub">
            <span className="mono">{shortId(row.evidenceId, 12)}</span>
          </small>
        </>
      ),
    },
    {
      key: 'stance',
      header: 'Stance',
      render: (row) => <Badge tone={STANCE_TONE[row.stance]}>{row.stance}</Badge>,
    },
    {
      key: 'source',
      header: 'Source',
      render: (row) =>
        row.sourceType === null ? <span className="hint">not in this ledger</span> : row.sourceType,
    },
    {
      key: 'reliability',
      header: 'Reliability',
      align: 'end',
      render: (row) =>
        row.reliability === null ? <span className="hint">—</span> : formatPercent(row.reliability),
    },
    {
      key: 'collected',
      header: 'Collected',
      render: (row) => formatDateTime(row.collectedAt),
    },
    {
      key: 'open',
      header: '',
      align: 'end',
      render: (row) => (
        <button
          type="button"
          className="link-button"
          onClick={() => onSelectEvidence(row.evidenceId)}
        >
          Open
        </button>
      ),
    },
  ];

  return (
    <>
      <Panel
        title="Analytic confidence"
        description="The assessment this workspace leads with, and the model that produced it."
        actions={
          <span className="surface-meta">
            {workspace.assessments.length} assessment
            {workspace.assessments.length === 1 ? '' : 's'}
          </span>
        }
      >
        {lead === undefined ? (
          <EmptyState
            title="No assessment"
            message="No model assessment has been produced for this investigation, so there is no confidence figure to report. Nothing is inferred in its place."
            endpoint={ASSESSMENT_ENDPOINT}
          />
        ) : (
          <div className="assessment-grid">
            <div>
              <div className="assessment-score">
                <ScoreRing
                  value={confidence ?? 0}
                  label={lead.calibrated_confidence === null ? 'raw score' : 'calibrated'}
                />
                <div>
                  <b>
                    {confidence === null ? '—' : formatPercent(confidence)}{' '}
                    <Badge tone={scoreTone(confidence ?? 0)}>
                      {lead.calibrated_confidence === null ? 'uncalibrated' : 'calibrated'}
                    </Badge>
                  </b>
                  <span>
                    {lead.calibrated_confidence === null
                      ? 'Calibration has not been applied — the raw model score is shown unadjusted.'
                      : `Raw ${formatPercent(lead.raw_score)} calibrated to ${formatPercent(
                          lead.calibrated_confidence,
                        )}.`}
                  </span>
                </div>
              </div>
              <dl className="kv kv--tight">
                <dt>Model</dt>
                <dd className="mono">{lead.model_id}</dd>
                <dt>Version</dt>
                <dd className="mono">{lead.model_version}</dd>
                <dt>Hypothesis</dt>
                <dd className="mono">{shortId(lead.hypothesis_id, 12)}</dd>
                <dt>Signals</dt>
                <dd>{signals.length}</dd>
              </dl>
            </div>
            <div>
              <p className="assessment-note">
                Confidence is a function of the evidence set that existed when the assessment ran.
                New evidence does not move this number until a new assessment is produced — treat
                the timestamp below, not the score, as the freshness of the picture.
              </p>
              <p className="hint">
                Scored {formatDateTime(workspace.case.updated_at)} · case last updated.
              </p>
            </div>
          </div>
        )}
      </Panel>

      <Panel
        title="Signal decomposition"
        description="How the score is made up: raw and calibrated totals, then the model's own per-signal weights."
      >
        {lead === undefined ? (
          <EmptyState
            title="No signal breakdown"
            message="Signal weights live on the assessment record, which this investigation does not have."
            endpoint={ASSESSMENT_ENDPOINT}
          />
        ) : signals.length === 0 ? (
          <EmptyState
            title="Model returned no signal weights"
            message={`${lead.model_id} ${lead.model_version} recorded a score of ${formatPercent(
              lead.raw_score,
            )} without a per-signal breakdown, so the score cannot be decomposed further from the API.`}
          />
        ) : (
          <>
            <ScoreBars
              label="Raw score, calibrated confidence and per-signal weights"
              rows={[
                { label: 'raw', value: lead.raw_score, tone: 'neutral' },
                ...(lead.calibrated_confidence === null
                  ? []
                  : [{ label: 'calibrated', value: lead.calibrated_confidence, tone: 'info' as const }]),
                ...signals.map((signal) => ({
                  label: signal.name,
                  value: signal.value,
                  tone: scoreTone(signal.value),
                })),
              ]}
            />
            {lead.explanations.length > 0 && (
              <>
                <p className="eyebrow">Model reasoning</p>
                <ul className="bullet-list">
                  {lead.explanations.map((text, index) => (
                    <li key={`${lead.assessment_id}-explanation-${String(index)}`}>{text}</li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </Panel>

      <Panel
        title="Limitations — what this does not prove"
        description="Read before acting on the score."
      >
        <ul className="bullet-list">
          <li>
            A calibrated confidence is a model output conditioned on the evidence collected so far.
            It is not a probability that the attribution is true, and it does not clear a
            hypothesis for action on its own.
          </li>
          <li>
            Confidence measures the strength of the observed link, not control of it. A high score
            does not establish who operated an account, paid for it, or directed it.
          </li>
          <li>
            Evidence that is not independent can inflate support. Several records from the same
            source or reposted from one another are one signal, not several.
          </li>
          {workspace.assessments.length > 1 && (
            <li>
              {workspace.assessments.length} assessments exist for this case; the figure above is
              the most recent one. Earlier runs may disagree — read the full list before concluding.
            </li>
          )}
          {coverage !== null && (
            <li>
              {citedCount} of {workspace.evidence.length} evidence records in this case (
              {coverage}%) are cited by an assessment. Anything outside that set neither supports
              nor undermines the score.
            </li>
          )}
          {rows.length > 0 && scoredRows.length < rows.length && (
            <li>
              {rows.length - scoredRows.length} of {rows.length} hypotheses carry no score at all,
              so a scored hypothesis is not necessarily the best explanation — only the measured
              one.
            </li>
          )}
        </ul>

        {limitationNotes.length > 0 ? (
          <>
            <p className="eyebrow">Recorded with this assessment</p>
            <ul className="bullet-list">
              {limitationNotes.map((note, index) => (
                <li key={`${lead?.assessment_id ?? 'assessment'}-limitation-${String(index)}`}>
                  {note}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="hint">
            The assessment record carries no machine-written limitations of its own — only the
            standing caveats above apply.
          </p>
        )}

        {missingEvidence.length > 0 && (
          <>
            <p className="eyebrow">Gaps analysts flagged on these hypotheses</p>
            <ul className="bullet-list">
              {missingEvidence.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </>
        )}

        <p className="caution">
          Nothing on this tab establishes intent, identity or legal attribution. It ranks
          explanations against the evidence held in this case at assessment time; the Evidence tab
          is where each cited record can be inspected.
        </p>
      </Panel>

      <Panel
        title="Competing hypotheses"
        description="Every attribution hypothesis raised for this case, scored and annotated. These are the assessment, not a separate opinion."
        actions={<span className="surface-meta">{rows.length} hypotheses</span>}
      >
        {hypotheses.loading && <LoadingState label="Loading hypotheses…" />}
        {hypotheses.error !== null && (
          <ErrorState message={hypotheses.error} onRetry={hypotheses.reload} />
        )}
        {!hypotheses.loading && hypotheses.error === null && rows.length === 0 && (
          <EmptyState
            title="No hypotheses"
            message="No attribution hypotheses have been raised for this investigation, so there is nothing to compare. The absence of hypotheses is not evidence of absence."
            endpoint={HYPOTHESIS_ENDPOINT}
          />
        )}
        {!hypotheses.loading && hypotheses.error === null && rows.length > 0 && (
          <>
            {scoredRows.length > 0 && (
              <div className="assessment-score">
                <Sparkline
                  values={scoredRows}
                  label="Score per hypothesis, strongest first is not implied — API order"
                />
                <div>
                  <b>{rows.length} hypotheses</b>
                  <span>
                    {scoredRows.length} scored · {rows.length - scoredRows.length} unscored
                  </span>
                </div>
              </div>
            )}

            <div className="card-grid">
              {rows.map((hypothesis) => {
                const assessment = assessmentByHypothesis.get(hypothesis.hypothesis_id);
                const score = hypothesisScore(hypothesis);
                const supporting = assessment?.supporting_evidence_ids ?? [];
                const contradicting = assessment?.contradictory_evidence_ids ?? [];
                const subject = entityLabel(byId, hypothesis.subject_entity_id);
                const object = entityLabel(byId, hypothesis.object_entity_id);
                return (
                  <article className="score-card" key={hypothesis.hypothesis_id}>
                    <header className="score-card__head">
                      <span className="mono" title={hypothesis.hypothesis_id}>
                        {shortId(hypothesis.hypothesis_id, 8)}
                      </span>
                      <Badge tone={hypothesis.status === 'accepted' ? 'ok' : 'neutral'}>
                        {hypothesis.status}
                      </Badge>
                    </header>
                    <p className="score-card__route">
                      <Link
                        className="mono"
                        to={`/actors/${encodeURIComponent(hypothesis.subject_entity_id)}`}
                        title={subject}
                      >
                        {shortId(subject, 14)}
                      </Link>
                      <span aria-hidden="true"> → </span>
                      <Link
                        className="mono"
                        to={`/actors/${encodeURIComponent(hypothesis.object_entity_id)}`}
                        title={object}
                      >
                        {shortId(object, 14)}
                      </Link>
                    </p>
                    <p className="hint">
                      {hypothesis.kind} · {subject} → {object}
                    </p>

                    {score === null ? (
                      <p className="hint">
                        No assessment recorded for this hypothesis — it is unscored, not weak.
                      </p>
                    ) : (
                      <ScoreBars
                        label={`Scores for hypothesis ${hypothesis.hypothesis_id}`}
                        rows={[
                          ...(hypothesis.raw_score === null
                            ? []
                            : [{ label: 'raw', value: hypothesis.raw_score, tone: 'neutral' as const }]),
                          { label: 'confidence', value: score, tone: scoreTone(score) },
                        ]}
                      />
                    )}

                    <div className="score-pair">
                      <div className="score-pair__col">
                        <span className="score-pair__label">Supporting</span>
                        <span className="bar">
                          <span
                            className="bar__fill bar__fill--ok"
                            style={{ width: `${supporting.length === 0 ? 0 : 100}%` }}
                          />
                        </span>
                        <span className="score-pair__value">{supporting.length} items</span>
                      </div>
                      <div className="score-pair__col">
                        <span className="score-pair__label">Contradicting</span>
                        <span className="bar">
                          <span
                            className="bar__fill bar__fill--danger"
                            style={{ width: `${contradicting.length === 0 ? 0 : 100}%` }}
                          />
                        </span>
                        <span className="score-pair__value">{contradicting.length} items</span>
                      </div>
                    </div>

                    {supporting.length > 0 && (
                      <ul className="bullet-list">
                        {supporting.slice(0, 6).map((id) => (
                          <li key={`${hypothesis.hypothesis_id}-supports-${id}`}>
                            <Badge tone="ok">supports</Badge>{' '}
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => onSelectEvidence(id)}
                            >
                              {shortId(id, 12)}
                            </button>
                          </li>
                        ))}
                        {supporting.length > 6 && (
                          <li className="hint">+{supporting.length - 6} more cited records</li>
                        )}
                      </ul>
                    )}

                    {contradicting.length > 0 && (
                      <ul className="bullet-list">
                        {contradicting.slice(0, 6).map((id) => (
                          <li key={`${hypothesis.hypothesis_id}-contradicts-${id}`}>
                            <Badge tone="danger">contradicts</Badge>{' '}
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => onSelectEvidence(id)}
                            >
                              {shortId(id, 12)}
                            </button>
                          </li>
                        ))}
                        {contradicting.length > 6 && (
                          <li className="hint">+{contradicting.length - 6} more cited records</li>
                        )}
                      </ul>
                    )}

                    {hypothesis.missing_evidence.length > 0 && (
                      <>
                        <p className="eyebrow">Missing evidence</p>
                        <ul className="bullet-list">
                          {hypothesis.missing_evidence.map((note) => (
                            <li key={`${hypothesis.hypothesis_id}-missing-${note}`}>{note}</li>
                          ))}
                        </ul>
                      </>
                    )}

                    {hypothesis.analyst_disposition !== null && (
                      <p className="hint">
                        <strong>Analyst disposition:</strong> {hypothesis.analyst_disposition}
                      </p>
                    )}
                    <p className="hint">
                      Raised {formatDateTime(hypothesis.created_at)} · updated{' '}
                      {formatDateTime(hypothesis.updated_at ?? hypothesis.created_at)}
                    </p>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </Panel>

      <Panel
        title="Evidence basis"
        description="Every ledger record an assessment leaned on, and in which direction."
        actions={<span className="surface-meta">{citations.length} cited</span>}
      >
        {citations.length === 0 ? (
          <EmptyState
            title="No cited evidence"
            message="No assessment for this case names the evidence it used, so the score cannot be traced back to the ledger."
            endpoint={ASSESSMENT_ENDPOINT}
          />
        ) : (
          <DataTable<CitedEvidence>
            caption="Evidence cited by the assessments in this case"
            columns={citationColumns}
            rows={citations}
            rowKey={(row) => row.evidenceId}
            rowClassName={(row) => (row.stance === 'contradicting' ? 'text-warn' : undefined)}
          />
        )}
      </Panel>
    </>
  );
}
