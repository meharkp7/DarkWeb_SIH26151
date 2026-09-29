import { useMemo, useState } from 'react';
import { formatDate, formatDateTime, formatPercent, shortId } from '../../lib/format';
import { Badge } from '../Badge';
import { EmptyState, ErrorState, LoadingState } from '../States';
import type { ApiResource } from '../../hooks/useApi';
import type { CaseTimeline, TimelineEvent, TimelineLayer } from '../../api/types';

export interface TimelineLanesProps {
  readonly timeline: ApiResource<CaseTimeline>;
  /** Jump to the Evidence tab with the record open. */
  readonly onSelectEvidence: (evidenceId: string) => void;
}

const TIMELINE_ENDPOINT = 'GET /api/v1/cases/{id}/timeline';

const LAYER_LABEL: Record<TimelineLayer, string> = {
  event: 'Event',
  actor: 'Actor activity',
  infrastructure: 'Infrastructure',
  financial: 'Financial',
};

const W = 1120;
const LANE_X = 16;
const LANE_W = 116;
const PLOT_X = LANE_X + LANE_W + 10;
const PLOT_W = W - PLOT_X - LANE_X;
const ROW_H = 26;
const TICK_COUNT = 6;

interface Placed {
  readonly event: TimelineEvent;
  readonly index: number;
}

