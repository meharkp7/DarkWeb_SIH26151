import { Link } from 'react-router-dom';
import type { AttributionPosture } from '../../api/types';
import { cx, formatPercent, scoreTone, shortId } from '../../lib/format';

export interface AttributionPanelProps {
  /** Leading assessments across the platform, as the API ranked them. */
  readonly rows: readonly AttributionPosture[];
  /** Overrides the accessible name of the list. */
  readonly label?: string;
}

interface Signal {
  readonly name: string;
  readonly value: number;
}

function clamp01(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}

/** Strongest modality first — the point of the list is what is leading. */
function readSignals(row: AttributionPosture): Signal[] {
  return Object.entries(row.signals)
    .filter((entry): entry is [string, number] => Number.isFinite(entry[1]))
    .map(([name, value]) => ({ name, value: clamp01(value) }))
    .sort((left, right) => right.value - left.value);
}

function signalTone(value: number): string {
  const tone = scoreTone(value);
  return tone === 'ok' ? 'ok' : tone === 'warn' ? 'warn' : 'danger';
}

/**
 * Attribution posture: the leading assessment per investigation, with the
 * evidence standing behind the number.
 *
 * A bare confidence percentage is not an assessment — it cannot be challenged.
 * Every row therefore carries the supporting-signal count, the number of
 * distinct modalities, the contradictions still open, and the freshness, so a
 * reader can tell a well-corroborated 80% from a 40%-weighted 80%.
 */
export function AttributionPanel({ rows, label = 'Attribution posture by investigation' }: AttributionPanelProps) {
  if (rows.length === 0) {
    return <p className="hint">No assessment has been produced yet, so there is no attribution to report.</p>;
  }

  return (
    <ul className="cc2-attr" aria-label={label}>
      {rows.map((row) => {
        const confidence = clamp01(row.confidence);
        const signals = readSignals(row);
        return (
          <li className="cc2-attr__row" key={row.case_id}>
            <div className="cc2-attr__head">
              <Link
                className="cc2-attr__name"
                to={`/cases/${encodeURIComponent(row.case_id)}`}
                title={row.case_name}
              >
                {row.case_name}
              </Link>
              <span className="mono cc2-attr__id">{shortId(row.case_id, 8)}</span>
              <span className={cx('cc2-attr__confidence', `cc2-attr__confidence--${scoreTone(confidence)}`)}>
                {formatPercent(confidence)}
              </span>
            </div>

            <span
              className="bar"
              role="progressbar"
              aria-valuenow={Math.round(confidence * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Attribution confidence for ${row.case_name}: ${formatPercent(confidence)}`}
            >
              <span className={`bar__fill bar__fill--${scoreTone(confidence)}`} style={{ width: `${confidence * 100}%` }} />
            </span>

            <dl className="cc2-attr__facts">
              <div>
                <dt>Supporting signals</dt>
                <dd>{row.supporting_signals}</dd>
              </div>
              <div>
                <dt>Modalities</dt>
                <dd>{row.modalities}</dd>
              </div>
              <div>
                <dt>Contradictions</dt>
                <dd className={row.contradictions > 0 ? 'cc2-attr__fact--flag' : undefined}>{row.contradictions}</dd>
              </div>
              <div>
                <dt>Freshness</dt>
                <dd>{formatPercent(row.freshness)}</dd>
              </div>
            </dl>

            {signals.length > 0 && (
              <ul className="cc2-attr__signals" aria-label={`Per-modality signal strength for ${row.case_name}`}>
                {signals.map((signal) => (
                  <li className="cc2-attr__signal" key={`${row.case_id}-${signal.name}`}>
                    <span className="cc2-attr__signal-name">{signal.name}</span>
                    <span className="bar bar--inline cc2-attr__signal-bar">
                      <span
                        className={`bar__fill bar__fill--${signalTone(signal.value)}`}
                        style={{ width: `${Math.max(2, signal.value * 100)}%` }}
                      />
                    </span>
                    <span className="mono cc2-attr__signal-value">{formatPercent(signal.value)}</span>
                  </li>
                ))}
              </ul>
            )}

            {row.explanations.length > 0 && (
              <ul className="cc2-attr__explanations">
                {row.explanations.map((text, index) => (
                  <li key={`${row.case_id}-explanation-${String(index)}`}>{text}</li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}
