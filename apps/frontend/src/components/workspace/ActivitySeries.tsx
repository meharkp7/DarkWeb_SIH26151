import { useId, useMemo, useState } from 'react';
import type { ContextPoint } from '../../api/types';
import { cx, formatDateTime } from '../../lib/format';
import '../../styles/workspace-temporal.css';

/**
 * The stored series behind one detected boundary.
 *
 * Two renderings, because a change point means nothing without the series it
 * sits in, and a series means nothing you can read a value off:
 *
 * - a numeric channel gets bars with the boundary drawn as a labelled line, and
 *   the buckets before and after it drawn in different weights *and* given
 *   different legend swatches, so which side of the line a bar is on is legible
 *   in greyscale and to a screen reader;
 * - a categorical channel has no magnitude to plot, so it is drawn as a value
 *   track with the same boundary marker rather than as a flat line that would
 *   read as "no activity".
 *
 * Every chart carries a real table beneath it. That is not redundancy for its
 * own sake: an SVG of seventy bars is a picture, and the whole basis of the
 * claim is that a number came out of those bars.
 */

const W = 640;
const H = 168;
const PAD_L = 8;
const PAD_R = 8;
const PAD_T = 26;
const PAD_B = 26;

export interface ActivitySeriesProps {
  readonly title: string;
  readonly points: readonly ContextPoint[];
  readonly changedAt: string;
  readonly emptyNote: string;
}

