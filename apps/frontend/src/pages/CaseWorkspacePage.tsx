import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, formatApiError } from '../api/client';
import {
  CASE_PRIORITIES,
  CASE_SEVERITIES,
  CASE_STATUSES,
} from '../api/types';
import type {
  CaseHypothesis,
  CaseNote,
  CasePriority,
  CaseSeverity,
  CaseStatus,
  CaseWorkspace,
  CaseUpdate,
  InvestigationCase,
  WorkspaceEntity,
  WorkspaceRelationship,
} from '../api/types';
import { useApi } from '../hooks/useApi';
import { useLive } from '../hooks/useLive';
import { formatDateTime, formatPercent, scoreTone, shortId } from '../lib/format';
import { Badge } from '../components/Badge';
import type { Tone } from '../components/Badge';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { EvidenceDrawer } from '../components/EvidenceDrawer';
import { EvidenceForm } from '../components/EvidenceForm';
import { GraphView } from '../components/GraphView';
import type { GraphEdge, GraphNode } from '../components/GraphView';
import { Panel } from '../components/Panel';
import { ScoreBars } from '../components/ScoreBars';
import { AssessmentPanel } from '../components/workspace/AssessmentPanel';
import { ScoreRing } from '../components/workspace/ScoreRing';
import { TimelinePanel } from '../components/workspace/TimelinePanel';
import { metaTitle } from '../components/workspace/workspaceFormat';

type Tab = 'overview' | 'evidence' | 'network' | 'timeline' | 'assessment' | 'notes';

const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'network', label: 'Network' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'assessment', label: 'Assessment' },
  { id: 'notes', label: 'Notes' },
];

const STATUS_TONE: Record<CaseStatus, Tone> = {
  open: 'info',
  active: 'ok',
  on_hold: 'warn',
  closed: 'neutral',
  archived: 'neutral',
};

const PRIORITY_TONE: Record<CasePriority, Tone> = {
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
};

const SEVERITY_TONE: Record<CaseSeverity, Tone> = {
  informational: 'neutral',
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
};

/** GraphView lays nodes on one ring; beyond this it stops being readable. */
const GRAPH_NODE_LIMIT = 20;
const GRAPH_EDGE_LIMIT = 48;

/**
 * Inline triage controls. Every edit is a single-key PATCH so an omitted
 * field is never cleared as a side effect of changing something else.
 */
