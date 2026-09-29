import { Link } from 'react-router-dom';
import { useLive } from '../hooks/useLive';
import { useApi } from '../hooks/useApi';
import type { CaseSummary, LiveActivity } from '../api/types';

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
}

function Metric({ value, label, detail, tone = '' }: { value: number | string; label: string; detail: string; tone?: string }) {
  return <article className={`command-metric ${tone}`}><span>{label}</span><strong>{typeof value === 'number' ? value.toLocaleString() : value}</strong><small>{detail}</small></article>;
}

function queueScore(item: CaseSummary): number {
  if (item.queue_score) return item.queue_score;
  const priority = { critical: 100, high: 78, medium: 52, low: 28 }[item.priority] ?? 40;
  const severity = { critical: 24, high: 18, medium: 10, low: 5, informational: 0 }[item.severity] ?? 5;
  return Math.min(100, priority + severity + (item.sla_overdue ? 18 : 0));
}

function QueueRow({ item }: { item: CaseSummary }) {
  const score = queueScore(item);
  return <Link className="priority-row" to={`/cases/${item.case_id}`}>
    <div className="priority-index"><span>{String(score).padStart(2, '0')}</span><i className={`priority-dot priority-dot--${item.priority}`} /></div>
    <div className="priority-case"><strong>{item.name}</strong><small>{item.case_id.slice(0, 8).toUpperCase()} · {item.queue_reason ?? `${item.priority} priority`}</small></div>
    <div className="priority-volume"><b>{item.counts.evidence.toLocaleString()}</b><span>evidence</span></div>
    <div className="priority-volume"><b>{item.counts.relationships.toLocaleString()}</b><span>links</span></div>
    <div className="priority-status"><span>{item.sla_overdue ? 'SLA EXCEPTION' : item.status.replace('_', ' ').toUpperCase()}</span><small>{item.severity}</small></div>
    <span className="priority-arrow">→</span>
  </Link>;
}

function Posture({ cases, criticalAlerts }: { cases: CaseSummary[]; criticalAlerts: number }) {
  const overdue = cases.filter((item) => item.sla_overdue).length;
  const critical = cases.filter((item) => item.priority === 'critical').length;
  const high = cases.filter((item) => item.priority === 'high').length;
  const unassigned = cases.filter((item) => item.assigned_to === null).length;
  return <aside className="command-posture">
    <div className="command-section-head"><div><span className="eyebrow">Command posture</span><h2>Current operating picture</h2></div><span className="posture-live"><i /> LIVE</span></div>
    <div className="posture-score"><div><small>QUEUE PRESSURE</small><strong>{Math.min(99, critical * 18 + high * 7 + overdue * 14 + criticalAlerts)}</strong></div><span>attention<br />index</span></div>
    <div className="posture-grid">
      <div><span>Critical queue</span><b>{critical}</b><small>immediate review</small></div>
      <div><span>High priority</span><b>{high}</b><small>active analysis</small></div>
      <div><span>SLA exceptions</span><b>{overdue}</b><small>deadline breach</small></div>
      <div><span>Unassigned</span><b>{unassigned}</b><small>ownership needed</small></div>
    </div>
    <div className="posture-rule"><span>OPERATING DIRECTIVE</span><p>Resolve evidence gaps and contradictory signals before increasing attribution confidence.</p></div>
    <Link to="/threat-watch" className="posture-action">Open threat watch <span>↗</span></Link>
  </aside>;
}

