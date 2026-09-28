export interface TimelineItem {
  readonly id: string;
  readonly start: Date;
  readonly end: Date;
  readonly label: string;
}

const CHART_WIDTH = 920;
const LABEL_WIDTH = 176;
const RIGHT_GUTTER = 28;
const ROW_HEIGHT = 20;
const TOP_PADDING = 12;
const AXIS_HEIGHT = 40;

const TICK_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

function formatStamp(date: Date): string {
  return TICK_FORMAT.format(date);
}

/**
 * Inline-SVG timeline: one horizontal bar per item between `start` and `end`
 * (e.g. observed → collected), on a shared time axis. Deterministic layout —
 * no force simulation, no randomness.
 */
export function TimelineBars({ items, label }: { items: readonly TimelineItem[]; label: string }) {
  if (items.length === 0) return null;

  const times = items.flatMap((item) => [item.start.getTime(), item.end.getTime()]);
  let min = Math.min(...times);
  let max = Math.max(...times);
  if (min === max) {
    const halfDay = 12 * 60 * 60 * 1000;
    min -= halfDay;
    max += halfDay;
  }
  const span = max - min;
  const plotWidth = CHART_WIDTH - LABEL_WIDTH - RIGHT_GUTTER;
  const toX = (time: number): number => LABEL_WIDTH + ((time - min) / span) * plotWidth;

  const rowCount = items.length;
  const axisY = TOP_PADDING + rowCount * ROW_HEIGHT + 6;
  const height = axisY + AXIS_HEIGHT;

  const tickCount = 4;
  const ticks = Array.from({ length: tickCount }, (_, index) => {
    const time = min + (span * index) / (tickCount - 1);
    return { time, x: toX(time) };
  });

  return (
    <svg
      className="timeline-svg"
      viewBox={`0 0 ${CHART_WIDTH} ${height}`}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      {ticks.map((tick) => (
        <g key={tick.time}>
          <line
            className="timeline-svg__grid"
            x1={tick.x}
            y1={TOP_PADDING - 4}
            x2={tick.x}
            y2={axisY}
          />
          <text className="timeline-svg__tick" x={tick.x} y={axisY + 18} textAnchor="middle">
            {formatStamp(new Date(tick.time))}
          </text>
        </g>
      ))}
      <line
        className="timeline-svg__axis"
        x1={LABEL_WIDTH}
        y1={axisY}
        x2={CHART_WIDTH - RIGHT_GUTTER}
        y2={axisY}
      />
      {items.map((item, index) => {
        const y = TOP_PADDING + index * ROW_HEIGHT;
        const x1 = toX(Math.min(item.start.getTime(), item.end.getTime()));
        const x2 = toX(Math.max(item.start.getTime(), item.end.getTime()));
        const barWidth = Math.max(4, x2 - x1);
        const duration = item.end.getTime() - item.start.getTime();
        const durationText =
          duration === 0
            ? 'instantaneous'
            : `${Math.round(duration / (1000 * 60))} min from start to end`;
        return (
          <g key={item.id}>
            <text className="timeline-svg__label" x={0} y={y + 13}>
              {truncate(item.label, 26)}
            </text>
            <rect className="timeline-svg__bar" x={x1} y={y + 4} width={barWidth} height={10} rx={4}>
              <title>{`${item.label} — ${formatStamp(item.start)} → ${formatStamp(item.end)} (${durationText})`}</title>
            </rect>
          </g>
        );
      })}
    </svg>
  );
}
