import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api, apiUrl, authHeaders, formatApiError } from '../api/client';
import type {
  CaseHypothesis,
  CaseMetrics,
  CaseQueueEntry,
  CaseTimeline,
  CaseStatus,
  CaseWorkspace,
  Evidence,
  SignalBand,
  SlaState,
  TeamMember,
} from '../api/types';
import { useApi } from '../hooks/useApi';
import { useLive } from '../hooks/useLive';
import { formatDateTime, formatPercent, shortId } from '../lib/format';
import { Badge } from '../components/Badge';
import type { Tone } from '../components/Badge';
import { EvidenceDrawer } from '../components/EvidenceDrawer';
import { EvidenceForm } from '../components/EvidenceForm';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { usePublishAgentContext } from '../components/agent-context';
import type { WorkspaceView } from '../components/agent-context';
import { AssessmentPanel } from '../components/workspace/AssessmentPanel';
import { EvidenceLedger } from '../components/workspace/EvidenceLedger';
import { HypothesisBoard } from '../components/workspace/HypothesisBoard';
import { NetworkGraph } from '../components/workspace/NetworkGraph';
import { SignalMatrix } from '../components/workspace/SignalMatrix';
import { TimelineLanes } from '../components/workspace/TimelineLanes';

const TABS: ReadonlyArray<{ id: WorkspaceView; label: string }> = [
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

const SEVERITY_TONE: Record<string, Tone> = {
  informational: 'neutral',
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
};

const PRIORITY_TONE: Record<string, Tone> = {
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
};

const SLA_TONE: Record<SlaState, Tone> = {
  breached: 'danger',
  at_risk: 'warn',
  ok: 'ok',
  none: 'neutral',
};

const METRICS_ENDPOINT = 'GET /api/v1/cases/{id}/metrics';
const SIGNALS_ENDPOINT = 'GET /api/v1/cases/{id}/signals';
const HYPOTHESES_ENDPOINT = 'GET /api/v1/cases/{id}/hypotheses';

/**
 * The workspace case record carries `sla_due_at` and `sla_overdue` but not the
 * register's `sla_state` column, so the state an analyst reads in the header is
 * derived from those two rather than invented: a closed case has no live
 * deadline, a case past its deadline is breached, and anything else is on track.
 */
function slaStateFor(record: CaseWorkspace['case']): SlaState {
  if (record.closed_at !== null || record.status === 'closed' || record.status === 'archived') {
    return record.sla_due_at === null ? 'none' : 'ok';
  }
  if (record.sla_due_at === null) return 'none';
  if (record.sla_overdue) return 'breached';
  return 'ok';
}

const SLA_TEXT: Record<SlaState, string> = {
  breached: 'SLA breached',
  at_risk: 'SLA at risk',
  ok: 'SLA on track',
  none: 'no SLA deadline',
};

async function downloadReport(url: string, filename: string): Promise<void> {
  const response = await fetch(url, { headers: authHeaders() });
  if (!response.ok) throw new Error(`Export failed (${response.status})`);
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

function isWorkspaceView(value: string | null): value is WorkspaceView {
  return value !== null && TABS.some((tab) => tab.id === value);
}

function MetricStrip({ metrics }: { metrics: CaseMetrics | null }) {
  if (metrics === null) return <LoadingState label="Reading case metrics…" />;  const cells: ReadonlyArray<{ label: string; value: string; sub?: string; tone?: string }> = [
    { label: 'Evidence', value: String(metrics.evidence), sub: 'ledger records' },
    { label: 'Entities', value: String(metrics.entities), sub: 'extracted objects' },
    { label: 'Links', value: String(metrics.links), sub: 'observed relationships' },
    { label: 'Sources', value: String(metrics.sources), sub: 'distinct sources' },
    {
      label: 'Attribution',
      value: metrics.attribution === null ? 'unscored' : formatPercent(metrics.attribution),
      sub: 'highest calibrated confidence',
    },
    {
      label: 'Contradictions',
      value: String(metrics.contradictions),
      sub: 'cited against hypotheses',
      tone: metrics.contradictions > 0 ? 'is-danger' : undefined,
    },
    { label: 'Hypotheses', value: String(metrics.hypotheses), sub: 'distinct candidates' },
    {
      label: 'Independent sources',
      value: String(metrics.independent_sources),
      sub: 'independence groups',
      tone: 'is-ok',
    },
  ];
  return (
    <dl className="inv-metrics">
      {cells.map((cell) => (
        <div className={cell.tone === undefined ? 'inv-metric' : `inv-metric ${cell.tone}`} key={cell.label}>
          <dt>{cell.label}</dt>
          <dd>{cell.value}</dd>
          {cell.sub !== undefined && <small>{cell.sub}</small>}
        </div>
      ))}
    </dl>
  );
}

function InvestigativeBrief({
  caseName,
  metrics,
  hypotheses,
  onOpenAssessment,
}: {
  caseName: string;
  metrics: CaseMetrics | null;
  hypotheses: readonly CaseHypothesis[];
  onOpenAssessment: () => void;
}) {
  const scored = useMemo(
    () =>
      hypotheses
        .filter((row) => row.calibrated_confidence !== null || row.raw_score !== null)
        .sort((left, right) => {
          const a = left.calibrated_confidence ?? left.raw_score ?? 0;
          const b = right.calibrated_confidence ?? right.raw_score ?? 0;
          return b - a;
        }),
    [hypotheses],
  );
  const lead = scored[0];
  const gaps = useMemo(() => {
    const seen = new Set<string>();
    for (const row of hypotheses) for (const note of row.missing_evidence) seen.add(note);
    return [...seen];
  }, [hypotheses]);
  const contradictions = metrics?.contradictions ?? 0;
  const cited = hypotheses.reduce(
    (total, row) => total + row.supporting_evidence_ids.length + row.contradictory_evidence_ids.length,
    0,
  );

  return (
    <div className="inv-brief">
      <div className="inv-brief__copy">
        <span className="eyebrow">Investigative brief</span>
        <h3>Where this investigation stands</h3>
        <p>
          {lead === undefined ? (
            <>
              No hypothesis for {caseName} has been scored yet, so there is no leading explanation
              to report. The evidence below is the whole of the current picture.
            </>
          ) : (
            <>
              The leading hypothesis is{' '}
              <strong>
                {shortId(lead.subject_entity_id, 8)} → {shortId(lead.object_entity_id, 8)}
              </strong>{' '}
              ({lead.kind}, status {lead.status}) at{' '}
              {formatPercent(lead.calibrated_confidence ?? lead.raw_score ?? 0)}
              {lead.calibrated_confidence === null ? ' on the uncalibrated raw score' : ' calibrated'}. It rests on{' '}
              {lead.supporting_evidence_ids.length} supporting record
              {lead.supporting_evidence_ids.length === 1 ? '' : 's'} drawn from{' '}
              {lead.independent_source_groups} independent source group
              {lead.independent_source_groups === 1 ? '' : 's'}, and{' '}
              {lead.contradictory_evidence_ids.length} record
              {lead.contradictory_evidence_ids.length === 1 ? '' : 's'} point against it.
            </>
          )}
        </p>
        {gaps.length > 0 && (
          <>
            <p className="eyebrow" style={{ marginTop: 18 }}>
              Evidence analysts flagged as missing
            </p>
            <ul className="inv-brief__gaps">
              {gaps.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </>
        )}
        <p style={{ marginTop: 16 }}>
          <button type="button" className="link-button" onClick={onOpenAssessment}>
            Compare every hypothesis on the Assessment tab →
          </button>
        </p>
      </div>
      <dl className="inv-brief__side">
        <dt>Leading hypothesis</dt>
        <dd>{lead === undefined ? <span className="hint">none scored</span> : shortId(lead.hypothesis_id, 12)}</dd>
        <dt>Confidence</dt>
        <dd>
          {lead === undefined ? (
            '—'
          ) : (
            <Badge tone={lead.status === 'accepted' ? 'ok' : 'neutral'}>
              {formatPercent(lead.calibrated_confidence ?? lead.raw_score ?? 0)}
            </Badge>
          )}
        </dd>
        <dt>Outstanding contradictions</dt>
        <dd>
          <Badge tone={contradictions > 0 ? 'danger' : 'ok'}>{String(contradictions)}</Badge>
        </dd>
        <dt>Records cited by hypotheses</dt>
        <dd>{cited}</dd>
        <dt>Competing hypotheses</dt>
        <dd>{hypotheses.length}</dd>
      </dl>
    </div>
  );
}

export function CaseWorkspacePage() {
  const { caseId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { snapshot } = useLive();
  const tabParam = params.get('tab');
  const tab: WorkspaceView = isWorkspaceView(tabParam) ? tabParam : 'overview';

  const workspace = useApi<CaseWorkspace>(
    caseId === '' ? null : apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/workspace`),
  );
  const metrics = useApi<CaseMetrics>(
    caseId === '' ? null : apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/metrics`),
  );
  const signals = useApi<SignalBand[]>(
    caseId === '' ? null : apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/signals`),
  );
  const timeline = useApi<CaseTimeline>(
    caseId === '' ? null : apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/timeline`),
  );
  const graphSummary = useApi<CaseQueueEntry[]>(apiUrl('/v1/dashboard/cases'));
  const hypotheses = useApi<CaseHypothesis[]>(
    caseId === '' ? null : apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/hypotheses`),
  );
  const team = useApi<{ members: TeamMember[] }>(apiUrl('/v1/admin/team'));

  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Array<{ note_id: string; body: string; created_at: string | null }>>([]);
  const [exportError, setExportError] = useState<string | null>(null);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const setTab = useCallback(
    (next: WorkspaceView) => {
      const search = new URLSearchParams(params);
      if (next === 'overview') search.delete('tab');
      else search.set('tab', next);
      setParams(search, { replace: false });
    },
    [params, setParams],
  );

  const data = workspace.data;
  usePublishAgentContext(data === null ? null : { place: data.case.name, view: tab });

  useEffect(() => {
    if (snapshot?.server_time !== undefined) workspace.reload();
    // Only the server clock should trigger a refresh; `workspace` is a new
    // object identity on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot?.server_time]);

  useEffect(() => {
    if (caseId === '') return;
    let active = true;
    void api
      .listNotes(caseId)
      .then((rows) => {
        if (active) setNotes(rows);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [caseId]);

  if (caseId === '') {
    return (
      <div className="page-stack inv-page">
        <EmptyState title="No case selected" message="Pick an investigation from the register." />
      </div>
    );
  }
  if (workspace.error !== null) {
    return (
      <div className="page-stack inv-page">
        <ErrorState message={workspace.error} onRetry={workspace.reload} />
      </div>
    );
  }
  if (data === null) {
    return (
      <div className="page-stack inv-page">
        <LoadingState label="Loading investigation workspace…" />
      </div>
    );
  }

  const record = data.case;
  const sla = slaStateFor(record);
  const hypothesisRows = hypotheses.data ?? [];
  const caseSummary = (graphSummary.data ?? []).find((entry) => entry.case_id === caseId) ?? null;

  const onTabKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = TABS.length - 1;
    let next: number | null = null;
    if (event.key === 'ArrowRight') next = index === last ? 0 : index + 1;
    else if (event.key === 'ArrowLeft') next = index === 0 ? last : index - 1;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = last;
    if (next === null) return;
    event.preventDefault();
    setTab(TABS[next]?.id ?? 'overview');
    tabRefs.current[next]?.focus();
  };

  const saveNote = async () => {
    const body = note.trim();
    if (body === '') return;
    setNoteBusy(true);
    setNoteError(null);
    try {
      const created = await api.createNote(caseId, { body });
      setNotes((current) => [created, ...current]);
      setNote('');
    } catch (err: unknown) {
      setNoteError(formatApiError(err));
    } finally {
      setNoteBusy(false);
    }
  };

  const assign = async (memberId: string) => {
    setAssignBusy(true);
    setAssignError(null);
    try {
      await api.updateCase(caseId, { assigned_to: memberId === '' ? null : memberId });
      workspace.reload();
    } catch (err: unknown) {
      setAssignError(formatApiError(err));
    } finally {
      setAssignBusy(false);
    }
  };

  const runExport = async (format: 'json' | 'csv' | 'stix' | 'pdf') => {
    setExportError(null);
    const name = `${record.name.replace(/\W+/g, '-').toLowerCase() || 'investigation'}.${format}`;
    try {
      await downloadReport(api.reportExportUrl(caseId, format), name);
    } catch (err: unknown) {
      setExportError(err instanceof Error ? err.message : 'Export failed.');
    }
  };

  const openEvidenceFromTab = (evidenceId: string) => {
    setOpenEvidence(evidenceId);
  };

  return (
    <div className="page-stack inv-page">
      <header className="inv-ws__head">
        <div>
          <nav className="inv-ws__crumbs" aria-label="Breadcrumb">
            <Link to="/cases">Register</Link>
            <span aria-hidden="true">›</span>
            <span>{record.name}</span>
          </nav>
          <div className="inv-ws__title">
            <span className="inv-ws__code" title={caseId}>
              {shortId(caseId, 8).toUpperCase()}
            </span>
            <h1>{record.name}</h1>
          </div>
          <div className="inv-ws__meta">
            <Badge tone={STATUS_TONE[record.status]}>{record.status.replace('_', ' ')}</Badge>
            <Badge tone={PRIORITY_TONE[record.priority] ?? 'neutral'} title="Triage priority">
              priority: {record.priority}
            </Badge>
            <Badge tone={SEVERITY_TONE[record.severity] ?? 'neutral'} title="Impact severity">
              severity: {record.severity}
            </Badge>
            <Badge tone={SLA_TONE[sla]} title={record.sla_due_at === null ? undefined : `due ${formatDateTime(record.sla_due_at)}`}>
              {SLA_TEXT[sla]}
            </Badge>
            {record.assigned_to === null ? (
              <Badge tone="warn">unassigned</Badge>
            ) : (
              <Badge tone="neutral" title={record.assigned_to}>
                owner {shortId(record.assigned_to, 8)}
              </Badge>
            )}
            {record.tags.map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
          </div>
          <p className="inv-ws__desc">
            {record.description ?? 'No case description recorded.'}
            {record.sla_due_at !== null && (
              <>
                {' '}
                Deadline {formatDateTime(record.sla_due_at)}.
              </>
            )}
          </p>
        </div>

        <div className="inv-ws__actions">
          <details className="inv-menu">
            <summary className="btn btn--ghost">Export ▾</summary>
            <div className="inv-menu__list">
              {(['json', 'csv', 'stix', 'pdf'] as const).map((format) => (
                <button key={format} type="button" onClick={() => void runExport(format)}>
                  {`Export ${format.toUpperCase()}`}
                  <small>GET /reports/export?format={format}</small>
                </button>
              ))}
            </div>
          </details>

          <label className="sr-only" htmlFor="inv-assign">
            Assign an owner
          </label>
          <select
            id="inv-assign"
            className="inv-select"
            value={record.assigned_to ?? ''}
            disabled={assignBusy}
            onChange={(event) => void assign(event.target.value)}
          >
            <option value="">unassigned</option>
            {(team.data?.members ?? [])
              .filter((member) => member.is_active)
              .map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {`${member.display_name} (${member.assigned_cases} case${member.assigned_cases === 1 ? '' : 's'})`}
                </option>
              ))}
          </select>

          <details className="inv-menu">
            <summary className="btn btn--ghost">More ▾</summary>
            <div className="inv-menu__list">
              <a href={api.reportPreviewUrl(caseId)} target="_blank" rel="noreferrer noopener">
                Open report preview
                <small>GET /reports/preview</small>
              </a>
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard?.writeText(window.location.href);
                }}
              >
                Copy link to this view
                <small>includes the active tab</small>
              </button>
              <button
                type="button"
                onClick={() => {
                  workspace.reload();
                  metrics.reload();
                  hypotheses.reload();
                  signals.reload();
                }}
              >
                Refresh all panels
                <small>re-reads every case endpoint</small>
              </button>
            </div>
          </details>
        </div>
      </header>

      {assignError !== null && <ErrorState message={assignError} />}
      {exportError !== null && <p className="status status--error">{exportError}</p>}

      <div className="inv-tabs" role="tablist" aria-label="Investigation views">
        {TABS.map((item, index) => (
          <button
            key={item.id}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`inv-tab-${item.id}`}
            className="inv-tabs__tab"
            aria-selected={tab === item.id}
            aria-controls={`inv-panel-${item.id}`}
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => setTab(item.id)}
            onKeyDown={(event) => onTabKeyDown(event, index)}
          >
            {item.label}
            {item.id === 'evidence' && data.counts.evidence !== undefined && (
              <small>{data.counts.evidence}</small>
            )}
            {item.id === 'network' && data.counts.relationships !== undefined && (
              <small>{data.counts.relationships}</small>
            )}
            {item.id === 'notes' && <small>{notes.length}</small>}
          </button>
        ))}
      </div>

      <section
        role="tabpanel"
        id={`inv-panel-${tab}`}
        aria-labelledby={`inv-tab-${tab}`}
        className="inv-tabpanel"
        tabIndex={0}
      >
        {tab === 'overview' && (
          <>
            {metrics.error !== null ? (
              <ErrorState
                message={`Case metrics are unavailable: ${metrics.error}`}
                onRetry={metrics.reload}
              />
            ) : (
              <MetricStrip metrics={metrics.data} />
            )}
            <InvestigativeBrief
              caseName={record.name}
              metrics={metrics.data}
              hypotheses={hypothesisRows}
              onOpenAssessment={() => setTab('assessment')}
            />
            <p className="hint" style={{ marginTop: 8 }}>
              {`Metrics: ${METRICS_ENDPOINT} · signals: ${SIGNALS_ENDPOINT} · hypotheses: ${HYPOTHESES_ENDPOINT}`}
            </p>
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel__head">
                <div className="panel__headings">
                  <h2 className="panel__title">Case signal matrix</h2>
                  <p className="panel__desc">
                    Support, contradiction and freshness per modality. Each cell shows the band and
                    the number behind it — a band on its own is not evidence.
                  </p>
                </div>
                <div className="panel__actions">
                  <button type="button" className="btn btn--ghost btn--small" onClick={signals.reload}>
                    Refresh
                  </button>
                </div>
              </div>
              <div className="panel__body">
                <SignalMatrix signals={signals} />
              </div>
            </div>
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel__head">
                <div className="panel__headings">
                  <h2 className="panel__title">Case record</h2>
                  <p className="panel__desc">
                    Triage metadata as the API holds it, including the register&apos;s view of this
                    case.
                  </p>
                </div>
              </div>
              <div className="panel__body">
                <dl className="kv">
                  <dt>Case ID</dt>
                  <dd className="mono">{caseId}</dd>
                  <dt>Opened</dt>
                  <dd>{formatDateTime(record.created_at)}</dd>
                  <dt>Last updated</dt>
                  <dd>{formatDateTime(record.updated_at)}</dd>
                  <dt>Last activity</dt>
                  <dd>{formatDateTime(caseSummary?.last_activity ?? null)}</dd>
                  <dt>Queue score</dt>
                  <dd>
                    {caseSummary === null
                      ? 'not present in the register'
                      : `${caseSummary.queue_score.toFixed(1)} — ${caseSummary.queue_reason}`}
                  </dd>
                  <dt>Why prioritised</dt>
                  <dd>
                    {caseSummary === null || caseSummary.reasons.length === 0 ? (
                      <span className="hint">no priority reasons reported</span>
                    ) : (
                      <ul className="plain-list">
                        {caseSummary.reasons.map((reason) => (
                          <li key={reason.key}>
                            {reason.label} <span className="mono">({reason.weight.toFixed(1)})</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </dd>
                  <dt>Closed</dt>
                  <dd>
                    {record.closed_at === null ? (
                      <span className="hint">open</span>
                    ) : (
                      <>
                        {formatDateTime(record.closed_at)}
                        {record.closure_reason !== null && ` — ${record.closure_reason}`}
                      </>
                    )}
                  </dd>
                </dl>
              </div>
            </div>
          </>
        )}

        {tab === 'evidence' && (
          <>
            <EvidenceLedger
              caseId={caseId}
              known={data.evidence}
              onOpenEvidence={openEvidenceFromTab}
            />
            <div className="panel" style={{ marginTop: 16 }}>
              <div className="panel__head">
                <div className="panel__headings">
                  <h2 className="panel__title">Attach evidence</h2>
                  <p className="panel__desc">
                    Record a new artifact against this case. The hash and collector fields are what
                    make the record admissible later.
                  </p>
                </div>
              </div>
              <div className="panel__body">
                <EvidenceForm
                  caseId={caseId}
                  onCreated={() => {
                    workspace.reload();
                    metrics.reload();
                  }}
                />
              </div>
            </div>
          </>
        )}

        {tab === 'network' && <NetworkGraph caseId={caseId} caseName={record.name} />}

        {tab === 'timeline' && (
          <TimelineLanes timeline={timeline} onSelectEvidence={openEvidenceFromTab} />
        )}

        {tab === 'assessment' && (
          <>
            <HypothesisBoard hypotheses={hypotheses} onSelectEvidence={openEvidenceFromTab} />
            <div style={{ marginTop: 16 }}>
              <AssessmentPanel
                workspace={data}
                hypotheses={hypotheses}
                onSelectEvidence={openEvidenceFromTab}
              />
            </div>
            {hypotheses.error !== null && (
              <p className="hint" style={{ marginTop: 10 }}>
                {`Hypotheses could not be read from ${HYPOTHESES_ENDPOINT}.`}
              </p>
            )}
          </>
        )}

        {tab === 'notes' && (
          <div className="panel">
            <div className="panel__head">
              <div className="panel__headings">
                <h2 className="panel__title">Analyst notes</h2>
                <p className="panel__desc">
                  The human record: observations, contradictions flagged, leads and the next
                  verification step.
                </p>
              </div>
              <div className="panel__actions">
                <span className="surface-meta">
                  {notes.length} note{notes.length === 1 ? '' : 's'}
                </span>
              </div>
            </div>
            <div className="panel__body">
              <div className="field">
                <label htmlFor="inv-note-body">New note</label>
                <textarea
                  id="inv-note-body"
                  rows={3}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Record an observation, contradiction, lead or next verification step…"
                />
              </div>
              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={noteBusy || note.trim() === ''}
                  onClick={() => void saveNote()}
                >
                  {noteBusy ? 'Saving…' : 'Add note'}
                </button>
              </div>
              {noteError !== null && <p className="status status--error">{noteError}</p>}
              <div className="inv-notes" style={{ marginTop: 14 }}>
                {notes.length === 0 && (
                  <EmptyState
                    title="No notes yet"
                    message="Nothing has been recorded against this investigation. The first note should say what the next verification step is."
                  />
                )}
                {notes.map((row) => (
                  <article className="inv-note" key={row.note_id}>
                    <p>{row.body}</p>
                    <small>{formatDateTime(row.created_at)}</small>
                  </article>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      {openEvidence !== null && (
        <EvidenceDrawer
          evidenceId={openEvidence}
          onClose={() => setOpenEvidence(null)}
          onLoaded={(_record: Evidence) => undefined}
          onOpenEvidence={setOpenEvidence}
        />
      )}
    </div>
  );
}
