import { cx } from '../lib/format';

export interface SparklineProps {
  /** Series of 0–1 scores in presentation order. */
  readonly values: readonly number[];
  /** Accessible description of what the series represents. */
  readonly label: string;
  readonly width?: number;
  readonly height?: number;
  readonly className?: string;
  /**
   * How a point is written in its tooltip. Defaults to a 0–1 score as a
   * percentage, which is what the callers that predate this prop are drawing;
   * a series of counts has to say so rather than rendering "4.0% of nothing".
   */
  readonly formatValue?: (value: number) => string;
}

/**
 * Mini inline-SVG sparkline (no chart library).
 *
 * Renders `null` for an empty series *and* for one containing a non-finite
 * value, so a caller can show an empty state rather than shipping a path with
 * `NaN` coordinates — which is not a chart, it is an empty `<polyline>` that
 * still occupies the cell and still reads as a measurement.
 *
 * The degenerate cases the geometry has to survive, all of which occur in real
 * registry data:
 *
 * - **all-zero** — `max - min` is 0, so the divisor falls back to 1 and every
 *   point lands on the baseline. A flat line at zero *is* the data, so it is
 *   drawn; a caller that would rather say "no trend recorded" must decide that
 *   before calling, because a sparkline cannot tell a real zero from a
 *   substituted one.
 * - **single point** — the ratio is 0 rather than `0 / 0`, so the point sits at
 *   the left edge instead of producing `NaN`.
 * - **decreasing** — nothing special: min and max are read over the whole
 *   series, so a falling line is drawn falling rather than mirrored.
 */
export function Sparkline({
  values,
  label,
  width = 150,
  height = 34,
  className,
  formatValue,
}: SparklineProps) {
  if (values.length === 0) return null;
  if (!values.every((value) => typeof value === 'number' && Number.isFinite(value))) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const innerWidth = width - 2;
  const innerHeight = height - 4;
  const say = formatValue ?? ((value: number) => `${(Math.round(value * 1000) / 10).toFixed(1)}%`);

  const position = (index: number) => {
    const ratio = values.length === 1 ? 0 : index / (values.length - 1);
    const x = 1 + ratio * innerWidth;
    const y = 2 + innerHeight - ((values[index] as number) - min) / range * innerHeight;
    return { x, y };
  };

  const points = values
    .map((_, index) => {
      const { x, y } = position(index);
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
        const { x, y } = position(index);
        return (
          <circle
            key={`${index}-${value}`}
            className="sparkline__dot"
            cx={x}
            cy={y}
            r={values.length === 1 ? 3 : 1.8}
          >
            <title>{`${index + 1}: ${say(value)}`}</title>
          </circle>
        );
      })}
    </svg>
  );
}
