import type { Tone } from './Badge';
import { cx, formatPercent } from '../lib/format';

export interface ScoreBarRow {
  readonly label: string;
  /** 0–1 value. */
  readonly value: number;
  readonly tone?: Tone;
}

export interface ScoreBarsProps {
  readonly rows: readonly ScoreBarRow[];
  /** Accessible description of the chart. */
  readonly label: string;
}

const ROW_HEIGHT = 26;
const CHART_WIDTH = 480;
const LABEL_WIDTH = 104;
const TRACK_WIDTH = 300;

/** Horizontal SVG bar chart for calibrated/raw scores. */
export function ScoreBars({ rows, label }: ScoreBarsProps) {
  const height = rows.length * ROW_HEIGHT + 6;

  return (
    <svg
      className="score-bars"
      viewBox={`0 0 ${CHART_WIDTH} ${height}`}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      {rows.map((row, index) => {
        const y = index * ROW_HEIGHT;
        const clamped = Math.min(1, Math.max(0, row.value));
        const tone = row.tone ?? 'info';
        return (
          <g key={row.label}>
            <text className="score-bars__label" x={0} y={y + 16}>
              {row.label}
            </text>
            <rect
              className="score-bars__track"
              x={LABEL_WIDTH}
              y={y + 6}
              width={TRACK_WIDTH}
              height={10}
              rx={5}
            />
            <rect
              className={cx('score-bars__fill', `score-bars__fill--${tone}`)}
              x={LABEL_WIDTH}
              y={y + 6}
              width={Math.max(2, TRACK_WIDTH * clamped)}
              height={10}
              rx={5}
            />
            <text className="score-bars__value" x={CHART_WIDTH} y={y + 16} textAnchor="end">
              {formatPercent(row.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
