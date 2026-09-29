export interface ScoreRingProps {
  /** 0–1 value; clamped before rendering so a bad API value cannot break the ring. */
  readonly value: number;
  /** Caption under the number, e.g. "confidence" or "raw score". */
  readonly label?: string;
}

const RADIUS = 38;

/**
 * Circular 0–1 gauge. Lives in its own file because both the Overview signal
 * header and the Assessment tab render it.
 */
export function ScoreRing({ value, label = 'confidence' }: ScoreRingProps) {
  const circumference = 2 * Math.PI * RADIUS;
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const dash = clamped * circumference;
  return (
    <div className="score-ring">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle className="score-ring__track" cx="50" cy="50" r={RADIUS} />
        <circle
          className="score-ring__value"
          cx="50"
          cy="50"
          r={RADIUS}
          strokeDasharray={`${dash} ${circumference - dash}`}
        />
      </svg>
      <div>
        <b>{Math.round(clamped * 100)}%</b>
        <small>{label}</small>
      </div>
    </div>
  );
}
