import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { CasesPage } from './CasesPage';
import type { CaseSummary } from '../api/types';
import { installFetch, jsonResponse } from '../test/mockFetch';

function summary(
  overrides: Partial<CaseSummary> & Pick<CaseSummary, 'case_id' | 'name'>,
): CaseSummary {
  return {
    description: null,
    status: 'open',
    priority: 'medium',
    severity: 'medium',
    tags: [],
    assigned_to: null,
    sla_due_at: null,
    closed_at: null,
    closure_reason: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: null,
    sla_overdue: false,
    counts: { evidence: 1, entities: 1, relationships: 1, assessments: 0 },
    last_activity: null,
    ...overrides,
  };
}

const CASES: CaseSummary[] = [
  summary({
    case_id: 'case-c1',
    name: 'Alpha Marketplace',
    status: 'active',
    priority: 'critical',
    severity: 'critical',
    tags: ['marketplace'],
  }),
  summary({
    case_id: 'case-c2',
    name: 'Beta Breach',
    status: 'open',
    priority: 'high',
    severity: 'high',
    tags: ['financial'],
    sla_overdue: true,
    sla_due_at: '2026-09-20T00:00:00Z',
  }),
  summary({
    case_id: 'case-c3',
    name: 'Gamma Leak',
    status: 'closed',
    priority: 'medium',
    severity: 'medium',
    tags: ['forum'],
  }),
  summary({
    case_id: 'case-c4',
    name: 'Delta Campaign',
    status: 'open',
    priority: 'low',
    severity: 'low',
    tags: ['marketplace'],
  }),
];

function renderPage(): void {
  render(
    <MemoryRouter>
      <CasesPage />
    </MemoryRouter>,
  );
}

async function rowHeadings(): Promise<HTMLElement[]> {
  return screen.findAllByRole('heading', { level: 3 });
}

describe('CasesPage', () => {
  it('renders one case row per record returned by the API', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();

    const headings = await rowHeadings();
    expect(headings).toHaveLength(4);
    for (const name of ['Alpha Marketplace', 'Beta Breach', 'Gamma Leak', 'Delta Campaign']) {
      expect(screen.getByRole('heading', { name })).toBeInTheDocument();
    }
    // Each row links into its case workspace.
    expect(screen.getByRole('link', { name: /Alpha Marketplace/ })).toHaveAttribute(
      'href',
      '/cases/case-c1',
    );
    expect(screen.getByText('4 of 4 shown · live from PostgreSQL')).toBeInTheDocument();
  });

  it('narrows the list by priority', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await rowHeadings();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter by priority' }), 'high');

    expect(await screen.findByRole('heading', { name: 'Beta Breach' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Delta Campaign' })).not.toBeInTheDocument();
    expect(screen.getByText('1 of 4 shown · live from PostgreSQL')).toBeInTheDocument();
  });

  it('narrows the list by severity', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await rowHeadings();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter by severity' }), 'low');

    expect(await screen.findByRole('heading', { name: 'Delta Campaign' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Beta Breach' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(screen.getByText('1 of 4 shown · live from PostgreSQL')).toBeInTheDocument();
  });

  it('narrows the list by status', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await rowHeadings();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter by status' }), 'open');

    expect(await screen.findByRole('heading', { name: 'Beta Breach' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Delta Campaign' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Gamma Leak' })).not.toBeInTheDocument();
    expect(screen.getByText('2 of 4 shown · live from PostgreSQL')).toBeInTheDocument();
  });

  it('searches by name, description or tag', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await rowHeadings();

    await userEvent.type(screen.getByRole('textbox', { name: 'Search cases' }), 'gamma');

    expect(await screen.findByRole('heading', { name: 'Gamma Leak' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(screen.getByText('1 of 4 shown · live from PostgreSQL')).toBeInTheDocument();
  });
});