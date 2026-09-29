import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from './App';
import type { CaseWorkspace } from './api/types';
import { SessionProvider } from './store/session';
import { installFetch, jsonResponse } from './test/mockFetch';

/**
 * The route table in App.tsx was recently rewired (pages used to redirect to
 * /cases). These tests pin the important paths to a real page element instead
 * of the NotFound fallback.
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
    if (url.includes('/api/v1/dashboard/summary')) {
      return jsonResponse({
        type: 'snapshot',
        server_time: '2026-09-29T12:00:00Z',
        counts: { cases: 0, evidence: 0, entities: 0, relationships: 0, assessments: 0 },
        critical_alerts: 0,
        activity: [],
      });
    }
    throw new Error(`App route test received an unexpected request: ${url}`);
  });
}

const ROUTE_HEADINGS: ReadonlyArray<readonly [path: string, heading: string]> = [
  ['/', 'Good evening, Analyst.'],
  ['/cases', 'Cases'],
  ['/cases/case-123', 'Alpha Breach'],
  ['/watch', 'Threat Watch'],
  ['/reports', 'Reports'],
  ['/graph', 'Graph'],
  ['/evidence', 'Evidence explorer'],
  ['/timeline', 'Timeline'],
  ['/attribution', 'Attribution assessment'],
  ['/hypotheses', 'Hypothesis comparison'],
  ['/sources', 'Source reliability'],
  ['/actors/actor-7f6d', 'actor-7f6d'],
];

describe('App route table', () => {
  it.each(ROUTE_HEADINGS)('resolves %s to its page, not NotFound', async (path, heading) => {
    installRouteFetch();
    renderRoute(path);

    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Page not found' })).not.toBeInTheDocument();
  });

  it('falls through unknown paths to NotFound', async () => {
    installRouteFetch();
    renderRoute('/no/such/route');

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});