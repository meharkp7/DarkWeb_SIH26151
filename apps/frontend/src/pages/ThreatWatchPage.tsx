import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useLive } from '../hooks/useLive';
import type { LiveActivity } from '../api/types';

type Filter = 'all' | 'critical' | 'relationship' | 'evidence';

function severity(item: LiveActivity) {
  if (item.action.includes('critical')) return 'critical';
  if (item.action.includes('relationship')) return 'elevated';
  return 'normal';
}

function label(item: LiveActivity) {
  return String(item.payload.message ?? item.action.replaceAll('.', ' '));
}

export function ThreatWatchPage() {
  const { snapshot, connected } = useLive();
  const [filter, setFilter] = useState<Filter>('all');
  const rows = snapshot?.activity ?? [];

  const filtered = useMemo(() => rows.filter((item) => {
    if (filter === 'all') return true;
    if (filter === 'critical') return severity(item) === 'critical';
    return item.action.startsWith(`${filter}.`);
  }), [rows, filter]);

  const critical = rows.filter((item) => severity(item) === 'critical').length;
  const relationships = rows.filter((item) => item.action.startsWith('relationship.')).length;
  const evidence = rows.filter((item) => item.action.startsWith('evidence.')).length;

  return (
    <div className="page-stack watch-page">
      <header className="watch-hero">
        <div>
          <span className="eyebrow">Continuous monitoring / live channel</span>
          <h1>Threat <i>Watch.</i></h1>
          <p>Watch the investigation state change in real time. Every event remains tied to its case and audit record.</p>
        </div>
        <div className="watch-live-card">
          <span className={connected ? 'live-dot live-dot--on' : 'live-dot'} />
          <div><b>{connected ? 'Streaming' : 'Reconnecting'}</b><small>{rows.length} events in current window</small></div>
        </div>
      </header>

      <section className="watch-summary">
        <button className={filter === 'all' ? 'is-active' : ''} onClick={() => setFilter('all')}><b>{rows.length}</b><span>all events</span></button>
        <button className={filter === 'critical' ? 'is-active is-danger' : ''} onClick={() => setFilter('critical')}><b>{critical}</b><span>critical</span></button>
        <button className={filter === 'relationship' ? 'is-active is-blue' : ''} onClick={() => setFilter('relationship')}><b>{relationships}</b><span>relationships</span></button>
        <button className={filter === 'evidence' ? 'is-active is-green' : ''} onClick={() => setFilter('evidence')}><b>{evidence}</b><span>evidence</span></button>
      </section>

      <section className="watch-layout">
        <div className="watch-stream">
          <div className="watch-stream__head"><span>Event</span><span>Case</span><span>Time</span></div>
          {filtered.map((item) => {
            const level = severity(item);
            return (
              <Link to={item.case_id ? `/cases/${item.case_id}` : '/threat-watch'} className={`watch-event watch-event--${level}`} key={item.seq}>
                <div className="watch-event__main">
                  <span className="watch-event__marker">{level === 'critical' ? '!' : level === 'elevated' ? '↗' : '·'}</span>
                  <div><b>{label(item)}</b><small>{item.action.replaceAll('.', ' / ')}</small></div>
                </div>
                <span className="watch-event__case">{item.case_id ? item.case_id.slice(0, 8).toUpperCase() : 'SYSTEM'}</span>
                <span className="watch-event__time">{new Date(item.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}<small>{new Date(item.occurred_at).toLocaleDateString()}</small></span>
              </Link>
            );
          })}
          {filtered.length === 0 && <div className="watch-empty">No events match this filter.</div>}
        </div>

        <aside className="watch-aside">
          <div className="watch-aside__head"><span className="eyebrow">Signal posture</span><b>Now</b></div>
          <div className="watch-meter"><span>Critical events</span><b>{critical}</b><i><em style={{ width: `${Math.min(100, critical * 12)}%` }} /></i></div>
          <div className="watch-meter"><span>Relationship movement</span><b>{relationships}</b><i><em style={{ width: `${Math.min(100, relationships * 10)}%` }} /></i></div>
          <div className="watch-meter"><span>Evidence movement</span><b>{evidence}</b><i><em style={{ width: `${Math.min(100, evidence * 10)}%` }} /></i></div>
          <div className="watch-note"><span>Operational note</span><p>Signals are synthetic demonstration data. Follow the linked case to inspect provenance before drawing conclusions.</p></div>
        </aside>
      </section>
    </div>
  );
}
