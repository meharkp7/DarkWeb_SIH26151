import { useMemo, useState } from 'react';
import { api } from '../../api/client';
import type { TemporalRefusal, TemporalShift, TemporalShiftReport } from '../../api/types';
import { useApi } from '../../hooks/useApi';
import { leadFor } from '../../lib/explain';
import { cx, formatDateTime, shortId } from '../../lib/format';
import { EmptyState, ErrorState, LoadingState } from '../States';
import { ActivitySeries } from './ActivitySeries';
import '../../styles/workspace-temporal.css';

/**
 * Behavioural shifts, on the workspace timeline tab.
 *
 * The tab next door is a chronological list: it says what happened when. This
 * says when something *changed* — the boundary, the evidence either side of it,
 * the series it sits in, and what the detector cannot conclude.
 *
 * The rules this panel is built around, each of which a naive version breaks:
 *
 * - **A sharpness bar is drawn only where the number has a 0-1 scale.** A CUSUM
 *   alarm and a mean-shift gain are unit-scale and unbounded, so a bar beside
 *   them would invite exactly the comparison their units forbid. They are
 *   printed as a number with the unit named, and the cell says why there is no
 *   bar.
 * - **Nothing is carried by colour or by length alone.** Which side of the
 *   boundary a bar falls on is stated in the legend; the boundary is dashed and
 *   captioned; a confirmed state change says "confirmed", not "1.0".
 * - **Limitations render at the weight of the finding.** They are inside the
 *   expanded row, under a heading that says what they are, and they are the
 *   detector's own words rather than a summary.
 * - **A refusal is not a blank.** Too-short windows are listed with the count
 *   supplied, the count required and the rule, because "no change detected" and
 *   "nothing to detect in" are different findings.
 * - **A row with no analysis available says so**, rather than rendering as an
 *   empty table that reads like a clean result.
 */

const SHIFTS_ENDPOINT = 'GET /api/v1/cases/{id}/temporal/shifts';

type SortKey = 'when' | 'subject';
type SortDir = 'ascending' | 'descending';

const METHODS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'binary_segmentation', label: 'mean-shift split' },
  { id: 'ks', label: 'KS-distance split' },
  { id: 'cusum', label: 'CUSUM' },
];

/**
 * Detectors whose score has a stable 0-1 scale, and only those.
 *
 * A confirmed state change is 1.0 by construction — the persistence rule was
 * satisfied or the change was not emitted — so a full bar is truthful. A KS
 * distance is a distribution distance in [0, 1]. A CUSUM alarm accumulates
 * unboundedly with run length and a segmentation gain scales with the series it
 * came from; drawing either against a fixed track would invite a comparison the
 * detector's own documentation rules out.
 */
const UNIT_SCALE_DETECTORS = new Set(['state_change']);

export interface BehaviouralShiftsProps {
  readonly caseId: string;
  readonly onSelectEvidence: (id: string) => void;
}

