import type { VelocityPoint } from '../../api/types';
import { formatOptional } from '../../lib/explain';

export interface VelocityChartProps {
  /** Evidence counts per bucket, oldest first, as the API returns them. */
  readonly points: readonly VelocityPoint[];
  /** Overrides the accessible name of the chart. */
  readonly label?: string;
}

const WIDTH = 720;
const HEIGHT = 232;
const PAD_LEFT = 48;
const PAD_RIGHT = 18;
const PLOT_TOP = 16;
const PLOT_HEIGHT = 128;
const PLOT_BOTTOM = PLOT_TOP + PLOT_HEIGHT;

/** The delta lane sits below the plot so a rising count never hides its change. */
const DELTA_TOP = PLOT_BOTTOM + 18;
const DELTA_HEIGHT = 26;
const DELTA_BASELINE = DELTA_TOP + DELTA_HEIGHT;

const TICK_INTERVALS = 4;

/** A malformed bucket must not be able to put NaN into a path. */
function finite(value: number | null | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/**
 * Round a maximum up to 1/2/2.5/5 x 10^n so the axis reads 0, 25, 50 … rather
 * than 0, 23.7, 47.4 — a tick an analyst has to divide is a tick they ignore.
 */
function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const scaled = value / magnitude;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10;
  return step * magnitude;
}

function deltaText(delta: number | null): string {
  if (delta === null || !Number.isFinite(delta)) return '—';
  return delta > 0 ? `+${delta}` : String(delta);
}

/** A count that is missing says so; a malformed one is not printed as a number. */
function countText(count: number): string {
  return formatOptional(count, (value) => value.toLocaleString('en-GB'));
}

/**
 * Evidence velocity: an area + line chart of the collected count per bucket,
 * with the signed change against the previous bucket drawn as a diverging bar
 * underneath.
 *
 * The delta lane is deliberately separate from the area. A count that is
 * climbing fast and a count that is climbing slowly look identical as area —
 * only the per-bucket change distinguishes a genuine surge from a plateau.
 */
export function VelocityChart({
  points,
  label = 'Evidence records collected per calendar month, ending with the current month',
}: VelocityChartProps) {
  if (points.length === 0) return null;

  const counts = points.map((point) => Math.max(0, finite(point.count)));
  const ceiling = niceCeil(Math.max(1, ...counts));
  const innerWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
  const slot = innerWidth / points.length;
  // Centre every bucket in its own slot. With one bucket that is the middle of
  // the plot rather than a division by zero against (length - 1).
  const xFor = (index: number): number => PAD_LEFT + slot * (index + 0.5);
  const yFor = (count: number): number => PLOT_BOTTOM - (count / ceiling) * PLOT_HEIGHT;

  const maxDelta = Math.max(1, ...points.map((point) => Math.abs(finite(point.delta))));

  const linePath = counts
    .map((count, index) => `${index === 0 ? 'M' : 'L'} ${xFor(index).toFixed(2)} ${yFor(count).toFixed(2)}`)
    .join(' ');
  const first = points[0];
  const last = points[points.length - 1];
  const areaPath =
    first === undefined || last === undefined
      ? ''
      : `${linePath} L ${xFor(points.length - 1).toFixed(2)} ${PLOT_BOTTOM} L ${xFor(0).toFixed(2)} ${PLOT_BOTTOM} Z`;

  const yTicks = Array.from({ length: TICK_INTERVALS + 1 }, (_, index) => {
    const value = (ceiling / TICK_INTERVALS) * index;
    return { value, y: yFor(value) };
  });

  // Monthly series run to roughly a dozen buckets; past that the axis labels
  // would collide, so every other one is dropped rather than overlapped.
  const stride = points.length > 8 ? 2 : 1;

  return (
    <svg
      className="cc2-velocity"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      <desc>
        {points
          .map((point) => `${point.label}: ${countText(point.count)} collected, change ${deltaText(point.delta)}`)
          .join('. ')}
        . Each point is a whole calendar month counted by the date the evidence was collected, and the
        change is against the month before it. A month with nothing collected is drawn as zero, so a
        flat section means nothing arrived rather than that the data is missing.
      </desc>

      {yTicks.map((tick) => (
        <g key={`tick-${tick.value}`}>
          <line
            className="cc2-velocity__grid"
            x1={PAD_LEFT}
            x2={WIDTH - PAD_RIGHT}
            y1={tick.y}
            y2={tick.y}
          />
          <text className="cc2-velocity__tick" x={PAD_LEFT - 8} y={tick.y + 3} textAnchor="end">
            {Math.round(tick.value).toLocaleString('en-GB')}
          </text>
        </g>
      ))}

      <line
        className="cc2-velocity__axis"
        x1={PAD_LEFT}
        x2={WIDTH - PAD_RIGHT}
        y1={PLOT_BOTTOM}
        y2={PLOT_BOTTOM}
      />

      {areaPath !== '' && <path className="cc2-velocity__area" d={areaPath} />}
      {points.length > 1 && <path className="cc2-velocity__line" d={linePath} />}

      <line
        className="cc2-velocity__delta-base"
        x1={PAD_LEFT}
        x2={WIDTH - PAD_RIGHT}
        y1={DELTA_BASELINE}
        y2={DELTA_BASELINE}
      />
      <text className="cc2-velocity__delta-label" x={PAD_LEFT - 8} y={DELTA_BASELINE + 3} textAnchor="end">
        Δ
      </text>

      {points.map((point, index) => {
        const x = xFor(index);
        const y = yFor(counts[index] ?? 0);
        // The first bucket has nothing to compare against; drawing a zero-length
        // "no change" bar there would invent a flat period that never happened.
        const delta = point.delta === null ? null : finite(point.delta);
        const barHeight = delta === null || delta === 0 ? 0 : Math.max(1.5, (Math.abs(delta) / maxDelta) * DELTA_HEIGHT);
        // Three directions, not two: an unchanged bucket is neither a rise nor
        // a fall, and colouring it either way misreads the series.
        const direction = delta === null || delta === 0 ? 'flat' : delta > 0 ? 'up' : 'down';
        const barY = direction === 'up' ? DELTA_BASELINE - barHeight : DELTA_BASELINE;
        const textY =
          direction === 'flat'
            ? DELTA_BASELINE - 5
            : direction === 'up'
              ? DELTA_BASELINE - barHeight - 5
              : DELTA_BASELINE + barHeight + 10;
        return (
          <g key={`${point.label}-${index}`}>
            <circle className="cc2-velocity__dot" cx={x} cy={y} r={3}>
              <title>{`${point.label}: ${countText(point.count)} collected, change ${deltaText(point.delta)}`}</title>
            </circle>
            {index % stride === 0 && (
              <text className="cc2-velocity__label" x={x} y={PLOT_BOTTOM + 14} textAnchor="middle">
                {point.label}
              </text>
            )}
            {delta !== null && direction !== 'flat' && (
              <rect
                className={`cc2-velocity__delta cc2-velocity__delta--${direction}`}
                x={x - Math.min(9, slot / 3)}
                y={barY}
                width={Math.min(18, slot * 0.66)}
                height={barHeight}
                rx={2}
              >
                <title>{`${point.label}: change ${deltaText(point.delta)} against the previous period`}</title>
              </rect>
            )}
            <text
              className={`cc2-velocity__delta-text cc2-velocity__delta-text--${direction}`}
              x={x}
              y={textY}
              textAnchor="middle"
            >
              {deltaText(point.delta)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
