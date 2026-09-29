import type { PressureIndicator } from '../../api/types';
import { epistemicLabel, formatOptional } from '../../lib/explain';
import { cx } from '../../lib/format';
import type { Tone } from '../Badge';

export interface PressurePanelProps {
  /** The scored indicators exactly as the API returned them. */
  readonly indicators: readonly PressureIndicator[];
  /**
   * `command_posture.pressure_index` — the platform-wide mean of the same
   * indicators. Passed in rather than recomputed here so the headline can never
   * disagree with the figure the API considers authoritative.
   */
  readonly pressureIndex?: number | null;
}

/**
 * Pressure is a *scaled* number, so the raw fraction it was scaled from travels
 * with it. A "62" with no denominator is a score an analyst has to trust; a "62
 * (315 / 900)" is one they can check against the evidence count themselves.
 */
function pressureTone(score: number): Tone {
  if (score >= 70) return 'danger';
  if (score >= 40) return 'warn';
  return 'ok';
}

function clampScore(value: number): number {
  return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
}

export function PressurePanel({ indicators, pressureIndex = null }: PressurePanelProps) {
  const index = pressureIndex === null ? null : clampScore(pressureIndex);
  const observed = indicators.reduce((total, indicator) => total + (Number.isFinite(indicator.observed) ? indicator.observed : 0), 0);
  const ceiling = indicators.reduce((total, indicator) => total + (Number.isFinite(indicator.ceiling) ? indicator.ceiling : 0), 0);
  // The index is the mean of scores the API scaled from recorded counts, so it
  // is arithmetic over the ledger rather than a model output.
  const epistemic = epistemicLabel('derived');

  return (
    <div className="cc2-pressure">
      <div className="cc2-pressure__summary">
        <div>
          <p className="db-figure">
            <span className="cc2-pressure__summary-label">Platform pressure index</span>
            <span className={cx('db-kind', `db-kind--${epistemic.kind}`)}>{epistemic.label}</span>
          </p>
          <strong className="cc2-pressure__summary-value">
            {formatOptional(index)}
            {index !== null && <small>/ 100</small>}
          </strong>
        </div>
        <div className="cc2-pressure__summary-meta">
          <p className="hint">
            {index === null
              ? 'The API did not return a platform pressure index for this snapshot.'
              : indicators.length === 0
                ? 'The API returned an index but no indicators behind it, so it cannot be checked against anything.'
                : `Mean of ${indicators.length} pressure indicator${indicators.length === 1 ? '' : 's'}. A figure near 0 means the platform is within capacity; near 100 means the ceilings below are reached.`}
          </p>
          {ceiling > 0 && (
            <p className="hint">
              Raw totals across all indicators: <span className="mono">{observed.toLocaleString('en-GB')}</span> of{' '}
              <span className="mono">{ceiling.toLocaleString('en-GB')}</span>.
            </p>
          )}
        </div>
      </div>

      {indicators.length === 0 ? (
        <p className="hint">No pressure indicators were returned for this snapshot.</p>
      ) : (
        <ul className="cc2-pressure__list">
          {indicators.map((indicator) => {
            const score = clampScore(indicator.score);
            return (
              <li className="cc2-pressure__row" key={indicator.key}>
                <div className="cc2-pressure__row-head">
                  <span className="cc2-pressure__row-label">{indicator.label}</span>
                  <span className="cc2-pressure__row-raw mono">
                    {formatOptional(indicator.observed, (value) => value.toLocaleString('en-GB'))} /{' '}
                    {formatOptional(indicator.ceiling, (value) => value.toLocaleString('en-GB'))}
                  </span>
                  <span className={cx('cc2-pressure__row-score', `cc2-pressure__row-score--${pressureTone(score)}`)}>
                    {score}
                  </span>
                </div>
                <span
                  className="bar"
                  role="progressbar"
                  aria-valuenow={score}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${indicator.label}: ${score} of 100, from ${indicator.observed} observed against a ceiling of ${indicator.ceiling}`}
                >
                  <span
                    className={`bar__fill bar__fill--${pressureTone(score)}`}
                    style={{ width: `${score}%` }}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