export function BehaviouralShifts({
  caseId,
  onSelectEvidence,
}: BehaviouralShiftsProps): JSX.Element {
  const [method, setMethod] = useState('binary_segmentation');
  const url = api.temporalShiftsUrl(caseId, { method });
  const report = useApi<TemporalShiftReport>(url);
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: 'when',
    dir: 'descending',
  });
  const [open, setOpen] = useState<string | null>(null);

  const rows = useMemo(() => {
    if (report.data === null) return [];
    const list = [...report.data.shifts];
    const factor = sort.dir === 'ascending' ? 1 : -1;
    list.sort((a, b) => {
      if (sort.key === 'subject') {
        const left = (a.subject_label ?? a.subject_id).toLowerCase();
        const right = (b.subject_label ?? b.subject_id).toLowerCase();
        if (left !== right) return left.localeCompare(right) * factor;
      }
      const left = Date.parse(a.changed_at);
      const right = Date.parse(b.changed_at);
      if (left !== right) return (left - right) * factor;
      return a.change_id.localeCompare(b.change_id);
    });
    return list;
  }, [report.data, sort]);

  const toggleSort = (key: SortKey): void => {
    setSort((current) =>
      current.key === key
        ? { key, dir: current.dir === 'ascending' ? 'descending' : 'ascending' }
        : { key, dir: key === 'when' ? 'descending' : 'ascending' },
    );
  };

  const body = ((): JSX.Element => {
    if (report.loading) return <LoadingState label="Running the change detectors…" />;
    if (report.error !== null) {
      return <ErrorState message={report.error} onRetry={report.reload} />;
    }
    if (report.data === null) return <LoadingState />;

    const data = report.data;
    if (data.shifts.length === 0 && data.refusals.length === 0) {
      return (
        <EmptyState
          title="No stored history to analyse"
          message={data.basis}
          endpoint={SHIFTS_ENDPOINT.replace('{id}', caseId)}
        />
      );
    }

    return (
      <>
        {data.refusals.length > 0 && <Refusals refusals={data.refusals} />}
        {data.shifts.length === 0 ? (
          <p className="bs-empty">
            {data.basis} Nothing was scored, and nothing was found: the two are not the
            same claim, and the refusals above are what separates them.
          </p>
        ) : (
          <ShiftTable
            rows={rows}
            sort={sort}
            onSort={toggleSort}
            open={open}
            onToggle={(id) => setOpen((current) => (current === id ? null : id))}
            onSelectEvidence={onSelectEvidence}
          />
        )}
      </>
    );
  })();

  return (
    <section className="bs-panel" aria-labelledby="behavioural-shifts-heading">
      <div className="bs-panel__head">
        <div>
          <h3 className="bs-panel__title" id="behavioural-shifts-heading">
            Behavioural shifts
          </h3>
          {report.data !== null && <p className="bs-panel__basis">{report.data.basis}</p>}
        </div>
        <div className="bs-panel__controls">
          <label className="bs-field" htmlFor="bs-method">
            detector
            <select
              id="bs-method"
              value={method}
              onChange={(event) => setMethod(event.target.value)}
            >
              {METHODS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {report.data !== null && (
        <p className="bs-panel__basis" style={{ padding: '0 16px 10px' }}>
          {leadFor('temporal.shifts', {
            count: report.data.shifts.length,
            total: report.data.observations,
          })}
        </p>
      )}
      {body}
      <div className="bs-refusals" style={{ borderBottom: 0, borderTop: '1px solid var(--line)' }}>
        <p className="bs-limits__head">What these numbers do not show</p>
        <ul className="bs-limits__list">
          {report.data === null
            ? (report.error !== null ? [<li key="e">{report.error}</li>] : [])
            : report.data.limitations.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </div>
    </section>
  );
}

/** Too-short windows, named. An empty analysis is not a clean result. */
function Refusals({ refusals }: { readonly refusals: readonly TemporalRefusal[] }): JSX.Element {
  return (
    <div className="bs-refusals">
      <p className="bs-refusals__summary">
        {leadFor('temporal.refusals', { count: refusals.length })}
      </p>
      <ul className="bs-refusals__list">
        {refusals.map((refusal) => (
          <li className="bs-refusal" key={`${refusal.subject_id}-${refusal.channel}`}>
            <p className="bs-refusal__head">
              <span className="bs-refusal__badge">not assessed</span>
              <span>
                {refusal.subject_label ?? shortId(refusal.subject_id)} · {refusal.channel}
              </span>
              <span className="bs-refusal__counts">
                {refusal.observed} / {refusal.required} {refusal.unit}
              </span>
            </p>
            <p className="bs-refusal__reason">{refusal.reason}</p>
            <p className="bs-refusal__rule">rule: {refusal.rule}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ShiftTable({
  rows,
  sort,
  onSort,
  open,
  onToggle,
  onSelectEvidence,
}: {
  readonly rows: readonly TemporalShift[];
  readonly sort: { key: SortKey; dir: SortDir };
  readonly onSort: (key: SortKey) => void;
  readonly open: string | null;
  readonly onToggle: (id: string) => void;
  readonly onSelectEvidence: (id: string) => void;
}): JSX.Element {
  return (
    <div className="bs-scroll">
      <table className="bs-table">
        <caption className="sr-only">
          Behavioural changes detected in this case, with the score the detecting algorithm
          produced, the evidence on each side of the boundary, and the detector's limitations.
        </caption>
        <thead>
          <tr>
            <th scope="col" aria-sort={sort.key === 'when' ? sort.dir : 'none'}>
              <button type="button" className="bs-sort" onClick={() => onSort('when')}>
                When
                <span className="bs-sort__caret" aria-hidden="true">
                  {sort.key === 'when' ? (sort.dir === 'ascending' ? '▲' : '▼') : '↕'}
                </span>
              </button>
            </th>
            <th scope="col" aria-sort={sort.key === 'subject' ? sort.dir : 'none'}>
              <button type="button" className="bs-sort" onClick={() => onSort('subject')}>
                What changed
                <span className="bs-sort__caret" aria-hidden="true">
                  {sort.key === 'subject' ? (sort.dir === 'ascending' ? '▲' : '▼') : '↕'}
                </span>
              </button>
            </th>
            <th scope="col">How sharp</th>
            <th scope="col">Detector</th>
            <th scope="col">
              <span className="sr-only">Expand</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <ShiftRows
              key={row.change_id}
              row={row}
              expanded={open === row.change_id}
              onToggle={onToggle}
              onSelectEvidence={onSelectEvidence}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A shift is one row that expands into a second; `<tr>` cannot hold a toggle. */
function ShiftRows({
  row,
  expanded,
  onToggle,
  onSelectEvidence,
}: {
  readonly row: TemporalShift;
  readonly expanded: boolean;
  readonly onToggle: (id: string) => void;
  readonly onSelectEvidence: (id: string) => void;
}): JSX.Element {
  const panelId = `bs-detail-${row.change_id}`;
  return (
    <>
      <tr>
        <td className="bs-when">
          {formatDateTime(row.changed_at)}
          {row.direction !== null && (
            <span className="bs-row__kind">{row.direction === 'increase' ? 'up' : 'down'}</span>
          )}
        </td>
        <td>
          <button
            type="button"
            className="bs-row__toggle"
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={() => onToggle(row.change_id)}
          >
            <span className="bs-row__caret" aria-hidden="true">
              {expanded ? '▼' : '▶'}
            </span>
            <span>
              <span className="bs-row__subject">
                {row.subject_label ?? shortId(row.subject_id)}
              </span>
              <span className="bs-row__kind">{row.summary}</span>
            </span>
          </button>
        </td>
        <td>
          <Sharpness row={row} />
        </td>
        <td>
          <span className="bs-detector">{row.detector_label}</span>
          {row.distribution_distance !== null && (
            <span className="bs-row__kind">
              KS distance {row.distribution_distance.toFixed(2)}
            </span>
          )}
        </td>
        <td>
          <button
            type="button"
            className="bs-btn"
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={() => onToggle(row.change_id)}
          >
            {expanded ? 'close' : 'evidence'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="bs-detail">
          <td colSpan={5}>
            <div className="bs-detail__inner" id={panelId}>
              <div>
                <h4>Evidence either side</h4>
                <div className="bs-windows">
                  <Window window={row.before} side="before" />
                  <Window window={row.after} side="after" />
                </div>
                <h4>What this does not show</h4>
                <div className="bs-limits">
                  <ul className="bs-limits__list">
                    {row.limitations.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              </div>
              <div>
                <ActivitySeries
                  title={`${row.subject_label ?? shortId(row.subject_id)} — ${
                    row.channel_label
                  }`}
                  points={row.context}
                  changedAt={row.changed_at}
                  emptyNote="This change carried no surrounding context: the detector fired in a bucket with no observations either side of it, which is worth knowing before the boundary is read as a date."
                />
                <h4>Cited by the change point</h4>
                <p className="bs-cites">
                  {row.evidence_ids.length === 0
                    ? 'none — the detector fired in a zero-filled bucket with no event behind it'
                    : row.evidence_ids.join(', ')}
                </p>
                {onSelectEvidence !== undefined &&
                  row.evidence_ids
                    .filter((id) => !id.startsWith('temporal-observation:'))
                    .map((id) => (
                      <button
                        key={id}
                        type="button"
                        className="bs-btn"
                        style={{ marginRight: 6 }}
                        onClick={() => onSelectEvidence(id)}
                      >
                        open {shortId(id)}
                      </button>
                    ))}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** One side of a boundary, with its counts and its citations. */
function Window({
  window,
  side,
}: {
  readonly window: TemporalShift['before'];
  readonly side: 'before' | 'after';
}): JSX.Element {
  const values = window.values.length > 0 ? window.values.join(', ') : '—';
  const counts =
    window.buckets > 0
      ? `${window.buckets} buckets, mean ${window.mean_count?.toFixed(2) ?? '—'} events`
      : `${window.event_count} sightings`;
  return (
    <div className={cx('bs-window', `bs-window--${side}`)}>
      <p className="bs-window__label">{side === 'before' ? 'Before' : 'From the change'}</p>
      <p className="bs-window__values">{values}</p>
      <p className="bs-window__stats">
        {counts}
        <br />
        {window.from_at !== null && window.to_at !== null
          ? `${formatDateTime(window.from_at)} → ${formatDateTime(window.to_at)}`
          : 'no timestamps on this side'}
      </p>
      <p className="bs-cites">
        {window.evidence_ids.length === 0
          ? 'no evidence on this side'
          : `${window.evidence_ids.length} cited: ${window.evidence_ids.join(', ')}`}
      </p>
    </div>
  );
}

/**
 * The detector's own score, drawn only where a bar would mean something.
 *
 * The bar is a picture of a number, and it lies the moment the number has no
 * fixed scale. Where the scale is 0-1 the bar is drawn and the value is printed
 * beside it; where it is not, the value is printed with its unit and the cell
 * says there is deliberately no bar.
 */
function Sharpness({ row }: { readonly row: TemporalShift }): JSX.Element {
  const unitScale = UNIT_SCALE_DETECTORS.has(row.detector);
  const label =
    row.detector === 'state_change'
      ? 'confirmed — the new value persisted'
      : row.detector === 'ks'
        ? 'KS distance, 0 to 1'
        : row.detector === 'cusum'
          ? 'cumulative excess — not comparable across run lengths'
          : 'between-regime variance — comparable only within this series';
  return (
    <span className="bs-sharp">
      {unitScale ? (
        <span
          className="bs-sharp__track"
          role="img"
          aria-label={`Sharpness: ${row.sharpness.toFixed(2)} of 1 — ${label}`}
        >
          <span
            className="bs-sharp__fill"
            style={{ width: `${Math.round(Math.min(1, Math.max(0, row.sharpness)) * 100)}%` }}
          />
        </span>
      ) : (
        <span className="sr-only">No bar: {label}.</span>
      )}
      <span className="bs-sharp__value">{row.sharpness.toFixed(2)}</span>
      <span className="bs-sharp__unit">{label}</span>
    </span>
  );
}
