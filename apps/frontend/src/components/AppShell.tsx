import { useCallback, useEffect, useMemo, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { AgentButton } from './AgentButton';
import { CommandPalette, openCommandPalette } from './CommandPalette';
import { ErrorBoundary } from './ErrorBoundary';
import { GlobalSearch } from './GlobalSearch';
import { TimeRangeControl } from './TimeRangeControl';
import { usePublishAgentContext } from './agent-context';
import { useLive } from '../hooks/useLive';
import { useAuth } from '../store/auth';

/**
 * Five destinations, and that is the whole app.
 *
 * There is deliberately no top-level Graph / Evidence / Hypotheses /
 * Attribution / Timeline / Sources entry. All of that is case analysis, and an
 * investigator opens a case rather than a subsystem — so it lives behind
 * `Investigations` in the Investigation Workspace. Putting it in the sidebar
 * too meant every one of those screens was reachable without a case and
 * therefore had to either duplicate the workspace or guess at one.
 *
 * `Actors` is the one cross-case surface, and it is different in kind: a
 * tracked actor belongs to no single investigation, several cases may cite it,
 * and "who is this persona across the whole platform" is a question an analyst
 * asks before choosing which case to open. It is here for that reason and not
 * as case analysis in disguise.
 */
const NAV = [
  { to: '/', label: 'Command Center', icon: '⌂', end: true },
  { to: '/cases', label: 'Investigations', icon: '◎', end: false },
  { to: '/actors', label: 'Actors', icon: '☗', end: false },
  { to: '/infrastructure', label: 'Infrastructure', icon: '⛓', end: false },
  { to: '/personas', label: 'Persona Linkage', icon: '⚯', end: false },
  { to: '/collection', label: 'Collection', icon: '⟳', end: false },
  { to: '/threat-watch', label: 'Threat Watch', icon: '◉', end: false },
];

const SYSTEM_NAV = [{ to: '/admin', label: 'Administration', icon: '⚙', end: false }];

/** Breadcrumb labels; a raw path segment reads as a slug, not as a name. */
const SECTION_LABELS: Record<string, string> = {
  cases: 'Investigations',
  actors: 'Actors',
  infrastructure: 'Infrastructure',
  personas: 'Persona Linkage',
  collection: 'Collection',
  'threat-watch': 'Threat Watch',
  watch: 'Threat Watch',
  // `/reports` is a redirect, not a destination: exporting an investigation is
  // an action taken on a case, so it lives in the workspace header. The label
  // remains so a bookmarked or in-flight URL still reads correctly in the
  // breadcrumb while it bounces.
  reports: 'Reports',
  admin: 'Administration',
  settings: 'Administration',
};

/** The two screens that bound their own rows by date already. */
const OWNS_TIMELINE = ['/infrastructure', '/personas'];

function ownsTimeline(pathname: string): boolean {
  return OWNS_TIMELINE.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

function sectionLabel(pathname: string): string {
  const segment = pathname.split('/')[1];
  if (pathname === '/') return 'Command Center';
  if (segment && SECTION_LABELS[segment]) return SECTION_LABELS[segment];
  if (pathname.startsWith('/cases/')) return 'Investigation';
  return 'Workspace';
}

/** `mm:ss` remaining, or null when the session has no recorded expiry. */
function remainingLabel(expiresAt: number | null): string | null {
  if (expiresAt === null) return null;
  const seconds = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
  const minutes = Math.floor(seconds / 60);
  if (seconds < 60) return `${seconds}s`;
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function AppShell() {
  const location = useLocation();
  const { connected, degradedReason, snapshot } = useLive();
  const { signOut, identity, sessionExpiresAt } = useAuth();
  const section = sectionLabel(location.pathname);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const closePalette = useCallback(() => setPaletteOpen(false), []);

  useEffect(() => {
    openCommandPalette.set(openPalette);
    return () => openCommandPalette.set(null);
  }, [openPalette]);

  // The shell owns the ⌘K binding rather than the palette itself, so the
  // palette stays a controlled component and the shortcut is declared in one
  // place next to the other global affordances.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== 'k' || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      setPaletteOpen((value) => !value);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Inside an investigation the workspace publishes a richer context (case
  // name + active view) and owns this. Here we only cover the top-level
  // spaces, so the agent always knows which screen it was invoked from
  // instead of receiving a bare route.
  const inCase = location.pathname.startsWith('/cases/');
  usePublishAgentContext(useMemo(() => (inCase ? null : { place: section }), [inCase, section]));

  const sessionLeft = remainingLabel(sessionExpiresAt);
  const initials = (identity?.name ?? 'AN')
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="app-shell">
      {/* Keyboard users land here first; without it every tab stop goes
          through the sidebar before reaching the content they navigated to. */}
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
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
        {degradedReason ? (
          // A silent console is worse than a slow one. The feed is stale and
          // the analyst needs to know the numbers on screen have stopped
          // moving before they act on them.
          <p className="sidebar-degraded" role="status">
            {degradedReason}
          </p>
        ) : null}
        <nav aria-label="Primary">
          <p className="nav-label">Workspace</p>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          <p className="nav-label nav-label--spaced">System</p>
          {SYSTEM_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="analyst">
            <span>{initials}</span>
            <div>
              <strong>{identity?.name ?? 'Analyst'}</strong>
              <small>{identity?.role ?? 'Intelligence Analyst'}</small>
              {sessionLeft ? (
                <small className="analyst__session">
                  Session {sessionLeft} remaining
                </small>
              ) : null}
            </div>
          </div>
          <div className="secure-note">AUTHORIZED · AUDITED · CONTROLLED</div>
        </div>
      </aside>
      <header className="topbar">
        <div className="crumb">
          <span>AEGIS</span>
          <b>/</b>
          <span>{section}</span>
        </div>
        <div className="top-actions">
          {/* One timeline over the registers that had none. It is absent on
              Infrastructure and Persona Linkage because those two own a
              timeline already, bound to a different timestamp, and two
              controls filtering one screen is one too many. */}
          {!ownsTimeline(location.pathname) && <TimeRangeControl />}
          {/* The search box is a real, always-visible control rather than a
              button that opens something else. A shortcut-only search is
              invisible search: an analyst who does not know the binding has
              no way to discover it exists, and "where have I seen this
              handle" is not a question anyone thinks of as needing a case
              already open. */}
          <GlobalSearch />
          <button
            type="button"
            className="profile profile-button"
            onClick={signOut}
            title="Sign out"
            aria-label={`Sign out ${identity?.name ?? 'analyst'}`}
          >
            {initials}
          </button>
        </div>
      </header>
      <main className="app-main" id="main-content" tabIndex={-1}>
        {/* Scoped to the outlet so a failing screen never takes the sidebar,
            the live indicator or the agent down with it. resetKey is the
            pathname, so moving between spaces clears the error. */}
        <ErrorBoundary resetKey={location.pathname} label={`${section} failed to render.`}>
          <Outlet />
        </ErrorBoundary>
      </main>
      <AgentButton />
      <CommandPalette open={paletteOpen} onClose={closePalette} />
    </div>
  );
}
