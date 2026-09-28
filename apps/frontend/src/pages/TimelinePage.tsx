import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { TimelineBars } from '../components/TimelineBars';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { Badge } from '../components/Badge';
import { formatDateTime, shortId } from '../lib/format';
import { useSession } from '../store/session';

interface TimelineRow {
  readonly id: string;
  readonly label: string;
  readonly detail: string;
  readonly observedAt: string | null;
  readonly collectedAt: string;
  readonly start: Date;
  readonly end: Date;
}

function toRow(item: {
  evidence_id: string;
  entity_type?: string | null;
  source_type: string;
  raw_artifact_uri: string;
  observed_at?: string | null;
  collected_at: string;
}): TimelineRow | null {
  const toMs = (value: string | null | undefined): number | null => {
    if (value === null || value === undefined || value === '') return null;
    const parsed = new Date(value).getTime();
    return Number.isNaN(parsed) ? null : parsed;
  };
  const stamps = [toMs(item.observed_at), toMs(item.collected_at)].filter(
    (value): value is number => value !== null,
  );
  if (stamps.length === 0) return null;
  return {
    id: item.evidence_id,
    label: item.entity_type ?? item.source_type,
    detail: item.raw_artifact_uri,
    observedAt: item.observed_at ?? null,
    collectedAt: item.collected_at,
    start: new Date(Math.min(...stamps)),
    end: new Date(Math.max(...stamps)),
  };
}

/**
 * Screen 5 — timeline.
 *
 * The backend has no timeline route yet, so events are derived honestly from
 * evidence held in this session: one bar per record spanning its
 * observed → collected interval.
 */
export function TimelinePage() {
  const { evidence } = useSession();

  const rows = useMemo(
    () =>
      evidence
        .map(toRow)
        .filter((row): row is TimelineRow => row !== null)
        .sort((left, right) => left.start.getTime() - right.start.getTime()),
    [evidence],
  );

  const columns: ReadonlyArray<Column<TimelineRow>> = [
    {
      key: 'event',
      header: 'Event',
      render: (row) => (
        <>
          <strong>{row.label}</strong>
          <br />
          <span className="hint mono">{row.detail}</span>
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
      key: 'evidence',
      header: 'Evidence',
      render: (row) => (
        <span className="mono" title={row.id}>
          {shortId(row.id, 12)}
        </span>
      ),
    },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Timeline</h1>
          <p className="page-sub">
            Interval-aware view of observed activity. No <code>GET /api/v1/timeline</code> route
            exists yet, so this renders events derived from evidence loaded in this session —
            never invented ones.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/evidence">
            Load evidence
          </Link>
        </div>
      </header>

      <Panel title="Observed → collected" description="One bar per evidence record.">
        {rows.length === 0 ? (
          <EmptyState
            title="No timeline events"
            message="The timeline endpoint is not implemented and this session has no evidence records. Fetch or ingest evidence first, then its observed/collected intervals appear here."
            endpoint="GET /api/v1/timeline"
          >
            <Link className="btn btn--primary" to="/evidence">
              Open evidence explorer
            </Link>
          </EmptyState>
        ) : (
          <>
            <TimelineBars
              items={rows.map((row) => ({
                id: row.id,
                start: row.start,
                end: row.end,
                label: row.label,
              }))}
              label="Evidence observed to collected intervals"
            />
            <p className="hint">
              Bars show the gap between when activity was observed and when it was collected —
              long gaps weaken time-sensitive corroboration.
            </p>
          </>
        )}
      </Panel>

      <Panel title="Events" description="Machine-readable list behind the chart.">
        <DataTable<TimelineRow>
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          caption="Timeline events derived from session evidence"
          empty={
            <EmptyState
              title="No events"
              message="Nothing to list until evidence is loaded in this session or the timeline endpoint ships."
              endpoint="GET /api/v1/timeline"
            />
          }
        />
        {rows.length > 0 && (
          <p className="hint">
            <Badge tone="warn">derived</Badge> Rows are client-derived from evidence; a server-side
            timeline (with change points and migrations) is still planned.
          </p>
        )}
      </Panel>
    </div>
  );
}