function parse(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Spread events that land on the same instant down a lane.
 *
 * A swimlane is unreadable if twenty events sit on one pixel, so events within
 * `1.5%` of the visible span share a column and stack vertically.
 */
function cluster(events: readonly TimelineEvent[], span: number): Map<string, number> {
  const column = new Map<string, number>();
  const sorted = [...events].sort((left, right) => {
    const a = parse(left.occurred_at) ?? 0;
    const b = parse(right.occurred_at) ?? 0;
    return a - b;
  });
  const window = Math.max(span * 0.015, 1000);
  let current: { anchor: number; index: number } | null = null;
  for (const event of sorted) {
    const at = parse(event.occurred_at) ?? 0;
    const key = eventKey(event);
    if (current === null || at - current.anchor > window) {
      const next: number = current === null ? 0 : current.index + 1;
      current = { anchor: at, index: next };
    }
    column.set(key, current.index);
  }
  return column;
}

function eventKey(event: TimelineEvent): string {
  return `${event.layer}::${event.title}::${event.detail ?? ''}::${parse(event.occurred_at) ?? 0}`;
}

/**
 * Layered timeline.
 *
 * Four lanes share one time axis so a financial event can be read against the
 * infrastructure change it followed. The SVG is the picture; the table beneath
 * it carries the same events as real markup, because a chart alone is not
 * reachable for a screen reader or for a copy-paste into a report.
 */
export function TimelineLanes({ timeline, onSelectEvidence }: TimelineLanesProps) {
  const [selected, setSelected] = useState<string | null>(null);

  const model = useMemo(() => {
    const data = timeline.data;
    if (data === null) return null;
    const events = data.events;
    const stamps = events
      .map((event) => parse(event.occurred_at))
      .filter((value): value is number => value !== null);
    if (stamps.length === 0) return { events, min: 0, max: 0, lanes: [] as Array<{ layer: TimelineLayer; placed: Placed[]; height: number }> };

    const min = Math.min(...stamps);
    const max = Math.max(...stamps);
    const span = Math.max(1, max - min);
    const layers = data.layers.length > 0 ? data.layers : (['event', 'actor', 'infrastructure', 'financial'] as const);
    const columns = cluster(events, span);

    const lanes = layers.map((layer) => {
      const own = events.filter((event) => event.layer === layer);
      const placed = own.map((event) => ({ event, index: columns.get(eventKey(event)) ?? 0 }));
      const depth = placed.reduce((deepest, row) => Math.max(deepest, row.index), 0) + 1;
      return { layer, placed, height: Math.max(ROW_H, depth * ROW_H) };
    });
    return { events, min, max, lanes };
  }, [timeline.data]);

  if (timeline.loading) return <LoadingState label="Loading investigation timeline…" />;
  if (timeline.error !== null) return <ErrorState message={timeline.error} onRetry={timeline.reload} />;
  if (model === null || model.lanes.length === 0) {
    return (
      <EmptyState
        title="No timeline"
        message="This investigation has no recorded events, so there is no sequence to plot."
        endpoint={TIMELINE_ENDPOINT}
      />
    );
  }

  const span = Math.max(1, model.max - model.min);
  const scaleX = (value: number) => PLOT_X + ((value - model.min) / span) * PLOT_W;
  const totalHeight = 34 + model.lanes.reduce((total, lane) => total + lane.height + 12, 0) + 26;
  let offsetY = 30;
  const laneTops = model.lanes.map((lane) => {
    const top = offsetY;
    offsetY += lane.height + 12;
    return top;
  });
  const selectedEvent = model.events.find((event) => eventKey(event) === selected) ?? null;
  const layerCounts = model.lanes.map((lane) => lane.placed.length);

  return (
    <>
      <div className="panel">
        <div className="panel__head">
          <div className="panel__headings">
            <h2 className="panel__title">Investigation timeline</h2>
            <p className="panel__desc">
              Four layers over one time axis. Select an event to read its detail, confidence and
              the evidence record behind it.
            </p>
          </div>
          <div className="panel__actions">
            <span className="surface-meta">
              {model.events.length} events across {model.lanes.length} layers
            </span>
          </div>
        </div>

        <div className="panel__body">
          <div className="inv-lanes">
            <svg
              className="inv-network__canvas"
              viewBox={`0 0 ${W} ${totalHeight}`}
              role="img"
              aria-label={`Timeline for this investigation: ${layerCounts
                .map((count, index) => `${LAYER_LABEL[model.lanes[index]?.layer ?? 'event']} ${count}`)
                .join(', ')}`}
            >
              {Array.from({ length: TICK_COUNT }, (_, index) => {
                const at = model.min + (span * index) / (TICK_COUNT - 1);
                const x = scaleX(at);
                return (
                  <g key={at}>
                    <line className="inv-lanes__grid" x1={x} y1={22} x2={x} y2={totalHeight - 22} />
                    <text className="inv-lanes__tick" x={x} y={totalHeight - 8}>
                      {formatDate(new Date(at).toISOString())}
                    </text>
                  </g>
                );
              })}

              {model.lanes.map((lane, index) => {
                const top = laneTops[index] ?? 0;
                return (
                  <g key={lane.layer}>
                    <rect
                      className={`inv-lanes__lane-bg${index % 2 === 1 ? ' is-alt' : ''}`}
                      x={LANE_X}
                      y={top}
                      width={W - LANE_X * 2}
                      height={lane.height}
                      rx="6"
                    />
                    <text className="inv-lanes__lane-label" x={LANE_X + 10} y={top + 16}>
                      {LAYER_LABEL[lane.layer]}
                    </text>
                    {lane.placed.map((row) => {
                      const at = parse(row.event.occurred_at) ?? model.min;
                      const x = scaleX(at);
                      const y = top + 14 + row.index * ROW_H;
                      const key = eventKey(row.event);
                      return (
                        <g key={key}>
                          <line className="inv-lanes__stem" x1={PLOT_X - 4} y1={y} x2={x} y2={y} />
                          <circle
                            className={[
                              'inv-lanes__dot',
                              `inv-lanes__dot--${row.event.layer}`,
                              selected === key ? 'is-selected' : '',
                            ]
                              .filter(Boolean)
                              .join(' ')}
                            cx={x}
                            cy={y}
                            r="5"
                            role="button"
                            tabIndex={0}
                            aria-label={`${row.event.title}, ${formatDateTime(row.event.occurred_at)}, ${LAYER_LABEL[row.event.layer]} layer`}
                            onClick={() => setSelected(selected === key ? null : key)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setSelected(selected === key ? null : key);
                              }
                            }}
                          >
                            <title>{row.event.title}</title>
                          </circle>
                        </g>
                      );
                    })}
                  </g>
                );
              })}
            </svg>
          </div>

          {selectedEvent !== null && (
            <div className="inv-event" style={{ marginTop: 14 }}>
              <h4>{selectedEvent.title}</h4>
              <dl>
                <dt>Layer</dt>
                <dd>{LAYER_LABEL[selectedEvent.layer]}</dd>
                <dt>Occurred</dt>
                <dd>{formatDateTime(selectedEvent.occurred_at)}</dd>
                {selectedEvent.action !== null && (
                  <>
                    <dt>Action</dt>
                    <dd className="mono">{selectedEvent.action}</dd>
                  </>
                )}
                <dt>Confidence</dt>
                <dd>
                  {selectedEvent.confidence === null ? (
                    <span className="hint">not scored</span>
                  ) : (
                    <Badge tone={selectedEvent.confidence >= 0.75 ? 'ok' : selectedEvent.confidence >= 0.5 ? 'warn' : 'danger'}>
                      {formatPercent(selectedEvent.confidence)}
                    </Badge>
                  )}
                </dd>
                <dt>Detail</dt>
                <dd>{selectedEvent.detail ?? <span className="hint">none recorded</span>}</dd>
                <dt>Evidence</dt>
                <dd>
                  {selectedEvent.evidence_id === null ? (
                    <span className="hint">no evidence record attached to this event</span>
                  ) : (
                    <button
                      type="button"
                      className="link-button mono"
                      onClick={() => onSelectEvidence(selectedEvent.evidence_id as string)}
                    >
                      {shortId(selectedEvent.evidence_id, 12)}
                    </button>
                  )}
                </dd>
              </dl>
            </div>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel__head">
          <div className="panel__headings">
            <h2 className="panel__title">Timeline events</h2>
            <p className="panel__desc">The same events as text, for search, copy and screen readers.</p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <caption className="sr-only">Timeline events for this investigation, by layer</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Layer</th>
                <th scope="col">Event</th>
                <th scope="col">Detail</th>
                <th scope="col">Confidence</th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {[...model.events]
                .sort((left, right) => (parse(right.occurred_at) ?? 0) - (parse(left.occurred_at) ?? 0))
                .map((event) => (
                  <tr key={eventKey(event)}>
                    <td>{formatDateTime(event.occurred_at)}</td>
                    <td>{LAYER_LABEL[event.layer]}</td>
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setSelected(eventKey(event))}
                      >
                        {event.title}
                      </button>
                    </td>
                    <td>{event.detail ?? <span className="hint">—</span>}</td>
                    <td>
                      {event.confidence === null ? (
                        <span className="hint">—</span>
                      ) : (
                        formatPercent(event.confidence)
                      )}
                    </td>
                    <td>
                      {event.evidence_id === null ? (
                        <span className="hint">—</span>
                      ) : (
                        <button
                          type="button"
                          className="link-button mono"
                          onClick={() => onSelectEvidence(event.evidence_id as string)}
                        >
                          {shortId(event.evidence_id, 12)}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
