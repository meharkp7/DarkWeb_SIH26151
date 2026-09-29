import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from './App';
import { clearSessionToken, setSessionToken } from './api/client';
import type { CaseSummary, CaseWorkspace, DashboardSnapshot } from './api/types';
import { AuthProvider } from './store/auth';
import { installFetch, jsonResponse } from './test/mockFetch';

/**
 * The route table encodes the information architecture:
 *
 *   Command Center · Investigations · Investigation Workspace ·
 *   Threat Watch · Administration
 *
 * The former global analysis surfaces are not pages any more — they redirect
 * into the case index. `/reports` went the same way: export is an action on a
 * case, not a destination, so it is an inline popover in the workspace and
 * register headers and the preview is a drawer. Both halves are pinned here,
 * because the failure mode this guards against is the sidebar quietly growing
 * back to ten entries and the same data being sliced a second time.
 */

const WORKSPACE: CaseWorkspace = {
  case: {
    case_id: 'case-123',
    name: 'Alpha Breach',
    description: null,
    status: 'active',
    priority: 'high',
    severity: 'critical',
    tags: ['financial'],
    assigned_to: null,
    sla_due_at: null,
    closed_at: null,
    closure_reason: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: null,
    sla_overdue: false,
  },
  counts: { evidence: 3, entities: 2, relationships: 1, assessments: 1 },
  evidence: [],
  entities: [],
  relationships: [],
  assessments: [],
  activity: [],
};

/**
 * A full `CaseQueueEntry`.
 *
 * Every field the backend now guarantees is present, because the console
 * reads them: a stub missing `reasons` or `sla_state` would let a page render
 * against a shape the API never sends, and the bug would only surface in
 * production.
 */
const CASE_SUMMARY: CaseSummary = {
  case_id: 'case-123',
  name: 'Alpha Breach',
  status: 'active',
  priority: 'high',
  severity: 'critical',
  tags: ['financial'],
  assigned_to: null,
  sla_due_at: null,
  sla_overdue: false,
  sla_state: 'none',
  queue_score: 62,
  queue_reason: 'High priority',
  reasons: [
    { key: 'priority', label: 'High priority', weight: 34 },
    { key: 'severity', label: 'Critical severity', weight: 26 },
  ],
  counts: {
    evidence: 3,
    entities: 2,
    relationships: 1,
    assessments: 0,
    contradictions: 0,
    recent_evidence: 1,
  },
  last_activity: null,
  attribution: null,
};

/** The full snapshot every page reads its figures from. */
const SNAPSHOT = {
  type: 'snapshot',
  server_time: '2026-09-29T12:00:00Z',
  counts: { cases: 1, evidence: 3, entities: 2, relationships: 1, assessments: 1 },
  critical_alerts: 0,
  activity: [],
  case_summaries: [CASE_SUMMARY],
  command_posture: {
    active_investigations: 1,
    critical: 0,
    high: 1,
    sla_at_risk: 0,
    new_evidence: 3,
    unresolved_links: 0,
    total_investigations: 1,
    unassigned: 0,
    pressure_index: 12,
  },
  evidence_velocity: [
    { label: 'Sep 2026', count: 3, delta: null },
  ],
  investigation_pressure: [
    { key: 'evidence_velocity', label: 'Evidence velocity', score: 1, observed: 3, ceiling: 900 },
  ],
  attribution_posture: [],
} as unknown as DashboardSnapshot;

