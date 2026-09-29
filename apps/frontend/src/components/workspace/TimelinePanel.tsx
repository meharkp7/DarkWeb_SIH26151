import { useMemo } from 'react';
import { formatDate, formatDateTime, formatPercent, scoreTone, shortId } from '../../lib/format';
import { Badge } from '../Badge';
import type { Tone } from '../Badge';
import { DataTable } from '../DataTable';
import type { Column } from '../DataTable';
import { Panel } from '../Panel';
import { EmptyState } from '../States';
import { TimelineBars } from '../TimelineBars';
import type { TimelineItem } from '../TimelineBars';
import type { CaseWorkspace, WorkspaceEntity, WorkspaceEvidence } from '../../api/types';
import { entityLabel, formatLag, indexEntities, metaTitle, timeOf } from './workspaceFormat';

export interface TimelinePanelProps {
  /**
   * Already-resolved workspace payload. The page owns this request and gates
   * its own loading/error before this panel mounts, so the panel reads
   * `workspace.evidence` directly and makes no requests of its own.
   */
  readonly workspace: CaseWorkspace;
  /** Re-fetch the workspace payload; also refreshes the interval chart. */
  readonly onRefresh: () => void;
}

type MilestoneKind = 'case' | 'activity' | 'evidence' | 'link';

interface Milestone {
  readonly id: string;
  readonly at: string;
  readonly kind: MilestoneKind;
  readonly title: string;
  readonly detail: string;
}

interface Interval {
  readonly id: string;
  readonly label: string;
  readonly detail: string;
  readonly observedAt: string | null;
  readonly collectedAt: string;
  readonly start: Date;
  readonly end: Date;
  readonly lagMinutes: number | null;
  readonly reliability: number;
}

const KIND_TONE: Record<MilestoneKind, Tone> = {
  case: 'info',
  activity: 'neutral',
  evidence: 'warn',
  link: 'ok',
};

const KIND_LABEL: Record<MilestoneKind, string> = {
  case: 'case',
  activity: 'audit',
  evidence: 'evidence',
  link: 'link',
};

/** `TimelineBars` stacks one 20px row per item; past this it stops reading as a chart. */
const MAX_BARS = 24;
/** The rail is the overview's answer to "what happened", not the full audit log. */
const MAX_MILESTONES = 30;

const EVIDENCE_ENDPOINT = 'GET /api/v1/cases/{id}/evidence';

function buildMilestones(workspace: CaseWorkspace, byId: ReadonlyMap<string, WorkspaceEntity>): Milestone[] {
  const record = workspace.case;
  const milestones: Milestone[] = [];

  if (record.created_at !== null) {
    milestones.push({
      id: 'case-open',
      at: record.created_at,
      kind: 'case',
      title: 'Investigation opened',
      detail: record.name,
    });
  }
  if (record.closed_at !== null) {
    milestones.push({
      id: 'case-close',
      at: record.closed_at,
      kind: 'case',
      title: 'Investigation closed',
      detail: record.closure_reason ?? 'No closure reason recorded',
    });
  }

  for (const row of workspace.activity) {
    const message = row.payload.message;
    milestones.push({
      id: `audit-${row.seq}`,
      at: row.occurred_at,
      kind: 'activity',
      title: typeof message === 'string' && message !== '' ? message : row.action,
      detail: row.entity_type === null ? row.action : `${row.action} · ${row.entity_type}`,
    });
  }

  for (const item of workspace.evidence) {
    milestones.push({
      id: `evidence-${item.evidence_id}`,
      at: item.collected_at,
      kind: 'evidence',
      title: `Evidence collected · ${item.source_type}`,
      detail: metaTitle(item.metadata) ?? shortId(item.evidence_id, 12),
    });
  }

  for (const link of workspace.relationships) {
    const from = entityLabel(byId, link.subject_entity_id);
    const to = entityLabel(byId, link.object_entity_id);
    milestones.push({
      id: `link-${link.relationship_id}`,
      at: link.first_seen,
      kind: 'link',
      title: `${from} → ${to}`,
      detail: `${link.type} · ${link.evidence_ids.length} backing record${
        link.evidence_ids.length === 1 ? '' : 's'
      }`,
    });
  }

  return milestones.sort((left, right) => {
    const delta = (timeOf(right.at) ?? 0) - (timeOf(left.at) ?? 0);
    return delta === 0 ? left.id.localeCompare(right.id) : delta;
  });
}

