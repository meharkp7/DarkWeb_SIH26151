import { NavLink, Outlet } from 'react-router-dom';
import { HealthIndicator } from './HealthIndicator';
import { cx } from '../lib/format';

interface NavItem {
  readonly to: string;
  readonly label: string;
  readonly glyph: string;
  readonly end?: boolean;
}

interface NavGroup {
  readonly label: string;
  readonly items: readonly NavItem[];
}

const NAV_GROUPS: readonly NavGroup[] = [
  {
    label: 'Investigations',
    items: [
      { to: '/', label: 'Cases', glyph: '▤', end: true },
      { to: '/evidence', label: 'Evidence', glyph: '⬡' },
      { to: '/timeline', label: 'Timeline', glyph: '⌗' },
      { to: '/graph', label: 'Graph', glyph: '✦' },
    ],
  },
  {
    label: 'Analysis',
    items: [
      { to: '/attribution', label: 'Attribution', glyph: '◎' },
      { to: '/hypotheses', label: 'Hypotheses', glyph: '⚖' },
      { to: '/sources', label: 'Sources', glyph: '⚲' },
    ],
  },
  {
    label: 'Output',
    items: [{ to: '/reports', label: 'Reports', glyph: '✎' }],
  },
];

/** Application shell: header with health probe, left navigation, routed main area. */
export function AppShell() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="app-header">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            ◆
          </span>
          <span className="brand__name">AEGIS</span>
          <span className="brand__tag">Investigation Console</span>
        </div>
        <HealthIndicator />
      </header>

      <nav className="app-nav" aria-label="Primary">
        {NAV_GROUPS.map((group, index) => {
          const labelId = `nav-group-label-${index}`;
          return (
            <div className="nav-group" key={group.label}>
              <p className="nav-group__label" id={labelId}>
                {group.label}
              </p>
              <ul className="nav-group__list" aria-labelledby={labelId}>
                {group.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.end ?? false}
                      className={({ isActive }) => cx('nav-link', isActive && 'nav-link--active')}
                    >
                      <span className="nav-link__glyph" aria-hidden="true">
                        {item.glyph}
                      </span>
                      <span className="nav-link__label">{item.label}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        <p className="nav-footnote">
          Screens render live API data where endpoints exist; otherwise they state plainly what is
          missing.
        </p>
      </nav>

      <main id="main-content" className="app-main" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
