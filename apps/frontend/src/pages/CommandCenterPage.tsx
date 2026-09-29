import { useCallback, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AttributionPanel } from '../components/analytics/AttributionPanel';
import { PressurePanel } from '../components/analytics/PressurePanel';
import { VelocityChart } from '../components/analytics/VelocityChart';
import { Badge } from '../components/Badge';
import type { Tone } from '../components/Badge';
import { DataBlock } from '../components/DataBlock';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { SourceReliabilityStrip } from '../components/quality/SourceReliabilityStrip';
import { TimeRangeNotice } from '../components/TimeRangeControl';
import { useApi } from '../hooks/useApi';
import { useLive } from '../hooks/useLive';
import { filterByTimeRange, useTimeRange } from '../store/TimeRange';
import { apiUrl } from '../api/client';
import type {
  CaseQueueEntry,
  CommandPosture,
  DashboardSnapshot,
  LiveActivity,
  SlaState,
} from '../api/types';
import { formatCount, formatOptional, leadFor } from '../lib/explain';
import { cx, formatDateTime, shortId } from '../lib/format';
import { useAuth } from '../store/auth';

const DASHBOARD_URL = apiUrl('/v1/dashboard/summary');

/** How many queue rows the console shows before deferring to the register. */
const QUEUE_PREVIEW = 8;
/** How many ledger entries fit above the fold without becoming a wall. */
const LEDGER_PREVIEW = 8;

const SLA_TONE: Record<SlaState, Tone> = {
  breached: 'danger',
  at_risk: 'warn',
  ok: 'ok',
  none: 'neutral',
};

const SLA_LABEL: Record<SlaState, string> = {
  breached: 'Breached',
  at_risk: 'At risk',
  ok: 'On track',
  none: 'No deadline',
};

/** Severity is stated in words, so the colour is never the only carrier. */
function severityTone(severity: string): Tone {
  if (severity === 'critical') return 'danger';
  if (severity === 'high') return 'warn';
  return 'neutral';
}

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
}

/**
 * A snapshot frame is allowed to be partial: the websocket and the REST summary
 * are the same document, but a deployment mid-upgrade can still be serving the
 * older shape. Reading a missing block as "absent" keeps the rest of the
 * console on screen instead of failing the whole page.
 */
function block<K extends keyof DashboardSnapshot>(
  snapshot: Partial<DashboardSnapshot> | null,
  key: K,
): DashboardSnapshot[K] | null {
  if (snapshot === null) return null;
  return snapshot[key] ?? null;
}

function signedWeight(weight: number): string {
  return weight > 0 ? `+${weight}` : String(weight);
}

function number(value: number): string {
  return value.toLocaleString('en-GB');
}