/**
 * Turn an evidence record into an observed → collected interval.
 *
 * Returns `null` when neither timestamp parses, so a malformed record is
 * dropped from the chart instead of rendering an `Invalid Date` bar.
 */
function toInterval(item: WorkspaceEvidence): Interval | null {
  const observed = timeOf(item.observed_at);
  const collected = timeOf(item.collected_at);
  const stamps = [observed, collected].filter((value): value is number => value !== null);
  if (stamps.length === 0) return null;
  const start = Math.min(...stamps);
  const end = Math.max(...stamps);
  return {
    id: item.evidence_id,
    label: item.entity_type === null ? item.source_type : `${item.entity_type}`,
    detail: metaTitle(item.metadata) ?? `${item.source_type} · ${formatPercent(item.reliability)}`,
    observedAt: observed === null ? null : item.observed_at,
    collectedAt: item.collected_at,
    start: new Date(start),
    end: new Date(end),
    lagMinutes: observed === null ? null : (end - start) / 60000,
    reliability: item.reliability,
  };
}

function meanLag(intervals: readonly Interval[]): number | null {
  const lags = intervals
    .map((item) => item.lagMinutes)
    .filter((value): value is number => value !== null);
  if (lags.length === 0) return null;
  return lags.reduce((total, value) => total + value, 0) / lags.length;
}

/**
 * Workspace Timeline tab — "how did this investigation evolve?".
 *
 * Everything here, including the observed → collected interval chart
 * harvested from the global `TimelinePage`, is derived from the single
 * `/workspace` payload. An earlier version issued a second
 * `GET /cases/{id}/evidence` call for `observed_at`; the workspace serializer
 * now returns it (along with `entity_type`, `independence_group` and
 * `metadata`), so that round trip is gone and the chart can no longer drift
 * out of step with the rest of the tab.
 */
