import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { AgentButton } from './AgentButton';
import { useLive } from '../hooks/useLive';

const NAV = [
  { to: '/', label: 'Command Center', icon: '⌂', end: true },
  { to: '/cases', label: 'Cases', icon: '□' },
  { to: '/watch', label: 'Threat Watch', icon: '◉' },
  { to: '/reports', label: 'Reports', icon: '≡' },
];

export function AppShell() {
  const location = useLocation();
  const { connected, snapshot } = useLive();
  const context = location.pathname.startsWith('/cases/') ? `Current investigation: ${location.pathname.split('/').pop()}` : undefined;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">◇</span><span>AEGIS</span><small>INTELLIGENCE</small></div>
        <div className="sidebar-live"><span className={connected ? 'live-dot live-dot--on' : 'live-dot'} /> {connected ? 'Live' : 'Reconnecting'} <span>{snapshot ? new Date(snapshot.server_time).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '—'}</span></div>
        <nav aria-label="Primary">
          <p className="nav-label">Workspace</p>
          {NAV.map((item) => <NavLink key={item.to} to={item.to} end={item.end} className={({isActive}) => `nav-item ${isActive ? 'nav-item--active' : ''}`}><span>{item.icon}</span>{item.label}</NavLink>)}
        </nav>
        <div className="sidebar-bottom"><div className="analyst"><span>MK</span><div><strong>Analyst</strong><small>Local workspace</small></div></div><div className="secure-note">Synthetic / authorized data only</div></div>
      </aside>
      <header className="topbar">
        <div className="crumb"><span>AEGIS</span><b>/</b><span>{location.pathname === '/' ? 'Command Center' : location.pathname.split('/')[1] ?? 'Workspace'}</span></div>
        <div className="top-actions"><button className="search-pill" onClick={() => window.dispatchEvent(new Event('aegis:open-agent'))}><span>⌕</span> Search cases, actors, evidence <kbd>⌘ K</kbd></button><button className="icon-button">◌</button><div className="profile">MK</div></div>
      </header>
      <main className="app-main"><Outlet /></main>
      <AgentButton context={context} />
    </div>
  );
}
