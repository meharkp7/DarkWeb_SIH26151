import { useState } from 'react';
import type { InfraCorrelateResponse, InfraThresholdInput } from '../../api/types';
import { formatApiError, api } from '../../api/client';
import { formatCount } from '../../lib/explain';
import { formatPercent } from '../../lib/format';

/**
 * Run the library's correlation over the stored observations.
 *
 * The threshold set is six explicit inputs rather than a single "run it"
 * button, and that is the point. The API refuses a request without them, and
 * rightly: a correlation that silently used a library default would read to
 * whoever read the result as a deliberate choice about what counts as shared
 * infrastructure, and it was not one.
 */
export function CorrelateRunner({
  caseId,
  onComplete,
}: {
  /** A correlation writes match rows, so a case is required. */
  readonly caseId: string;
  readonly onComplete: () => void;
}): JSX.Element {
  const [thresholds, setThresholds] = useState<InfraThresholdInput>({
    min_similarity: 0.42,
    min_certificate: 0.9,
    min_content: 0.8,
    min_http: 0.9,
    min_temporal_overlap: 0,
    require_temporal_overlap: true,
  });
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InfraCorrelateResponse | null>(null);

  if (caseId === '') {
    return (
      <p className="inf-note">
        <span className="inf-note__title">Case required</span>
        A correlation writes match rows, and a finding nobody can attribute to an investigation
        cannot be revisited, contradicted or closed. Choose a case before running one.
      </p>
    );
  }

  const setNumber = (key: keyof InfraThresholdInput) => (event: { target: { value: string } }) => {
    const parsed = Number(event.target.value);
    setThresholds((current) => ({ ...current, [key]: Number.isFinite(parsed) ? parsed : 0 }));
  };

  const run = async (): Promise<void> => {
    setRunning(true);
    setError(null);
    try {
      const response = await api.infraCorrelate({ case_id: caseId, thresholds });
      setResult(response);
      onComplete();
    } catch (caught) {
      setError(formatApiError(caught));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="inf-note inf-note--info">
      <p className="inf-note__title">Run a correlation</p>
      <div className="inf-filters" style={{ marginBottom: 10 }}>
        {(
          [
            ['min_similarity', 'Min overall', 0.01, 1, 0.01],
            ['min_certificate', 'Min certificate', 0.01, 1, 0.01],
            ['min_content', 'Min content', 0.01, 1, 0.01],
            ['min_http', 'Min HTTP', 0.01, 1, 0.01],
            ['min_temporal_overlap', 'Min temporal overlap', 0, 1, 0.01],
          ] as const
        ).map(([key, label, min, max, step]) => (
          <div className="inf-field" key={key}>
            <label className="inf-field__label" htmlFor={`inf-threshold-${key}`}>
              {label}
            </label>
            <input
              id={`inf-threshold-${key}`}
              type="number"
              min={min}
              max={max}
              step={step}
              value={thresholds[key]}
              onChange={setNumber(key)}
              style={{ width: 88 }}
            />
          </div>
        ))}
        <div className="inf-field">
          <span className="inf-field__label">Temporal gate</span>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, minHeight: 30 }}>
            <input
              type="checkbox"
              checked={thresholds.require_temporal_overlap}
              onChange={(event) =>
                setThresholds((current) => ({
                  ...current,
                  require_temporal_overlap: event.target.checked,
                }))
              }
            />
            <span className="inf-caption">require overlapping windows</span>
          </label>
        </div>
        <button
          type="button"
          className="inf-btn inf-btn--primary"
          onClick={() => void run()}
          disabled={running}
        >
          {running ? 'Scoring pairs…' : `Run over case ${caseId.slice(0, 8)}…`}
        </button>
      </div>

      {error !== null && (
        <p className="inf-note" role="alert">
          <span className="inf-note__title">Could not run the correlation</span>
          {error}
        </p>
      )}

      {result !== null && (
        <div style={{ marginTop: 10 }}>
          <p style={{ margin: '0 0 6px' }}>
            Read {formatCount(result.observations_considered, 'observation')} —{' '}
            {result.pairs_evaluated} pairs scored —{' '}
            <strong>
              {formatCount(result.candidates, 'candidate', 'candidates')} above the thresholds.
            </strong>{' '}
            {formatCount(result.created.length, 'new match', 'new matches')} written,{' '}
            {formatCount(result.existing.length, 'match', 'matches')} already on file and left
            untouched.
          </p>
          {result.same_network_candidates > 0 && (
            <p className="inf-caption" style={{ margin: '0 0 6px' }}>
              {formatCount(result.same_network_candidates, 'candidate', 'candidates')} were dropped
              as same-network pairs: this table pairs a hidden service with a clearnet host, and a
              pair that never crosses networks is not that.
            </p>
          )}
          {result.skipped_observations.length > 0 && (
            <p className="inf-caption" style={{ margin: '0 0 6px' }}>
              {formatCount(result.skipped_observations.length, 'observation')} could not be read
              and were not scored. They are listed below rather than dropped, because a run that
              quietly ignored a sixth of its inputs presents its result as if it had seen them all.
            </p>
          )}
          {/* The correlation's own caveats, in its own words. */}
          <p className="inf-limits__head" style={{ marginTop: 10 }}>
            What this run does not establish
          </p>
          <ul className="inf-limits__list">
            {result.limitations.map((note) => (
              <li className="inf-limits__note" key={note}>
                {note}
              </li>
            ))}
          </ul>
          {result.created.length > 0 && (
            <p className="inf-footnote" style={{ marginTop: 8 }}>
              Highest new correlation{' '}
              {formatPercent(
                Math.max(...result.created.map((match) => match.overall)),
              )}
              {result.created.filter((match) => match.single_channel).length > 0 && (
                <>
                  {' '}
                  — of which{' '}
                  {formatCount(
                    result.created.filter((match) => match.single_channel).length,
                    'rests',
                    'rest',
                  )}{' '}
                  on a single channel.
                </>
              )}
            </p>
          )}
          {result.skipped_observations.length > 0 && (
            <ul className="inf-limits__list" style={{ marginTop: 8 }}>
              {result.skipped_observations.map((skipped) => (
                <li className="inf-limits__note" key={skipped.observation_id}>
                  <span className="inf-mono">{skipped.subject.slice(0, 22)}…</span> —{' '}
                  {skipped.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