function actionLabel(event: LiveActivity): string {
  const message = event.payload.message;
  if (typeof message === 'string' && message.trim() !== '') return message;
  return event.action.replaceAll('.', ' ');
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function LiveStatus({
  connected,
  degradedReason,
  serverTime,
  onRefresh,
}: {
  readonly connected: boolean;
  readonly degradedReason: string | null;
  readonly serverTime: string | null;
  readonly onRefresh: () => void;
}) {
  const state = degradedReason !== null ? 'degraded' : connected ? 'live' : 'down';
  const label =
    state === 'degraded' ? 'Live — degraded' : state === 'live' ? 'Live' : 'Reconnecting';
  return (
    <div className="cc2-live">
      <span className={cx('cc2-live__chip', `cc2-live__chip--${state}`)} role="status">
        <i className="cc2-live__dot" aria-hidden="true" />
        {label}
      </span>
      <span className="cc2-live__time">
        Server time <span className="mono">{formatDateTime(serverTime)}</span>
      </span>
      <button type="button" className="btn btn--ghost btn--small" onClick={onRefresh}>
        Refresh
      </button>
      <Link className="btn btn--small" to="/cases">
        Investigations
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Command posture
// ---------------------------------------------------------------------------

interface PostureTile {
  readonly key: string;
  readonly label: string;
  readonly value: number | null;
  /** The denominator or window that makes the figure readable on its own. */
  readonly qualifier: string;
  readonly tone: Tone;
  readonly to: string;
}

/**
 * A tile shows a dash when the posture block was not in the frame.
 *
 * The tiles used to substitute 0 for a missing figure, which reads as "nothing
 * is wrong" — the one conclusion a blank dashboard must never invite.
 */
function postureTiles(posture: CommandPosture | null, total: number | null): PostureTile[] {
  const safe = posture;
  const denominator =
    total === null ? 'register total not returned' : `of ${number(total)} investigation${total === 1 ? '' : 's'}`;
  return [
    {
      key: 'active',
      label: 'Active investigations',
      value: safe?.active_investigations ?? null,
      qualifier: denominator,
      tone: 'info',
      to: '/cases?status=active',
    },
    {
      key: 'critical',
      label: 'Critical',
      value: safe?.critical ?? null,
      qualifier: denominator,
      tone: 'danger',
      to: '/cases?priority=critical',
    },
    {
      key: 'high',
      label: 'High priority',
      value: safe?.high ?? null,
      qualifier: denominator,
      tone: 'warn',
      to: '/cases?priority=high',
    },
    {
      key: 'sla',
      label: 'SLA at risk or breached',
      value: safe?.sla_at_risk ?? null,
      qualifier: 'due within 12 hours',
      tone: 'warn',
      to: '/cases?sla=at_risk',
    },
    {
      key: 'evidence',
      label: 'New evidence',
      value: safe?.new_evidence ?? null,
      qualifier: 'collected in 7 days',
      tone: 'ok',
      to: '/cases?sort=recent_evidence',
    },
    {
      key: 'contradictions',
      label: 'Unresolved contradictions',
      value: safe?.unresolved_links ?? null,
      qualifier: 'assessments still contradicted',
      tone: 'danger',
      to: '/cases?sort=contradictions',
    },
  ];
}

function PostureTiles({ posture, total }: { readonly posture: CommandPosture | null; readonly total: number | null }) {
  const tiles = postureTiles(posture, total);
  return (
    <section className="cc2-tiles" aria-label="Command posture">
      {tiles.map((tile) => (
        <Link
          key={tile.key}
          className="cc2-tile"
          to={tile.to}
          aria-label={`${tile.label}: ${formatOptional(tile.value)}, ${tile.qualifier}. Opens the investigations register filtered to this queue.`}
        >
          <span className="cc2-tile__label">{tile.label}</span>
          <strong className={cx('cc2-tile__value', `cc2-tile__value--${tile.tone}`)}>
            {formatOptional(tile.value)}
          </strong>
          <span className="cc2-tile__qualifier">{tile.qualifier}</span>
        </Link>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Priority queue
// ---------------------------------------------------------------------------

/**
 * Everything the score is made of.
 *
 * The signed contributions are shown rather than a prose headline because a
 * queue an analyst cannot audit is a queue they will eventually stop trusting.
 */
function WhyPrioritised({ row }: { readonly row: CaseQueueEntry }) {
  const total = row.reasons.reduce((sum, reason) => sum + reason.weight, 0);
  const reconciles = total === row.queue_score;
  return (
    <div className="cc2-queue__why">
      <p className="cc2-queue__why-head">
        <span className="eyebrow">Why prioritised</span>
        <span className="cc2-queue__why-total">
          {number(row.queue_score)} / 100
        </span>
      </p>
      <p className="hint">{row.queue_reason}</p>
      <ul className="cc2-reasons">
        {row.reasons.map((reason) => (
          <li className="cc2-reason" key={`${row.case_id}-${reason.key}`}>
            <span className="cc2-reason__label">{reason.label}</span>
            <span
              className={cx('cc2-reason__weight', reason.weight > 0 ? 'cc2-reason__weight--up' : 'cc2-reason__weight--down')}
            >
              {signedWeight(reason.weight)}
            </span>
          </li>
        ))}
      </ul>
      <p className="hint">
        {reconciles
          ? `These ${row.reasons.length} signed contributions sum to the queue score of ${number(row.queue_score)}.`
          : `These ${row.reasons.length} signed contributions total ${number(total)}; the published score is ${number(row.queue_score)}, capped at 100 by the API.`}
      </p>
    </div>
  );
}

function QueueRow({
  row,
  expanded,
  onToggle,
  onOpen,
}: {
  readonly row: CaseQueueEntry;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly onOpen: (event: MouseEvent<HTMLTableDataCellElement>) => void;
}) {
  const detailId = `queue-why-${row.case_id}`;
  return (
    <>
      <tr className={cx('cc2-queue__row', expanded && 'cc2-queue__row--open')}>
        <td className="cc2-queue__cell cc2-queue__cell--score">
          <span className="mono">{number(row.queue_score)}</span>
        </td>
        <td className="cc2-queue__cell cc2-queue__cell--case" onClick={onOpen}>
          <Link className="cc2-queue__name" to={`/cases/${encodeURIComponent(row.case_id)}`}>
            {row.name}
          </Link>
          <span className="cc2-queue__meta">
            <span className="mono">{shortId(row.case_id, 8)}</span>
            <Badge tone={severityTone(row.severity)}>{row.severity}</Badge>
            <span className="cc2-queue__status">{row.status.replaceAll('_', ' ')}</span>
          </span>
        </td>
        <td className="cc2-queue__cell cc2-queue__cell--num" onClick={onOpen}>
          <span className="mono">{number(row.counts.evidence)}</span>
          <span className="cc2-queue__cell-sub">{number(row.counts.recent_evidence)} in 7d</span>
        </td>
        <td className="cc2-queue__cell cc2-queue__cell--num" onClick={onOpen}>
          <span className="mono">{number(row.counts.relationships)}</span>
          <span className="cc2-queue__cell-sub">
            {number(row.counts.contradictions)} contradiction
            {row.counts.contradictions === 1 ? '' : 's'}
          </span>
        </td>
        <td className="cc2-queue__cell" onClick={onOpen}>
          <Badge tone={SLA_TONE[row.sla_state]}>{SLA_LABEL[row.sla_state]}</Badge>
          <span className="cc2-queue__cell-sub">{formatDateTime(row.sla_due_at)}</span>
        </td>
        <td className="cc2-queue__cell" onClick={onOpen}>
          {row.assigned_to === null ? (
            <span className="cc2-queue__unassigned">Unassigned</span>
          ) : (
            <span className="mono" title={row.assigned_to}>
              {shortId(row.assigned_to, 8)}
            </span>
          )}
        </td>
        <td className="cc2-queue__cell cc2-queue__cell--toggle">
          <button
            type="button"
            className="cc2-queue__toggle"
            aria-expanded={expanded}
            aria-controls={detailId}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
          >
            {expanded ? 'Hide reasons' : 'Why'}
            <span className="cc2-queue__chevron" aria-hidden="true">
              {expanded ? '▴' : '▾'}
            </span>
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="cc2-queue__detail" id={detailId}>
          <td colSpan={7}>
            <WhyPrioritised row={row} />
          </td>
        </tr>
      )}
    </>
  );
}

function PriorityQueue({ rows }: { readonly rows: readonly CaseQueueEntry[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const navigate = useNavigate();
  const toggle = useCallback(
    (caseId: string) => setOpenId((current) => (current === caseId ? null : caseId)),
    [],
  );

  /**
   * The row is a pointer shortcut to the case workspace; the case name carries
   * the same destination for keyboard and screen-reader users. Modified clicks
   * are left alone so cmd-click still opens a background tab via the real link.
   */
  const open = useCallback(
    (caseId: string) => (event: MouseEvent<HTMLTableDataCellElement>) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      navigate(`/cases/${encodeURIComponent(caseId)}`);
    },
    [navigate],
  );

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No investigations registered"
        message="The platform has no investigation records, so there is no priority queue to rank. Nothing is inferred in place of the missing data."
        endpoint="GET /api/v1/dashboard/summary"
      />
    );
  }

  const visible = rows.slice(0, QUEUE_PREVIEW);
  return (
    <>
      <div className="table-wrap">
        <table className="data-table cc2-queue">
          <caption className="data-table__caption">
            Priority queue, highest score first. Expand a row for the signed contributions behind its score.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="cc2-queue__cell--score">Score</th>
              <th scope="col">Investigation</th>
              <th scope="col" className="cc2-queue__cell--num">Evidence</th>
              <th scope="col" className="cc2-queue__cell--num">Links</th>
              <th scope="col">SLA</th>
              <th scope="col">Owner</th>
              <th scope="col">
                <span className="cc2-visually-hidden">Reasons</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <QueueRow
                key={row.case_id}
                row={row}
                expanded={openId === row.case_id}
                onToggle={() => toggle(row.case_id)}
                onOpen={open(row.case_id)}
              />
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > visible.length && (
        <p className="cc2-queue__more">
          Showing the {visible.length} highest-scoring of {formatCount(rows.length, 'investigation')}.{' '}
          <Link to="/cases">Open the full register</Link>.
        </p>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Activity ledger and platform counts
// ---------------------------------------------------------------------------

function ActivityLedger({ rows }: { readonly rows: readonly LiveActivity[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No recorded activity"
        message="Nothing has been written to the activity ledger yet. The ledger fills as cases, evidence and assessments change."
        endpoint="GET /api/v1/dashboard/activity"
      />
    );
  }
  return (
    <ul className="cc2-activity">
      {rows.slice(0, LEDGER_PREVIEW).map((event) => (
        <li key={event.seq}>
          <Link
            className="cc2-activity__row"
            to={event.case_id === null ? '/threat-watch' : `/cases/${encodeURIComponent(event.case_id)}`}
          >
            <span className="cc2-activity__time mono">{formatDateTime(event.occurred_at)}</span>
            <span className="cc2-activity__seq mono">#{event.seq}</span>
            <span className="cc2-activity__text">
              {actionLabel(event)}
              {event.case_id !== null && (
                <span className="cc2-activity__case mono">{shortId(event.case_id, 8)}</span>
              )}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function PlatformStrip({ snapshot }: { readonly snapshot: DashboardSnapshot | null }) {
  const counts = block(snapshot, 'counts');
  const items: ReadonlyArray<{ readonly key: string; readonly label: string; readonly value: number | null }> = [
    { key: 'cases', label: 'Cases', value: counts?.cases ?? null },
    { key: 'evidence', label: 'Evidence', value: counts?.evidence ?? null },
    { key: 'entities', label: 'Entities', value: counts?.entities ?? null },
    { key: 'relationships', label: 'Relationships', value: counts?.relationships ?? null },
    { key: 'assessments', label: 'Assessments', value: counts?.assessments ?? null },
  ];
  // `critical_alerts` is absent from a partial frame for the same reason the
  // counts are: a frame that did not carry it did not measure it.
  const alerts = snapshot === null ? null : snapshot.critical_alerts;
  return (
    <section className="cc2-strip" aria-label="Platform footprint">
      <ul className="cc2-strip__items">
        {items.map((item) => (
          <li className="cc2-strip__item" key={item.key}>
            <span className="cc2-strip__value mono">{formatOptional(item.value)}</span>
            <span className="cc2-strip__label">{item.label}</span>
          </li>
        ))}
        <li className={cx('cc2-strip__item', (alerts ?? 0) > 0 && 'cc2-strip__item--alert')}>
          <span className="cc2-strip__value mono">{formatOptional(alerts)}</span>
          <span className="cc2-strip__label">
            Critical alert{(alerts ?? 0) === 1 ? '' : 's'}
            {(alerts ?? 0) > 0 && ' — review now'}
          </span>
        </li>
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function CommandCenterPage() {
  const { snapshot, connected, degradedReason, refresh } = useLive();
  const { identity } = useAuth();
  const { from, to, label: windowLabel, isActive } = useTimeRange();
  /**
   * The socket is the fast path, not the only one. If it is refused the
   * console still has to load — and to be able to say *why* it is empty — so
   * the summary endpoint is also read directly, with a retry the analyst can
   * trigger.
   */
  const rest = useApi<DashboardSnapshot>(DASHBOARD_URL);
  const data = snapshot ?? rest.data;
  const loading = snapshot === null && rest.loading;
  const error = snapshot === null ? rest.error : null;

  const queue = useMemo(
    () => [...(block(data, 'case_summaries') ?? [])].sort((left, right) => right.queue_score - left.queue_score),
    [data],
  );

  /**
   * The window over the two things on this console that happened at a moment.
   *
   * The operating picture arrives over a websocket, so there is no query to
   * bound here and the narrowing is done in the browser over the frame already
   * in hand — which is exactly why both blocks below say so. The queue is
   * measured by *last activity*: an investigation opened last month and worked
   * on this morning is something the analyst learned about this morning. The
   * ledger is measured by when the write happened, which is the one date it
   * carries.
   */
  const queueInWindow = useMemo(
    () => filterByTimeRange(queue, (row) => row.last_activity, from, to),
    [queue, from, to],
  );

  const posture = block(data, 'command_posture');
  // The register total is the posture block's own count. Falling back to the
  // number of rows on screen would present a truncated queue as the whole
  // register, and every "of N" tile with it.
  const total = posture?.total_investigations ?? null;
  const velocity = block(data, 'evidence_velocity') ?? [];
  const pressure = block(data, 'investigation_pressure') ?? [];
  const attribution = block(data, 'attribution_posture') ?? [];
  // Held: the window below keys on the ledger, and a fresh array every render
  // would re-narrow the feed on every frame the socket delivers.
  const activity = useMemo(() => block(data, 'activity') ?? [], [data]);
  const ledger = useMemo(
    () => filterByTimeRange(activity, (event) => event.occurred_at, from, to),
    [activity, from, to],
  );

  const headline = useMemo(() => {
    if (posture === null) {
      return 'Awaiting the live operating picture from the AEGIS API.';
    }
    const ranked = queueInWindow.rows;
    /*
     * An empty window is not an all-clear. "Nothing requires intervention"
     * would be a claim about the whole register, and the window says nothing
     * about the investigations it left out.
     */
    if (ranked.length === 0 && queue.length > 0) {
      return `${windowLabel}: no investigation was worked on inside that window, out of ${number(
        queue.length,
      )} in the register. That is a fact about the window, not a statement that nothing needs attention.`;
    }
    if ((posture.critical === 0 && posture.sla_at_risk === 0 && posture.unresolved_links === 0) && ranked.length === 0) {
      return 'Nothing requires intervention: no investigations are registered.';
    }
    if ((posture.critical === 0 && posture.sla_at_risk === 0) && ranked.length === 0) {
      return 'Nothing requires intervention right now: no investigation is critical and no deadline is at risk.';
    }
    const top = ranked[0];
    const alerts = data?.critical_alerts ?? 0;
    if (top === undefined) return 'No investigations are registered, so there is no queue to rank.';
    const windowed = isActive ? ` within ${windowLabel}` : '';
    return alerts > 0
      ? `${number(alerts)} critical alert${alerts === 1 ? '' : 's'} open. ${top.name} heads the queue${windowed} at ${number(top.queue_score)} of 100.`
      : `${top.name} heads the queue${windowed} at ${number(top.queue_score)} of 100.`;
  }, [data, posture, queue, queueInWindow.rows, isActive, windowLabel]);

  const isDegraded = degradedReason !== null;
  const isStale = data !== null && !connected && !isDegraded;

  return (
    <div className="page-stack cc2-page">
      <header className="cc2-head">
        <div className="cc2-head__main">
          <span className="eyebrow">Every figure states its basis</span>
          <h1 className="cc2-head__title">
            {greeting()}, {identity?.name ?? 'Analyst'}.
          </h1>
          <p className="cc2-head__sub">{headline}</p>
        </div>
        <LiveStatus
          connected={connected}
          degradedReason={degradedReason}
          serverTime={data?.server_time ?? null}
          onRefresh={() => {
            refresh();
            rest.reload();
          }}
        />
      </header>

      {isDegraded && (
        <p className="cc2-notice cc2-notice--danger" role="alert">
          <strong>Live updates are degraded.</strong> {degradedReason} The figures below are the last
          good snapshot, not the current state.
        </p>
      )}
      {isStale && (
        <p className="cc2-notice" role="status">
          <strong>Not live.</strong> The command socket is closed, so these figures were fetched once
          over HTTP and will not move until it reconnects.
        </p>
      )}

      {loading && <LoadingState label="Loading the command picture…" />}
      {error !== null && <ErrorState message={error} onRetry={rest.reload} />}

      {!loading && error === null && (
        <>
          <DataBlock
            title="Command posture"
            eyebrow="State of the register"
            lead={leadFor('command.posture', { total })}
            dense
            className="db--plain"
          >
            {/*
              The tiles are platform-wide counters with no date on them, and
              the one below them is labelled all-time. A window cannot narrow
              them, and a queue that is bounded beside an unbounded set of
              tiles is a comparison an analyst will make anyway — so it is
              refused in words rather than left to be inferred.
            */}
            {isActive && (
              <p className="tr-notice">
                {`${windowLabel} — these tiles are not bounded by this window. They count the whole register, every day, because a count of investigations still needing attention does not stop mattering when it is old. The window applies to the priority queue and the activity ledger below.`}
              </p>
            )}
            <PostureTiles posture={posture} total={total} />
          </DataBlock>

          {/* Directly under the posture tiles: which sources the posture is
              built on, and how many of them are one voice. A command picture
              that shows case counts without showing where the evidence came
              from cannot be weighed. */}
          <SourceReliabilityStrip />

          <DataBlock
            title="Priority queue"
            eyebrow="Derived, and auditable line by line"
            lead={leadFor('priority.queue', { total })}
            actions={
              <span className="surface-meta">
                {formatCount(
                  isActive ? queueInWindow.rows.length : queue.length,
                  'investigation',
                )}
              </span>
            }
          >
            <TimeRangeNotice
              window={windowLabel}
              shown={queueInWindow.rows.length}
              total={queue.length}
              basis={`in the browser over the ${queue.length} ${
                queue.length === 1 ? 'row' : 'rows'
              } in this live frame, by last activity — the summary endpoint takes no time bound`}
              undated={queueInWindow.undated}
            />
            <PriorityQueue rows={queueInWindow.rows} />
          </DataBlock>

          <div className="cc2-split">
            <DataBlock
              title="Evidence velocity"
              eyebrow="Collection rate, month by month"
              lead={leadFor('evidence.velocity', { buckets: velocity.length })}
            >
              {velocity.length === 0 ? (
                <EmptyState
                  title="No velocity series"
                  message="The summary endpoint returned no evidence-velocity buckets, so there is no trend to draw."
                  endpoint="GET /api/v1/dashboard/summary"
                />
              ) : (
                <>
                  <VelocityChart points={velocity} />
                  <ul className="cc2-velocity__legend">
                    <li>
                      <span className="cc2-legend__swatch cc2-legend__swatch--up" aria-hidden="true" />rose
                      against the previous period
                    </li>
                    <li>
                      <span className="cc2-legend__swatch cc2-legend__swatch--down" aria-hidden="true" />
                      fell against the previous period
                    </li>
                    <li>
                      <span className="cc2-legend__swatch cc2-legend__swatch--flat" aria-hidden="true" />
                      unchanged
                    </li>
                  </ul>
                </>
              )}
            </DataBlock>

            <DataBlock
              title="Investigation pressure"
              eyebrow="Scaled against declared ceilings"
              lead={leadFor('investigation.pressure')}
            >
              {pressure.length === 0 && posture === null ? (
                <EmptyState
                  title="No pressure indicators"
                  message="The summary endpoint returned no pressure indicators for this snapshot."
                  endpoint="GET /api/v1/dashboard/summary"
                />
              ) : (
                <PressurePanel indicators={pressure} pressureIndex={posture?.pressure_index ?? null} />
              )}
            </DataBlock>
          </div>

          <DataBlock
            title="Attribution posture"
            eyebrow="Estimates stay labelled"
            lead={leadFor('attribution.posture', { limit: attribution.length })}
            actions={<span className="surface-meta">{formatCount(attribution.length, 'case')}</span>}
          >
            <AttributionPanel rows={attribution} />
          </DataBlock>

          <div className="cc2-split">
            <DataBlock
              title="Activity ledger"
              eyebrow="What the platform recorded"
              lead={leadFor('activity.feed', { shown: LEDGER_PREVIEW })}
              actions={
                <Link className="btn btn--ghost btn--small" to="/threat-watch">
                  Threat watch
                </Link>
              }
            >
              <TimeRangeNotice
                window={windowLabel}
                shown={ledger.rows.length}
                total={activity.length}
                basis={`in the browser over the ${activity.length} ${
                  activity.length === 1 ? 'entry' : 'entries'
                } in this live frame, by when each write happened — the summary endpoint takes no time bound`}
                undated={ledger.undated}
              />
              <ActivityLedger rows={ledger.rows} />
            </DataBlock>

            <DataBlock
              title="Platform footprint"
              eyebrow="All-time totals, nothing filtered"
              lead={leadFor('platform.counts')}
            >
              {isActive && (
                <p className="tr-notice">
                  {`${windowLabel} — not bounded by this window. These are the store's all-time totals, and the critical-alert figure counts every audit entry recorded as critical since collection began. Set the window to all time to read the console as one view.`}
                </p>
              )}
              <PlatformStrip snapshot={data} />
              {posture !== null && (
                <dl className="kv kv--tight cc2-posture__facts">
                  <dt>Unassigned</dt>
                  <dd>{number(posture.unassigned)} of {number(posture.total_investigations)}</dd>
                  <dt>Queue pressure</dt>
                  <dd>{number(posture.pressure_index)} of 100</dd>
                </dl>
              )}
            </DataBlock>
          </div>
        </>
      )}
    </div>
  );
}
