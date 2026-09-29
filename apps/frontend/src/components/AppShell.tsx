import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useMemo } from 'react';
import { AgentButton } from './AgentButton';
import { ErrorBoundary } from './ErrorBoundary';
import { usePublishAgentContext } from './agent-context';
import { useLive } from '../hooks/useLive';

/**
 * Five destinations, and that is the whole app.
 *
 * There is deliberately no top-level Graph / Evidence / Hypotheses /
 * Attribution / Timeline / Sources / Actors entry. All of that is case
 * analysis, and an investigator opens a case rather than a subsystem — so it
 * lives behind `Cases` in the Investigation Workspace. Putting it in the
 * sidebar too meant every one of those screens was reachable without a case
 * and therefore had to either duplicate the workspace or guess at one.
 *
 * The floating AEGIS Agent is the sixth affordance, and it is not a page —
 * it reads whatever context the current space publishes.
 */
const NAV = [
  { to: '/', label: 'Command Center', icon: '⌂', end: true },
  { to: '/cases', label: 'Cases', icon: '◎', end: false },
  { to: '/threat-watch', label: 'Threat Watch', icon: '◉', end: false },
  { to: '/reports', label: 'Reports', icon: '⎙', end: false },
];

const SETTINGS_NAV = [{ to: '/settings', label: 'Settings', icon: '⚙', end: true }];

/** Breadcrumb labels; a raw path segment reads as a slug, not as a name. */
const SECTION_LABELS: Record<string, string> = {
  cases: 'Cases',
  'threat-watch': 'Threat Watch',
  watch: 'Threat Watch',
  reports: 'Reports',
  settings: 'Settings',
};

function sectionLabel(pathname: string): string {
  const segment = pathname.split('/')[1];
  if (pathname === '/') return 'Command Center';
  if (segment && SECTION_LABELS[segment]) return SECTION_LABELS[segment];
  if (pathname.startsWith('/cases/')) return 'Investigation';
  return 'Workspace';
}

export function AppShell() {
  const location = useLocation();
  const { connected, snapshot } = useLive();
  const section = sectionLabel(location.pathname);

  // Inside an investigation the workspace publishes a richer context (case
  // name + active view) and owns this. Here we only cover the top-level
  // spaces, so the agent always knows which screen it was invoked from
  // instead of receiving a bare route.
  const inCase = location.pathname.startsWith('/cases/');
  usePublishAgentContext(useMemo(() => (inCase ? null : { place: section }), [inCase, section]));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◇</span>
          <span>AEGIS</span>
          <small>INTELLIGENCE</small>
        </div>
        <div className="sidebar-live">
          <span className={connected ? 'live-dot live-dot--on' : 'live-dot'} />{' '}
          {connected ? 'Live' : 'Reconnecting'}{' '}
          <span>
            {snapshot
              ? new Date(snapshot.server_time).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : '—'}
          </span>
        </div>
        <nav aria-label="Primary">
          <p className="nav-label">Workspace</p>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          <p className="nav-label nav-label--spaced">System</p>
          {SETTINGS_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="analyst">
            <span>MK</span>
            <div>
              <strong>Analyst</strong>
              <small>Local workspace</small>
            </div>
          </div>
          <div className="secure-note">Synthetic / authorized data only</div>
        </div>
      </aside>
      <header className="topbar">
        <div className="crumb">
          <span>AEGIS</span>
          <b>/</b>
          <span>{section}</span>
        </div>
        <div className="top-actions">
          <button
            className="search-pill"
            onClick={() => window.dispatchEvent(new Event('aegis:open-agent'))}
          >
            <span>⌕</span> Search cases, actors, evidence <kbd>⌘ K</kbd>
          </button>
          <button className="icon-button">◌</button>
          <div className="profile">MK</div>
        </div>
      </header>
      <main className="app-main">
        {/* Scoped to the outlet so a failing screen never takes the sidebar,
            the live indicator or the agent down with it. resetKey is the
            pathname, so moving between spaces clears the error. */}
        <ErrorBoundary resetKey={location.pathname} label={`${section} failed to render.`}>
          <Outlet />
        </ErrorBoundary>
      </main>
      <AgentButton />
    </div>
  );
}