export function TimelinePanel({ workspace, onRefresh }: TimelinePanelProps) {
  const byId = useMemo(() => indexEntities(workspace.entities), [workspace.entities]);
  const milestones = useMemo(() => buildMilestones(workspace, byId), [workspace, byId]);

  const intervals = useMemo(
    () =>
      workspace.evidence
        .map(toInterval)
        .filter((row): row is Interval => row !== null)
        .sort((left, right) => left.start.getTime() - right.start.getTime()),
    [workspace.evidence],
  );

  const bars = useMemo<readonly TimelineItem[]>(
    () => intervals.slice(-MAX_BARS).map((row) => ({ id: row.id, start: row.start, end: row.end, label: row.label })),
    [intervals],
  );

  const lag = meanLag(intervals);
  const record = workspace.case;
  // Milestones are sorted newest-first, so index 0 is the latest event.
  const latest: Milestone | null = milestones[0] ?? null;
  const firstEvent = timeOf(record.created_at);
  const spanDays =
    firstEvent === null || latest === null
      ? null
      : Math.max(0, Math.round(((timeOf(latest.at) ?? firstEvent) - firstEvent) / 86400000));

  const intervalColumns: ReadonlyArray<Column<Interval>> = [
    {
      key: 'item',
      header: 'Record',
      render: (row) => (
        <>
          <b>{row.label}</b>
          <small className="table-sub">{row.detail}</small>
        </>
      ),
    },
    {
      key: 'observed',
      header: 'Observed',
      render: (row) => formatDateTime(row.observedAt),
    },
    {
      key: 'collected',
      header: 'Collected',
      render: (row) => formatDateTime(row.collectedAt),
    },
    {
      key: 'lag',
      header: 'Lag',
      align: 'end',
      render: (row) =>
        row.lagMinutes === null ? <span className="hint">not observed</span> : formatLag(row.lagMinutes),
    },
    {
      key: 'reliability',
      header: 'Reliability',
      align: 'end',
      render: (row) => <Badge tone={scoreTone(row.reliability)}>{formatPercent(row.reliability)}</Badge>,
    },
  ];

  const linkColumns: ReadonlyArray<Column<CaseWorkspace['relationships'][number]>> = [
    {
      key: 'route',
      header: 'Link',
      render: (row) => (
        <>
          <b>{entityLabel(byId, row.subject_entity_id)}</b>
          <small className="table-sub">
            {row.type} → {entityLabel(byId, row.object_entity_id)}
          </small>
        </>
      ),
    },
    {
      key: 'first',
      header: 'First seen',
      render: (row) => formatDateTime(row.first_seen),
    },
    {
      key: 'last',
      header: 'Last seen',
      render: (row) => formatDateTime(row.last_seen),
    },
    {
      key: 'confidence',
      header: 'Confidence',
      align: 'end',
      render: (row) => formatPercent(row.confidence),
    },
    {
      key: 'backing',
      header: 'Backing records',
      align: 'end',
      render: (row) =>
        row.evidence_ids.length === 0 ? (
          <span className="hint">uncorroborated</span>
        ) : (
          <span title={row.evidence_ids.join(', ')}>{row.evidence_ids.length}</span>
        ),
    },
  ];

  return (
    <>
      <Panel
        title="Investigation evolution"
        description="Case milestones, audited actions, evidence collection and observed links for this case, newest first."
        actions={
          <>
            <span className="surface-meta">{milestones.length} events</span>
            <button type="button" className="btn btn--ghost btn--small" onClick={onRefresh}>
              Refresh
            </button>
          </>
        }
      >
        {milestones.length === 0 ? (
          <EmptyState
            title="No history yet"
            message="This investigation has no recorded events: nothing has been collected, linked or audited against it."
          />
        ) : (
          <>
            <dl className="kv kv--tight">
              <dt>Opened</dt>
              <dd>{formatDateTime(record.created_at)}</dd>
              <dt>Last event</dt>
              <dd>{latest === null ? <span className="hint">unknown</span> : formatDateTime(latest.at)}</dd>
              <dt>Elapsed</dt>
              <dd>{spanDays === null ? <span className="hint">unknown</span> : `${spanDays} d`}</dd>
              <dt>Evidence collected</dt>
              <dd>{workspace.evidence.length}</dd>
              <dt>Links observed</dt>
              <dd>{workspace.relationships.length}</dd>
              <dt>Audited actions</dt>
              <dd>{workspace.activity.length}</dd>
            </dl>

            <div className="timeline">
              {milestones.slice(0, MAX_MILESTONES).map((milestone) => (
                <div className="timeline-row" key={milestone.id} title={formatDateTime(milestone.at)}>
                  <span>{formatDate(milestone.at)}</span>
                  <i aria-hidden="true" />
                  <b>
                    {milestone.title} <Badge tone={KIND_TONE[milestone.kind]}>{KIND_LABEL[milestone.kind]}</Badge>
                  </b>
                  <small>{milestone.detail}</small>
                </div>
              ))}
            </div>

            {milestones.length > MAX_MILESTONES && (
              <p className="hint">
                Showing the {MAX_MILESTONES} most recent of {milestones.length} events. The full
                audit trail is served by <code>GET /api/v1/cases/&#123;id&#125;/activity</code>.
              </p>
            )}
          </>
        )}
      </Panel>

      <Panel
        title="Observed → collected"
        description="One bar per evidence record, spanning when the activity was observed to when it was collected."
        actions={
          <button type="button" className="quiet-button" onClick={onRefresh}>
            Reload ledger
          </button>
        }
      >
        {intervals.length === 0 ? (
          <EmptyState
            title="No timeline events"
            message="No evidence record for this case carries a usable observed or collected timestamp, so no interval can be drawn."
            endpoint={EVIDENCE_ENDPOINT}
          />
        ) : (
          <>
            <TimelineBars
              items={bars}
              label="Evidence observed to collected intervals for this investigation"
            />
            <p className="hint">
              Long gaps between observation and collection weaken time-sensitive corroboration.
              Mean lag {formatLag(lag)} across {intervals.length} record
              {intervals.length === 1 ? '' : 's'}
              {intervals.length > MAX_BARS ? `; the chart shows the last ${MAX_BARS}.` : '.'}
            </p>
            <DataTable<Interval>
              caption="Evidence intervals behind the chart"
              columns={intervalColumns}
              rows={intervals}
              rowKey={(row) => row.id}
              empty={<EmptyState title="No events" message="Nothing to list." endpoint={EVIDENCE_ENDPOINT} />}
            />
          </>
        )}
      </Panel>

      <Panel
        title="Relationship emergence"
        description="When each link was first corroborated and whether it still is."
        actions={<span className="surface-meta">{workspace.relationships.length} links</span>}
      >
        {workspace.relationships.length === 0 ? (
          <EmptyState
            title="No relationships"
            message="No links have been resolved between entities in this investigation, so there is no emergence to plot."
          />
        ) : (
          <DataTable
            caption="Relationship first and last seen"
            columns={linkColumns}
            rows={workspace.relationships}
            rowKey={(row) => row.relationship_id}
          />
        )}
      </Panel>
    </>
  );
}