export function ActivitySeries({
  title,
  points,
  changedAt,
  emptyNote,
}: ActivitySeriesProps): JSX.Element {
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  const numeric = points.length > 0 && points.every((point) => point.count !== null);

  const boundary = useMemo(
    () => points.findIndex((point) => point.is_boundary),
    [points],
  );

  if (points.length === 0) {
    return <p className="bs-empty">{emptyNote}</p>;
  }

  return (
    <div className="bs-chart">
      <div className="bs-chart__head">
        <p className="bs-chart__title">{title}</p>
        <p className="bs-chart__note">
          {numeric
            ? `${points.length} buckets · boundary at ${formatDateTime(changedAt)}`
            : `${points.length} sightings · boundary at ${formatDateTime(changedAt)}`}
        </p>
      </div>
      {numeric ? (
        <NumericChart points={points} boundary={boundary} changedAt={changedAt} />
      ) : (
        <ValueTrack points={points} />
      )}
      <button
        type="button"
        className="bs-table-toggle"
        aria-expanded={showTable}
        aria-controls={tableId}
        onClick={() => setShowTable((value) => !value)}
      >
        {showTable ? 'hide the values as a table' : 'show the values as a table'}
      </button>
      {showTable && (
        <table className="bs-values" id={tableId}>
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr>
              <th scope="col">Bucket</th>
              <th scope="col">{numeric ? 'Events' : 'Observed value'}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={`${point.at}-${index}`} data-boundary={point.is_boundary}>
                <th scope="row" style={{ fontWeight: 400 }}>
                  {formatDateTime(point.at)}
                </th>
                <td>
                  {point.value}
                  {point.is_boundary && <span className="bs-boundary-tag">boundary</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/**
 * Bars, one per bucket, with the boundary as a labelled rule.
 *
 * The chart carries no colour-only signal: the bars either side of the boundary
 * differ in weight, the boundary is dashed and captioned, and the legend names
 * both sides in words.
 */
function NumericChart({
  points,
  boundary,
  changedAt,
}: {
  readonly points: readonly ContextPoint[];
  readonly boundary: number;
  readonly changedAt: string;
}): JSX.Element {
  const counts = points.map((point) => point.count ?? 0);
  const peak = Math.max(...counts, 1);
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;
  const step = innerW / points.length;
  const barW = Math.max(1, step - 1);
  const firstLabel = points[0] === undefined ? '' : formatDateTime(points[0].at);
  const last = points[points.length - 1];
  const lastLabel = last === undefined ? '' : formatDateTime(last.at);

  const ticks = [0, Math.round(peak / 2), peak];

  return (
    <>
      <svg
        className="bs-chart__svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Activity per bucket, ${counts.length} buckets, peak ${peak} events. A detected change is marked at ${formatDateTime(changedAt)}. The values are in the table below.`}
      >
        {ticks.map((tick) => {
          const y = PAD_T + innerH - (tick / peak) * innerH;
          return (
            <g key={tick}>
              <line
                className="bs-chart__axis"
                x1={PAD_L}
                x2={W - PAD_R}
                y1={y}
                y2={y}
                strokeDasharray={tick === 0 ? undefined : '2 3'}
              />
              <text className="bs-chart__tick" x={PAD_L} y={y - 3}>
                {tick}
              </text>
            </g>
          );
        })}
        {counts.map((count, index) => {
          const barH = (count / peak) * innerH;
          const isAfter = boundary >= 0 && index >= boundary;
          return (
            <rect
              key={index}
              className={cx('bs-chart__bar', isAfter && 'bs-chart__bar--after')}
              x={PAD_L + index * step}
              y={PAD_T + innerH - barH}
              width={barW}
              height={barH}
            />
          );
        })}
        {boundary >= 0 && boundary < points.length && (
          <>
            <line
              className="bs-chart__boundary"
              x1={PAD_L + boundary * step - 1}
              x2={PAD_L + boundary * step - 1}
              y1={PAD_T - 8}
              y2={PAD_T + innerH}
            />
            <text
              className="bs-chart__boundary-label"
              x={PAD_L + boundary * step + 3}
              y={PAD_T - 10}
            >
              change
            </text>
          </>
        )}
        <text className="bs-chart__tick" x={PAD_L} y={H - 8}>
          {firstLabel}
        </text>
        <text
          className="bs-chart__tick"
          x={W - PAD_R}
          y={H - 8}
          textAnchor="end"
        >
          {lastLabel}
        </text>
      </svg>
      <ul className="bs-chart__legend">
        <li>
          <span className="bs-chart__swatch bs-chart__swatch--before" aria-hidden="true" />
          before the change
        </li>
        <li>
          <span className="bs-chart__swatch bs-chart__swatch--after" aria-hidden="true" />
          from the change
        </li>
        <li>peak {peak} events in a bucket</li>
      </ul>
    </>
  );
}

/**
 * One cell per sighting for a channel with no magnitude.
 *
 * A venue or a handle cannot be plotted, so it is drawn as a sequence and the
 * distinct values are named beneath it. A boundary cell is outlined and dashed
 * rather than filled, because on this channel the state *is* the finding and
 * painting it a different colour would be the only place a meaning rode on hue.
 */
function ValueTrack({ points }: { readonly points: readonly ContextPoint[] }): JSX.Element {
  // Run-length encoded, so "venue A until day 20, venue B after" reads as two
  // values and not as a list of forty identical strings.
  const runs: { value: string; count: number; boundary: boolean }[] = [];
  for (const point of points) {
    const last = runs[runs.length - 1];
    if (last !== undefined && last.value === point.value) last.count += 1;
    else runs.push({ value: point.value, count: 1, boundary: false });
    if (point.is_boundary) {
      const current = runs[runs.length - 1];
      if (current !== undefined) current.boundary = true;
    }
  }
  return (
    <>
      <ol className="bs-track" aria-label="Observed value per sighting, in order">
        {points.map((point, index) => (
          <li
            key={`${point.at}-${index}`}
            className={cx('bs-track__step', point.is_boundary && 'bs-track__step--boundary')}
          >
            <span className="sr-only">
              {formatDateTime(point.at)}: {point.value}
              {point.is_boundary ? ' — detected change' : ''}
            </span>
          </li>
        ))}
      </ol>
      <p className="bs-track__caption">
        {runs
          .map((run) => {
            const label = run.count > 1 ? `${run.value} × ${run.count}` : run.value;
            return run.boundary ? `change → ${label}` : label;
          })
          .join(' · ')}
      </p>
    </>
  );
}
