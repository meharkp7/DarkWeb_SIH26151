import type { Tone } from '../Badge';
import { Badge } from '../Badge';
import { epistemicLabel } from '../../lib/explain';

/**
 * How an attribution figure should be described.
 *
 * The registry stores the score on the actor row itself rather than computing
 * it at render time, so it is classed the same way the investigations register
 * classes a stored attribution: a recorded score, not an opinion formed in the
 * browser. `null` is a third thing entirely — nobody has assessed this actor —
 * and it gets its own label rather than a bar at zero.
 */
const RECORDED = epistemicLabel('assessment');

export interface ActorConfidenceProps {
  readonly confidence: number | null;
  /** Rendered smaller, for a rail fact rather than a table cell. */
  readonly compact?: boolean;
}

export function ActorConfidence({ confidence, compact = false }: ActorConfidenceProps) {
  if (confidence === null || !Number.isFinite(confidence)) {
    return (
      <span className="act-conf act-conf__none">
        <span className="act-conf__value">—</span>
        {!compact && <small className="act-exp__hint">Not assessed</small>}
      </span>
    );
  }

  const clamped = Math.min(1, Math.max(0, confidence));
  const percent = Math.round(clamped * 1000) / 10;
  const tone: Tone = clamped >= 0.75 ? 'ok' : clamped >= 0.5 ? 'warn' : 'danger';

  return (
    <span className="act-conf">
      <span className="act-conf__value">{`${percent}%`}</span>
      <span
        className="act-conf__track"
        role="meter"
        aria-label="Attribution confidence"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuetext={`${percent}%, ${RECORDED.label.toLowerCase()}`}
      >
        <i className={`act-conf__fill act-conf__fill--${tone}`} style={{ width: `${clamped * 100}%` }} />
      </span>
      {!compact && <Badge tone="neutral">{RECORDED.label}</Badge>}
    </span>
  );
}