function renderRoute(path: string): void {
  clearSessionToken();
  setSessionToken('route-test-token', Date.now() + 3_600_000);
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function installRouteFetch(): void {
  installFetch(async (input) => {
    const url = String(input);
    if (url.includes('/api/v1/auth/me')) {
      return jsonResponse({
        email: 'analyst@example.test',
        name: 'Test Analyst',
        role: 'analyst',
        organization: 'AEGIS',
      });
    }
    if (url.includes('/api/v1/cases/case-123/workspace')) return jsonResponse(WORKSPACE);
    if (url.includes('/api/v1/cases/case-123/notes')) return jsonResponse([]);
    if (url.includes('/api/v1/cases/case-123/hypotheses')) return jsonResponse([]);
    for (const [suffix, body] of Object.entries({
      '/metrics': {
        case_id: 'case-123', evidence: 3, links: 1, entities: 2, sources: 1,
        attribution: null, contradictions: 0, hypotheses: 0, independent_sources: 1,
      },
      '/signals': [],
      '/timeline': { case_id: 'case-123', events: [], layers: [] },
      '/graph': { case_id: 'case-123', nodes: [], edges: [], edge_types: {}, node_types: {} },
      '/activity': [],
      '/evidence': [],
    })) {
      if (url.includes(`/cases/case-123${suffix}`)) return jsonResponse(body);
    }
    if (url.includes('/api/v1/dashboard/cases')) return jsonResponse([CASE_SUMMARY]);
    if (url.includes('/api/v1/dashboard/summary')) return jsonResponse(SNAPSHOT);
    if (url.includes('/api/v1/threat-watch/events')) return jsonResponse([]);
    if (url.includes('/health')) return jsonResponse({ status: 'ok', service: 'api' });
    // Threat Watch renders from the live WebSocket snapshot; nothing to serve.
    throw new Error(`App route test received an unexpected request: ${url}`);
  });
}

/** The primary spaces. Anything else is not a page. */
const PRIMARY_ROUTES: ReadonlyArray<readonly [path: string, heading: string | RegExp]> = [
  ['/cases', /Investigations|Cases/],
  ['/cases/case-123', 'Alpha Breach'],
  ['/admin', /Administration|Team|Audit|System/],
];

/**
 * Retired destinations. Each is reachable only as a case view or an inline
 * control, so the old standalone URL has to land on the case index rather than
 * 404 — an analyst with a bookmark should still end up somewhere useful.
 * `/reports` joins them because export moved into the headers, not because it
 * ever needed a case to mean anything.
 */
const RETIRED_ROUTES = [
  '/graph',
  '/evidence',
  '/timeline',
  '/attribution',
  '/hypotheses',
  '/sources',
  '/actors/actor-7f6d',
  '/reports',
] as const;

describe('App route table', () => {
  it.each(PRIMARY_ROUTES)('resolves %s to its page, not NotFound', async (path, heading) => {
    installRouteFetch();
    renderRoute(path);

    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Page not found' })).not.toBeInTheDocument();
  });

  it('sends the retired /settings path to Administration', async () => {
    installRouteFetch();
    renderRoute('/settings');

    await waitFor(() => {
      expect(document.querySelector('.crumb')?.textContent).toContain('Administration');
    });
  });

  it('greets the signed-in analyst by name, by the actual time of day', async () => {
    installRouteFetch();
    renderRoute('/');

    // Two things are asserted here, and both used to be faked: the hour comes
    // from the clock rather than a fixed string, and the name comes from the
    // authenticated identity rather than a hard-coded "Analyst." A console
    // that greets everyone identically is not reading who is signed in.
    const heading = await screen.findByRole('heading', {
      name: /Good (morning|afternoon|evening), Test Analyst\./,
    });
    expect(heading).toBeInTheDocument();
  });

  it.each(RETIRED_ROUTES)('%s redirects into the case index rather than 404ing', async (path) => {
    installRouteFetch();
    renderRoute(path);

    expect(await screen.findByRole('heading', { name: /Investigations|Cases/ })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Page not found' })).not.toBeInTheDocument();
  });

  it('renames the old /watch path to the canonical /threat-watch', async () => {
    installRouteFetch();
    renderRoute('/watch');

    // Threat Watch renders from the live snapshot, so there is no h1 to await;
    // asserting the redirect target is the breadcrumb it lands on.
    await waitFor(() => {
      expect(document.querySelector('.crumb')?.textContent).toContain('Threat Watch');
    });
  });

  it('falls through unknown paths to NotFound', async () => {
    installRouteFetch();
    renderRoute('/no/such/route');

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

describe('primary navigation', () => {
  it('offers exactly the five spaces plus Administration', async () => {
    installRouteFetch();
    renderRoute('/');

    const nav = await screen.findByRole('navigation', { name: 'Primary' });
    const labels = Array.from(nav.querySelectorAll('.nav-item')).map((el) => el.textContent?.trim());

    // Reports is deliberately absent: exporting an investigation is an action
    // taken on a case, so it lives in the workspace header rather than
    // occupying a destination of its own.
    expect(labels).toEqual([
      '⌂Command Center',
      '◎Investigations',
      '◉Threat Watch',
      '⚙Administration',
    ]);
  });

  it('does not list any retired analysis surface in the sidebar', async () => {
    installRouteFetch();
    renderRoute('/');

    const nav = await screen.findByRole('navigation', { name: 'Primary' });
    for (const retired of ['Graph', 'Evidence', 'Hypotheses', 'Attribution', 'Timeline', 'Sources', 'Actors']) {
      expect(nav.textContent).not.toContain(retired);
    }
  });

  it('keeps Cases highlighted while inside an investigation', async () => {
    installRouteFetch();
    renderRoute('/cases/case-123');

    await screen.findByRole('heading', { name: 'Alpha Breach' });

    await waitFor(() => {
      const active = document.querySelectorAll('.nav-item--active');
      expect(Array.from(active).map((el) => el.textContent?.trim())).toEqual([
        '◎Investigations',
      ]);
    });
  });
});
