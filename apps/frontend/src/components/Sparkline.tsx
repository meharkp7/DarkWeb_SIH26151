import { cx } from '../lib/format';

export interface SparklineProps {
  /** Series of 0–1 scores in presentation order. */
  readonly values: readonly number[];
  /** Accessible description of what the series represents. */
  readonly label: string;
  readonly width?: number;
  readonly height?: number;
  readonly className?: string;
}

/**
 * Mini inline-SVG sparkline (no chart library).
 * Renders `null` for an empty series so callers can show an empty state.
 */
export function Sparkline({ values, label, width = 150, height = 34, className }: SparklineProps) {
  if (values.length === 0) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const innerWidth = width - 2;
  const innerHeight = height - 4;

  const points = values
    .map((value, index) => {
      const ratio = values.length === 1 ? 0 : index / (values.length - 1);
      const x = 1 + ratio * innerWidth;
      const y = 2 + innerHeight - ((value - min) / range) * innerHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      className={cx('sparkline', className)}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      {values.length > 1 && <polyline className="sparkline__line" points={points} />}
      {values.map((value, index) => {
        const ratio = values.length === 1 ? 0 : index / (values.length - 1);
        const x = 1 + ratio * innerWidth;
        const y = 2 + innerHeight - ((value - min) / range) * innerHeight;
        return (
          <circle
            key={`${index}-${value}`}
            className="sparkline__dot"
            cx={x}
            cy={y}
            r={values.length === 1 ? 3 : 1.8}
          >
            <title>{`${index + 1}: ${(Math.round(value * 1000) / 10).toFixed(1)}%`}</title>
          </circle>
        );
      })}
    </svg>
  );
}
