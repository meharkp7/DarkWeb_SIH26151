import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from './App';
import type { CaseSummary, CaseWorkspace } from './api/types';
import { SessionProvider } from './store/session';
import { installFetch, jsonResponse } from './test/mockFetch';

/**
 * The route table encodes the five-space information architecture:
 *
 *   Command Center  Cases  Investigation Workspace  Reports  Threat Watch
 *
 * plus Settings. The former global analysis surfaces are not pages any more —
 * they redirect into the case index. Both halves are pinned here, because the
 * failure mode this guards against is the sidebar quietly growing back to ten
 * entries and the same data being sliced a second time.
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

const CASE_SUMMARY = {
  case_id: 'case-123',
  name: 'Alpha Breach',
  status: 'active',
  priority: 'high',
  severity: 'critical',
  tags: ['financial'],
  assigned_to: null,
  sla_due_at: null,
  sla_overdue: false,
  counts: { evidence: 3, entities: 2, relationships: 1, assessments: 0 },
} as unknown as CaseSummary;

function renderRoute(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  );
}

function installRouteFetch(): void {
  installFetch(async (input) => {
    const url = String(input);
    if (url.includes('/api/v1/cases/case-123/workspace')) return jsonResponse(WORKSPACE);
    if (url.includes('/api/v1/cases/case-123/notes')) return jsonResponse([]);
    if (url.includes('/api/v1/cases/case-123/hypotheses')) return jsonResponse([]);
    if (url.includes('/api/v1/dashboard/cases')) return jsonResponse([CASE_SUMMARY]);
    if (url.includes('/api/v1/dashboard/summary')) {
      return jsonResponse({
        type: 'snapshot',
        server_time: '2026-09-29T12:00:00Z',
        counts: { cases: 1, evidence: 3, entities: 2, relationships: 1, assessments: 1 },
        critical_alerts: 0,
        activity: [],
      });
    }
    if (url.includes('/health')) return jsonResponse({ status: 'ok', service: 'api' });
    // Threat Watch renders from the live WebSocket snapshot; nothing to serve.
    throw new Error(`App route test received an unexpected request: ${url}`);
  });
}

/** The five primary spaces plus Settings. Anything else is not a page. */
const PRIMARY_ROUTES: ReadonlyArray<readonly [path: string, heading: string]> = [
  ['/cases', 'Cases'],
  ['/cases/case-123', 'Alpha Breach'],
  ['/reports', 'Reports'],
  ['/settings', 'Settings'],
];

/**
 * Retired global analysis surfaces. Each is reachable only as a case view, so
 * the old standalone URL has to land on the case index rather than 404 — an
 * analyst with a bookmark should still end up somewhere useful.
 */
const RETIRED_ROUTES = [
  '/graph',
  '/evidence',
  '/timeline',
  '/attribution',
  '/hypotheses',
  '/sources',
  '/actors/actor-7f6d',
] as const;

describe('App route table', () => {
  it.each(PRIMARY_ROUTES)('resolves %s to its page, not NotFound', async (path, heading) => {
    installRouteFetch();
    renderRoute(path);

    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Page not found' })).not.toBeInTheDocument();
  });

  it('greets the analyst on the Command Center, by the actual time of day', async () => {
    installRouteFetch();
    renderRoute('/');

    // The greeting tracks the clock rather than being a fixed string, so this
    // asserts the shape and not one particular hour.
    const heading = await screen.findByRole('heading', {
      name: /Good (morning|afternoon|evening), Analyst\./,
    });
    expect(heading).toBeInTheDocument();
  });

  it.each(RETIRED_ROUTES)('%s redirects into the case index rather than 404ing', async (path) => {
    installRouteFetch();
    renderRoute(path);

    expect(await screen.findByRole('heading', { name: 'Cases' })).toBeInTheDocument();
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
  it('offers exactly the five spaces plus Settings', async () => {
    installRouteFetch();
    renderRoute('/');

    const nav = await screen.findByRole('navigation', { name: 'Primary' });
    const labels = Array.from(nav.querySelectorAll('.nav-item')).map((el) => el.textContent?.trim());

    expect(labels).toEqual(['⌂Command Center', '◎Cases', '◉Threat Watch', '⎙Reports', '⚙Settings']);
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
      expect(Array.from(active).map((el) => el.textContent?.trim())).toEqual(['◎Cases']);
    });
  });
});
