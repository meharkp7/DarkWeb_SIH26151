import { Link } from 'react-router-dom';
import { useLive } from '../hooks/useLive';
import { useApi } from '../hooks/useApi';
import type { CaseSummary, LiveActivity } from '../api/types';

function Metric({ value, label, delta, tone='' }: { value:number; label:string; delta:string; tone?:string }) {
  return <div className={`metric ${tone}`}><div className="metric-value">{value.toLocaleString()}</div><div className="metric-label">{label}</div><div className="metric-delta">↗ {delta}</div></div>;
}
function Activity({ rows }: { rows: LiveActivity[] }) {
  return <div className="activity-list">{rows.slice(0,8).map((item) => <div className="activity-row" key={item.seq}><span className={`activity-marker ${item.action.includes('critical') ? 'critical' : ''}`} /><div><strong>{String(item.payload.message ?? item.action.replaceAll('.', ' '))}</strong><small>{item.case_id ? 'Case-linked intelligence' : 'Platform event'} · {new Date(item.occurred_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</small></div><span className="activity-kind">{item.action.split('.')[0]}</span></div>)}</div>;
}
function GlobalMap({ activity }: { activity: LiveActivity[] }) {
  const points = [[15,37],[27,28],[39,44],[53,23],[63,38],[73,28],[83,46],[48,66],[29,67],[67,70]];
  return <div className="world-panel"><div className="world-grid" /><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Synthetic global activity map"><path d="M4 48 C 22 20, 35 30, 50 42 S 74 66, 96 37"/><path d="M10 74 C 30 50, 44 63, 60 50 S 80 28, 94 63"/>{points.map(([x,y],i)=><g key={i}><circle cx={x} cy={y} r={i<activity.length ? 1.2 : .7} className={i%4===0?'map-node map-node--hot':'map-node'} /><circle cx={x} cy={y} r="3" className="map-ring" /></g>)}</svg><div className="map-caption"><span>GLOBAL INTELLIGENCE ACTIVITY</span><b>{activity.length} recent signals</b></div></div>;
}
export function CommandCenterPage(){
  const { snapshot, connected } = useLive();
  const { data: cases } = useApi<CaseSummary[]>(apiUrlCases());
  const data = snapshot;
  const caseRows = cases ?? data?.case_summaries ?? [];
  return <div className="page-stack">
    <header className="hero-head"><div><span className="eyebrow">Intelligence operations center</span><h1>Good evening, Analyst.</h1><p>Live intelligence across your authorized investigation workspace.</p></div><div className="hero-status"><span className={connected?'live-dot live-dot--on':'live-dot'} />{connected?'LIVE FEED':'OFFLINE'}<small>{data ? new Date(data.server_time).toLocaleString() : 'Waiting for API'}</small></div></header>
    <section className="metric-grid"><Metric value={data?.counts.cases ?? 0} label="Active investigations" delta="live" /><Metric value={data?.counts.evidence ?? 0} label="Evidence records" delta="streaming" tone="metric-blue" /><Metric value={data?.counts.relationships ?? 0} label="Network links" delta="derived" tone="metric-violet" /><Metric value={data?.critical_alerts ?? 0} label="Critical alerts" delta="attention" tone="metric-red" /></section>
    <section className="command-grid"><GlobalMap activity={data?.activity ?? []}/><div className="surface activity-surface"><div className="surface-head"><div><span className="eyebrow">Live intelligence</span><h2>Recent activity</h2></div><Link to="/watch">View all →</Link></div><Activity rows={data?.activity ?? []}/></div></section>
    <section className="section-head"><div><span className="eyebrow">Operations</span><h2>Active investigations</h2></div><Link className="text-link" to="/cases">Open cases →</Link></section>
    <section className="case-strip">{caseRows.slice(0,4).map((item)=><Link to={`/cases/${item.case_id}`} className="case-card" key={item.case_id}><div className="case-card__top"><span className="status-dot" />{item.status.replace('_',' ')}</div><h3>{item.name}</h3><p>{item.description ?? 'Authorized intelligence investigation.'}</p><div className="case-card__stats"><span>{item.counts.evidence} evidence</span><span>{item.counts.entities} entities</span><span>{item.counts.relationships} links</span></div></Link>)}</section>
  </div>;
}
function apiUrlCases(){ return '/api/v1/dashboard/cases'; }