function Activity({ rows }: { rows: LiveActivity[] }) {
  return <div className="command-activity">{rows.slice(0, 7).map((item) => <Link key={item.seq} to={item.case_id ? `/cases/${item.case_id}` : '/threat-watch'} className="command-activity-row">
    <span className="activity-time">{new Date(item.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span><i className={item.action.includes('critical') ? 'critical' : ''} />
    <div><strong>{String(item.payload.message ?? item.action.replaceAll('.', ' '))}</strong><small>{item.case_id ? `CASE ${item.case_id.slice(0, 8).toUpperCase()}` : 'PLATFORM'} · #{item.seq}</small></div>
  </Link>)}</div>;
}

export function CommandCenterPage() {
  const { snapshot, connected } = useLive();
  const { data: cases } = useApi<CaseSummary[]>('/api/v1/dashboard/cases');
  const rows = [...(cases ?? snapshot?.case_summaries ?? [])].sort((a, b) => queueScore(b) - queueScore(a));
  const active = rows.filter((item) => item.status === 'open' || item.status === 'active');
  const overdue = rows.filter((item) => item.sla_overdue).length;
  const critical = rows.filter((item) => item.priority === 'critical').length;
  const activity = snapshot?.activity ?? [];

  return <div className="page-stack command-center-enterprise">
    <header className="command-header">
      <div><span className="eyebrow">AEGIS / intelligence operations</span><h1>{greeting()}, <em>Analyst.</em></h1><p>Operational command view for active investigations, evidence movement, analytical pressure and unresolved attribution work.</p></div>
      <div className="command-header-right"><span className={connected ? 'live-chip is-live' : 'live-chip'}><i />{connected ? 'LIVE SYNCHRONIZED' : 'RECONNECTING'}</span><small>{snapshot ? new Date(snapshot.server_time).toLocaleString() : 'Awaiting telemetry'}</small><Link to="/cases" className="button button--dark">Investigations ↗</Link></div>
    </header>

    <section className="command-metrics">
      <Metric value={active.length} label="Active investigations" detail={`${rows.length} registered cases`} />
      <Metric value={snapshot?.counts.evidence ?? 0} label="Evidence ledger" detail="persisted observations" tone="blue" />
      <Metric value={snapshot?.counts.entities ?? 0} label="Tracked entities" detail="resolved case entities" tone="violet" />
      <Metric value={snapshot?.counts.relationships ?? 0} label="Relationship links" detail="observed associations" tone="green" />
      <Metric value={snapshot?.counts.assessments ?? 0} label="Assessments" detail="model + analyst outputs" tone="amber" />
      <Metric value={overdue} label="SLA exceptions" detail={`${critical} critical investigations`} tone="red" />
    </section>

    <section className="command-main-grid">
      <div className="command-panel priority-panel">
        <div className="command-section-head"><div><span className="eyebrow">Analyst triage</span><h2>Prioritization queue</h2></div><Link to="/cases">View register ↗</Link></div>
        <div className="priority-table-head"><span>SCORE</span><span>INVESTIGATION</span><span>EVIDENCE</span><span>LINKS</span><span>POSTURE</span><span /></div>
        {rows.slice(0, 7).map((item) => <QueueRow key={item.case_id} item={item} />)}
        {rows.length === 0 && <div className="command-empty"><strong>No operational data</strong><span>Run the synthetic demonstration seed to populate the command picture.</span></div>}
      </div>
      <Posture cases={rows} criticalAlerts={snapshot?.critical_alerts ?? 0} />
    </section>

    <section className="command-bottom-grid">
      <div className="command-panel evidence-panel"><div className="command-section-head"><div><span className="eyebrow">Evidence movement</span><h2>Operational activity ledger</h2></div><Link to="/threat-watch">Live stream ↗</Link></div><Activity rows={activity} /></div>
      <div className="command-panel signal-panel"><div className="command-section-head"><div><span className="eyebrow">Analytical chain</span><h2>Evidence to assessment</h2></div></div><div className="signal-chain"><div><span>01</span><b>Evidence</b><small>{(snapshot?.counts.evidence ?? 0).toLocaleString()} records</small></div><i>→</i><div><span>02</span><b>Entities</b><small>{(snapshot?.counts.entities ?? 0).toLocaleString()} resolved</small></div><i>→</i><div><span>03</span><b>Relationships</b><small>{(snapshot?.counts.relationships ?? 0).toLocaleString()} links</small></div><i>→</i><div><span>04</span><b>Assessment</b><small>{(snapshot?.counts.assessments ?? 0).toLocaleString()} outputs</small></div></div><div className="signal-note"><strong>Analyst rule</strong><p>Attribution confidence remains bounded by evidence quality, independence and unresolved contradiction. Every case workspace exposes the underlying chain.</p></div></div>
    </section>
  </div>;
}