function TriageBar({
  workspace,
  onPatched,
}: {
  workspace: InvestigationCase & { sla_overdue: boolean };
  onPatched: (updated: InvestigationCase) => void;
}) {
  const [busyField, setBusyField] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slaInput, setSlaInput] = useState(() =>
    workspace.sla_due_at === null ? '' : workspace.sla_due_at.slice(0, 16),
  );
  const [tagsInput, setTagsInput] = useState(() => workspace.tags.join(', '));

  useEffect(() => {
    setSlaInput(workspace.sla_due_at === null ? '' : workspace.sla_due_at.slice(0, 16));
    setTagsInput(workspace.tags.join(', '));
  }, [workspace.sla_due_at, workspace.tags]);

  const patch = useCallback(
    async (field: string, payload: CaseUpdate) => {
      setBusyField(field);
      setError(null);
      try {
        const updated = await api.updateCase(workspace.case_id, payload);
        onPatched(updated);
      } catch (err: unknown) {
        setError(formatApiError(err));
      } finally {
        setBusyField(null);
      }
    },
    [workspace.case_id, onPatched],
  );

  const commitStatus = async (next: CaseStatus) => {
    if (next === workspace.status) return;
    if (next === 'closed') {
      const reason = window.prompt(
        'Closing an investigation requires a closure reason. What was the outcome?',
        workspace.closure_reason ?? '',
      );
      if (reason === null) return;
      if (reason.trim() === '') {
        setError('API 422 — a closure reason is required to close a case.');
        return;
      }
      await patch('status', { status: next, closure_reason: reason.trim() });
      return;
    }
    await patch('status', { status: next });
  };

  return (
    <Panel
      title="Triage"
      description="Priority, severity, ownership and SLA. Closing requires a recorded reason."
    >
      <div className="triage-grid">
        <div className="field">
          <label htmlFor="tb-status">Status</label>
          <select
            id="tb-status"
            value={workspace.status}
            disabled={busyField === 'status'}
            onChange={(event) => void commitStatus(event.target.value as CaseStatus)}
          >
            {CASE_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tb-priority">Priority</label>
          <select
            id="tb-priority"
            value={workspace.priority}
            disabled={busyField === 'priority'}
            onChange={(event) => void patch('priority', { priority: event.target.value as CasePriority })}
          >
            {CASE_PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tb-severity">Severity</label>
          <select
            id="tb-severity"
            value={workspace.severity}
            disabled={busyField === 'severity'}
            onChange={(event) => void patch('severity', { severity: event.target.value as CaseSeverity })}
          >
            {CASE_SEVERITIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tb-sla">SLA due</label>
          <input
            id="tb-sla"
            type="datetime-local"
            value={slaInput}
            disabled={busyField === 'sla_due_at'}
            onChange={(event) => setSlaInput(event.target.value)}
            onBlur={() => {
              const next =
                slaInput === '' ? null : new Date(slaInput).toISOString();
              if (next !== workspace.sla_due_at) {
                void patch('sla_due_at', { sla_due_at: next });
              }
            }}
          />
        </div>
        <div className="field field--wide">
          <label htmlFor="tb-tags">Tags (comma separated)</label>
          <div className="inline-form">
            <input
              id="tb-tags"
              value={tagsInput}
              disabled={busyField === 'tags'}
              onChange={(event) => setTagsInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                const tags = tagsInput
                  .split(',')
                  .map((tag) => tag.trim())
                  .filter((tag) => tag !== '');
                void patch('tags', { tags });
              }}
              placeholder="financial, marketplace"
            />
            <button
              type="button"
              className="btn btn--ghost btn--small"
              disabled={busyField === 'tags'}
              onClick={() => {
                const tags = tagsInput
                  .split(',')
                  .map((tag) => tag.trim())
                  .filter((tag) => tag !== '');
                void patch('tags', { tags });
              }}
            >
              Save
            </button>
          </div>
        </div>
      </div>

      <div className="triage-summary">
        <Badge tone={STATUS_TONE[workspace.status]}>{workspace.status.replace('_', ' ')}</Badge>
        <Badge tone={PRIORITY_TONE[workspace.priority]} title="Priority">
          {workspace.priority}
        </Badge>
        <Badge tone={SEVERITY_TONE[workspace.severity]} title="Severity">
          {workspace.severity}
        </Badge>
        {workspace.sla_overdue && <Badge tone="danger">SLA breached</Badge>}
        {workspace.closed_at !== null && (
          <Badge tone="neutral">closed {formatDateTime(workspace.closed_at)}</Badge>
        )}
        {workspace.assigned_to === null ? (
          <Badge tone="warn">unassigned</Badge>
        ) : (
          <Badge tone="neutral">owner {shortId(workspace.assigned_to, 8)}</Badge>
        )}
      </div>

      {workspace.closure_reason !== null && (
        <p className="hint">
          <strong>Closure reason:</strong> {workspace.closure_reason}
        </p>
      )}
      {error !== null && <ErrorState message={error} />}
    </Panel>
  );
}

function NotesTab({ caseId }: { caseId: string }) {
  const notes = useApi<CaseNote[]>(`/api/v1/cases/${encodeURIComponent(caseId)}/notes`);
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = body.trim();
    if (trimmed === '') {
      setError('A note cannot be blank.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createNote(caseId, { body: trimmed });
      setBody('');
      notes.reload();
    } catch (err: unknown) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Investigative notes"
      description="Analyst working commentary. The separate audit trail is on the Overview tab."
      actions={
        <span className="surface-meta">{notes.data?.length ?? 0} notes</span>
      }
    >
      <div className="field">
        <label htmlFor="note-body">Add a note</label>
        <textarea
          id="note-body"
          rows={3}
          value={body}
          onChange={(event) => setBody(event.target.value)}
          placeholder="What did you observe, and what should the next analyst check?"
        />
      </div>
      <div className="form-actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void submit()}
          disabled={busy}
        >
          {busy ? 'Saving…' : 'Add note'}
        </button>
        <span className="hint">POST /api/v1/cases/{caseId}/notes</span>
      </div>
      {error !== null && <p className="status status--error">{error}</p>}

      <div className="section-head">
        <h2>Recorded notes</h2>
        <button type="button" className="quiet-button" onClick={notes.reload}>
          Refresh
        </button>
      </div>

      {notes.loading && <LoadingState label="Loading notes…" />}
      {notes.error !== null && <ErrorState message={notes.error} onRetry={notes.reload} />}
      {!notes.loading && notes.error === null && (notes.data ?? []).length === 0 && (
        <EmptyState
          title="No notes yet"
          message="Notes are the analyst's own record of what was checked and concluded. Nothing has been written for this investigation."
          endpoint="GET /api/v1/cases/{id}/notes"
        />
      )}
      <ul className="note-list">
        {(notes.data ?? []).map((note) => (
          <li key={note.note_id} className="note">
            <p className="note__body">{note.body}</p>
            <p className="note__meta">
              {formatDateTime(note.created_at)}
              {note.author_id !== null && <> · {shortId(note.author_id, 8)}</>}
            </p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function CaseWorkspacePage() {
  const { caseId = '' } = useParams();
  const { snapshot } = useLive();
  const resource = useApi<CaseWorkspace>(
    caseId === '' ? null : `/api/v1/cases/${encodeURIComponent(caseId)}/workspace`,
  );
  // Hoisted out of the Assessment tab so switching to it costs no round trip:
  // the workspace is the main screen, so its hypotheses load with it.
  const hypotheses = useApi<CaseHypothesis[]>(
    caseId === '' ? null : `/api/v1/cases/${encodeURIComponent(caseId)}/hypotheses`,
  );
  const [tab, setTab] = useState<Tab>('overview');
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [live, setLive] = useState<CaseWorkspace | null>(null);

  useEffect(() => {
    if (snapshot?.server_time !== undefined) resource.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot?.server_time]);

  useEffect(() => {
    if (resource.data !== null) setLive(resource.data);
  }, [resource.data]);

  const data = live;
  const refresh = resource.reload;

  const assessment = data?.assessments[0];
  const confidence = assessment?.calibrated_confidence ?? assessment?.raw_score ?? 0;

  const { graphNodes, graphEdges, truncated } = useMemo(() => {
    if (data === null) return { graphNodes: [] as GraphNode[], graphEdges: [] as GraphEdge[], truncated: 0 };

    const actors = data.entities.filter((entity) => entity.type === 'actor');
    const others = data.entities.filter((entity) => entity.type !== 'actor');
    // Actors first so they occupy the leading ring positions.
    const ordered: WorkspaceEntity[] = [...actors, ...others];
    const visible = ordered.slice(0, GRAPH_NODE_LIMIT);
    const visibleIds = new Set(visible.map((entity) => entity.entity_id));

    const nodes: GraphNode[] = visible.map((entity) => ({
      id: entity.entity_id,
      label: entity.surface_form.slice(0, 18),
    }));

    const edges: GraphEdge[] = data.relationships
      .filter(
        (relationship) =>
          visibleIds.has(relationship.subject_entity_id) &&
          visibleIds.has(relationship.object_entity_id),
      )
      .slice(0, GRAPH_EDGE_LIMIT)
      .map((relationship) => ({
        source: relationship.subject_entity_id,
        target: relationship.object_entity_id,
        label: relationship.type,
        tone: relationship.confidence >= 0.5 ? 'ok' : 'danger',
      }));

    return { graphNodes: nodes, graphEdges: edges, truncated: ordered.length - visible.length };
  }, [data]);

  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const setSelectedEntity = useCallback((nodeId: string) => {
    setSelectedEntityId((current) => (current === nodeId ? null : nodeId));
  }, []);
  const selected =
    data === null || selectedEntityId === null
      ? null
      : (data.entities.find((entity) => entity.entity_id === selectedEntityId) ?? null);

  const evidenceColumns: ReadonlyArray<Column<CaseWorkspace['evidence'][number]>> = [
    {
      key: 'source',
      header: 'Source',
      render: (row) => (
        <>
          <b>{row.source_type}</b>
          <small className="table-sub">
            {metaTitle(row.metadata) ?? shortId(row.evidence_id, 12)}
          </small>
        </>
      ),
    },
    {
      key: 'observed',
      header: 'Observed',
      render: (row) => formatDateTime(row.observed_at ?? row.collected_at),
    },
    {
      key: 'reliability',
      header: 'Reliability',
      align: 'end',
      render: (row) => formatPercent(row.reliability),
    },
    {
      key: 'integrity',
      header: 'Integrity',
      render: (row) => <span className="mono">{shortId(row.sha256, 12)}</span>,
    },
  ];

  if (caseId === '') {
    return (
      <div className="page-stack">
        <EmptyState title="No case selected" message="Pick an investigation from the case list." />
      </div>
    );
  }

  if (resource.error !== null) {
    return (
      <div className="page-stack">
        <ErrorState message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (data === null) {
    return (
      <div className="page-stack">
        <LoadingState label="Loading investigation workspace…" />
      </div>
    );
  }

  const relationships: WorkspaceRelationship[] = data.relationships;

  return (
    <div className="page-stack workspace-page">
      <header className="workspace-head">
        <div>
          <div className="breadcrumbs">
            <Link to="/cases">Cases</Link>
            <span>›</span>
            <span>{data.case.name}</span>
          </div>
          <div className="title-line">
            <h1>{data.case.name}</h1>
            <Badge tone={STATUS_TONE[data.case.status]}>
              {data.case.status.replace('_', ' ')}
            </Badge>
            {data.case.sla_overdue && <Badge tone="danger">SLA breached</Badge>}
          </div>
          <p>{data.case.description ?? <span className="hint">No description</span>}</p>
          {data.case.tags.length > 0 && (
            <p className="tag-row">
              {data.case.tags.map((tag) => (
                <span className="tag" key={tag}>
                  {tag}
                </span>
              ))}
            </p>
          )}
        </div>
        <div className="workspace-actions">
          <span className="synced">
            <i /> Live synced
          </span>
          <a className="button" href={api.reportExportUrl(caseId, 'json')}>
            Export JSON
          </a>
          <a className="button button--dark" href={api.reportExportUrl(caseId, 'csv')}>
            Export CSV
          </a>
        </div>
      </header>

      <nav className="workspace-tabs" aria-label="Workspace sections">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={tab === item.id ? 'active' : ''}
            aria-current={tab === item.id ? 'page' : undefined}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'overview' && (
        <>
          <section className="workspace-signal">
            <div>
              <span className="eyebrow">Case signal</span>
              <h2>Evidence-backed intelligence picture</h2>
              <p>
                Derived from {data.counts.evidence} evidence records,{' '}
                {data.counts.entities} entities and {data.counts.relationships} observed
                relationships.
              </p>
            </div>
            <ScoreRing value={confidence} />
            <div className="signal-summary">
              <div>
                <b>{data.counts.evidence}</b>
                <span>evidence</span>
              </div>
              <div>
                <b>{data.counts.entities}</b>
                <span>entities</span>
              </div>
              <div>
                <b>{data.counts.relationships}</b>
                <span>links</span>
              </div>
            </div>
          </section>

          <TriageBar
            workspace={data.case}
            onPatched={(updated) => {
              setLive({ ...data, case: { ...data.case, ...updated } });
            }}
          />

          <section className="workspace-grid">
            <Panel
              title="Relationship field"
              actions={
                <button type="button" className="quiet-button" onClick={() => setTab('network')}>
                  Explore →
                </button>
              }
            >
              {graphNodes.length === 0 ? (
                <EmptyState
                  title="No entities"
                  message="No entities have been extracted into this investigation yet."
                />
              ) : (
                <div className="graph-canvas">
                  <GraphView
                    nodes={graphNodes}
                    edges={graphEdges}
                    label={`Relationship graph for ${data.case.name}`}
                    onSelectNode={() => setTab('network')}
                  />
                  <div className="graph-legend">
                    <span>
                      <i className="legend-dot legend-dot--actor" /> Actors
                    </span>
                    <span>
                      <i className="legend-dot" /> Other entities
                    </span>
                    <span>{graphEdges.length} relationships shown</span>
                  </div>
                </div>
              )}
            </Panel>

            <Panel title="Signal composition">
              {assessment === undefined ? (
                <EmptyState
                  title="No assessment"
                  message="No model assessment has been produced for this investigation."
                />
              ) : (
                <ScoreBars
                  label="Assessment signal weights"
                  rows={Object.entries(assessment.signals).map(([name, value]) => ({
                    label: name,
                    value,
                    tone: scoreTone(value),
                  }))}
                />
              )}
            </Panel>
          </section>

          <section className="workspace-grid workspace-grid--bottom">
            <Panel
              title="Intelligence activity"
              description="Immutable system audit trail."
              actions={<span className="surface-meta">seq {data.activity[0]?.seq ?? 0}</span>}
            >
              {data.activity.length === 0 ? (
                <EmptyState
                  title="No activity"
                  message="No audited events have been recorded for this investigation."
                />
              ) : (
                <div className="activity-list">
                  {data.activity.slice(0, 8).map((row) => (
                    <div className="activity-row" key={row.seq}>
                      <span className="activity-marker" />
                      <div>
                        <strong>{String(row.payload.message ?? row.action)}</strong>
                        <small>{formatDateTime(row.occurred_at)}</small>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Most connected entities">
              {data.entities.length === 0 ? (
                <EmptyState title="No entities" message="Nothing extracted yet." />
              ) : (
                <div className="entity-list">
                  {data.entities
                    .slice()
                    .sort((a, b) => b.confidence - a.confidence)
                    .slice(0, 7)
                    .map((entity, index) => (
                      <div key={entity.entity_id}>
                        <span className="entity-rank">{String(index + 1).padStart(2, '0')}</span>
                        <strong>{entity.surface_form}</strong>
                        <span>{formatPercent(entity.confidence)}</span>
                      </div>
                    ))}
                </div>
              )}
            </Panel>
          </section>
        </>
      )}

      {tab === 'evidence' && (
        <>
          <Panel
            title="Evidence ledger"
            description="Every record collected for this investigation."
            actions={
              <button type="button" className="btn btn--ghost btn--small" onClick={refresh}>
                Refresh
              </button>
            }
          >
            {openEvidence !== null && (
              <EvidenceDrawer
                evidenceId={openEvidence}
                onClose={() => setOpenEvidence(null)}
                onLoaded={() => undefined}
                onOpenEvidence={setOpenEvidence}
              />
            )}
            <DataTable
              caption="Evidence collected for this investigation"
              columns={[
                ...evidenceColumns,
                {
                  key: 'open',
                  header: '',
                  align: 'end' as const,
                  render: (row: CaseWorkspace['evidence'][number]) => (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setOpenEvidence(row.evidence_id)}
                    >
                      Open
                    </button>
                  ),
                },
              ]}
              rows={data.evidence}
              rowKey={(row) => row.evidence_id}
              empty={
                <EmptyState
                  title="No evidence"
                  message="Nothing has been collected into this investigation yet."
                  endpoint="GET /api/v1/cases/{id}/evidence"
                />
              }
            />
          </Panel>
          <Panel title="Ingest evidence" description="New records attach to this investigation.">
            <EvidenceForm caseId={caseId} onCreated={refresh} />
          </Panel>
        </>
      )}

      {tab === 'network' && (
        <Panel
          title="Network investigation"
          description={`${graphNodes.length} entities, ${graphEdges.length} relationships shown.`}
          actions={
            <Link className="quiet-button" to="/graph">
              Full graph →
            </Link>
          }
        >
          {graphNodes.length === 0 ? (
            <EmptyState
              title="No relationships"
              message="No entities have been extracted into this investigation yet."
            />
          ) : (
            <>
              {truncated > 0 && (
                <p className="caution">
                  {truncated} further entities are not drawn — the graph shows the{' '}
                  {GRAPH_NODE_LIMIT} most relevant and the first {GRAPH_EDGE_LIMIT} relationships.
                </p>
              )}
              <div className="graph-canvas graph-canvas--tall">
                <GraphView
                  nodes={graphNodes}
                  edges={graphEdges}
                  label={`Relationship graph for ${data.case.name}`}
                  onSelectNode={setSelectedEntity}
                />
                <div className="graph-legend">
                  <span>
                    <i className="legend-dot legend-dot--actor" /> Actors
                  </span>
                  <span>{relationships.length} relationships total</span>
                </div>
              </div>
              {selected !== null && (
                <dl className="kv">
                  <dt>Entity</dt>
                  <dd>{selected.surface_form}</dd>
                  <dt>Type</dt>
                  <dd>{selected.type}</dd>
                  <dt>Normalized</dt>
                  <dd className="mono">{selected.normalized_form}</dd>
                  <dt>Confidence</dt>
                  <dd>{formatPercent(selected.confidence)}</dd>
                  <dt>Relationships</dt>
                  <dd>
                    {relationships.filter(
                      (relationship) =>
                        relationship.subject_entity_id === selected.entity_id ||
                        relationship.object_entity_id === selected.entity_id,
                    ).length}
                  </dd>
                </dl>
              )}
            </>
          )}
        </Panel>
      )}

      {tab === 'timeline' && (
        <TimelinePanel workspace={data} onRefresh={refresh} />
      )}

      {tab === 'assessment' && (
        <AssessmentPanel
          workspace={data}
          hypotheses={hypotheses}
          onSelectEvidence={(evidenceId) => {
            setOpenEvidence(evidenceId);
            setTab('evidence');
          }}
        />
      )}

      {tab === 'notes' && <NotesTab caseId={caseId} />}
    </div>
  );
}
