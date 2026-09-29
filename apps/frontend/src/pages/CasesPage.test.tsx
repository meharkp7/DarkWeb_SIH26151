import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { CasesPage } from './CasesPage';
import type { CasePriority, CaseQueueEntry, CaseStatus, SlaState } from '../api/types';
import { installFetch, jsonResponse } from '../test/mockFetch';

/**
 * The register renders `CaseQueueEntry` rows. `summary` builds a full entry;
 * `legacySummary` builds the pre-queue shape (no reasons, no sla_state, no
 * contradiction counts) so the defensive readers are covered too.
 */
function entry(overrides: Partial<CaseQueueEntry> & Pick<CaseQueueEntry, 'case_id' | 'name'>): CaseQueueEntry {
  return {
    status: 'open',
    priority: 'medium',
    severity: 'medium',
    tags: [],
    assigned_to: null,
    sla_due_at: null,
    sla_overdue: false,
    sla_state: 'none',
    queue_score: 0,
    queue_reason: '',
    reasons: [],
    counts: { evidence: 1, entities: 1, relationships: 1, assessments: 0, contradictions: 0, recent_evidence: 0 },
    last_activity: null,
    attribution: null,
    ...overrides,
  };
}

const CASES: CaseQueueEntry[] = [
  entry({
    case_id: 'case-c1',
    name: 'Alpha Marketplace',
    status: 'active',
    priority: 'critical',
    severity: 'critical',
    tags: ['marketplace'],
    queue_score: 82.5,
    queue_reason: 'critical priority, 4 fresh evidence',
    reasons: [{ key: 'priority', label: 'Critical triage priority', weight: 40 }],
  }),
  entry({
    case_id: 'case-c2',
    name: 'Beta Breach',
    status: 'open',
    priority: 'high',
    severity: 'high',
    tags: ['financial'],
    sla_overdue: true,
    sla_state: 'breached',
    sla_due_at: '2026-09-20T00:00:00Z',
    queue_score: 61,
  }),
  entry({
    case_id: 'case-c3',
    name: 'Gamma Leak',
    status: 'closed',
    priority: 'medium',
    severity: 'medium',
    tags: ['forum'],
  }),
  entry({
    case_id: 'case-c4',
    name: 'Delta Campaign',
    status: 'open',
    priority: 'low',
    severity: 'low',
    tags: ['marketplace'],
  }),
];

function renderPage(initialEntry = '/cases'): void {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <CasesPage />
    </MemoryRouter>,
  );
}

/**
 * The register plus a location probe, so "did this navigate?" can be answered
 * from the router rather than inferred from a missing href.
 */
function renderRouted(initialEntry: string): void {
  function Probe() {
    return <span data-testid="location">{useLocation().pathname + useLocation().search}</span>;
  }
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/cases"
          element={
            <>
              <CasesPage />
              <Probe />
            </>
          }
        />
        <Route path="/cases/:caseId" element={<p>Case workspace</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The inspector rail is the only `complementary` landmark on the register. */
function rail(): HTMLElement | null {
  return screen.queryByRole('complementary');
}

/** Body rows only — the header row is not a case. */
async function caseRows(): Promise<HTMLElement[]> {
  const rows = await screen.findAllByRole('row');
  return rows.filter((row) => row.closest('tbody') !== null);
}

function text(): string {
  return document.body.textContent ?? '';
}

describe('CasesPage', () => {
  it('renders one dense table row per record returned by the API', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();

    const rows = await caseRows();
    expect(rows).toHaveLength(4);
    for (const name of ['Alpha Marketplace', 'Beta Breach', 'Gamma Leak', 'Delta Campaign']) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'Alpha Marketplace' })).toHaveAttribute(
      'href',
      '/cases/case-c1',
    );
    expect(text()).toContain('4 of 4 shown · live from PostgreSQL');
  });

  it('exposes sortable column headers with aria-sort', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();

    const priority = await screen.findByRole('button', { name: /Priority/ });
    expect(priority.closest('th')).toHaveAttribute('aria-sort', 'none');
    // The default sort is queue score, which no single column header owns.
    const caseHeader = await screen.findByRole('button', { name: /Case/ });
    expect(caseHeader.closest('th')).toHaveAttribute('aria-sort', 'none');

    await userEvent.click(priority);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Priority/ }).closest('th')).toHaveAttribute(
        'aria-sort',
        'descending',
      );
    });
    const names = [...(await caseRows())].map((row) => row.textContent ?? '');
    expect(names.findIndex((value) => value.includes('Alpha Marketplace'))).toBeLessThan(
      names.findIndex((value) => value.includes('Delta Campaign')),
    );
  });

  it('narrows the list by priority and writes the filter to the URL', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await caseRows();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter by priority' }), 'high');

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Filter by priority' })).toHaveValue('high');
    });
    expect(screen.getByRole('link', { name: 'Beta Breach' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Delta Campaign' })).not.toBeInTheDocument();
    expect(text()).toContain('1 of 4 shown · live from PostgreSQL');
  });

  it('narrows the list by severity', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await caseRows();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter by severity' }), 'low');

    expect(await screen.findByRole('link', { name: 'Delta Campaign' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Beta Breach' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(text()).toContain('1 of 4 shown · live from PostgreSQL');
  });

  it('narrows the list by status', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await caseRows();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter by status' }), 'open');

    expect(await screen.findByRole('link', { name: 'Beta Breach' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Delta Campaign' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Gamma Leak' })).not.toBeInTheDocument();
    expect(text()).toContain('2 of 4 shown · live from PostgreSQL');
  });

  it('searches by name, id or tag', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await caseRows();

    await userEvent.type(screen.getByRole('textbox', { name: 'Search cases' }), 'gamma');

    expect(await screen.findByRole('link', { name: 'Gamma Leak' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(text()).toContain('1 of 4 shown · live from PostgreSQL');
  });

  it('applies the filters carried in the query string on first render', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage('/cases?priority=critical&status=active');
    await caseRows();

    expect(screen.getByRole('combobox', { name: 'Filter by priority' })).toHaveValue('critical');
    expect(screen.getByRole('combobox', { name: 'Filter by status' })).toHaveValue('active');
    expect(screen.getByRole('link', { name: 'Alpha Marketplace' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Beta Breach' })).not.toBeInTheDocument();
    expect(text()).toContain('1 of 4 shown · live from PostgreSQL');
  });

  it('filters by the SLA state the Command Center deep-links with', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage('/cases?sla=breached');
    await caseRows();

    expect(screen.getByRole('combobox', { name: 'Filter by SLA state' })).toHaveValue('breached');
    expect(screen.getByRole('link', { name: 'Beta Breach' })).toBeInTheDocument();
    expect(text()).toContain('1 of 4 shown · live from PostgreSQL');
  });

  it('filters unassigned investigations from the URL', async () => {
    installFetch(async () =>
      jsonResponse(
        CASES.map((row, index) => (index === 0 ? { ...row, assigned_to: 'user-1' } : row)),
      ),
    );

    renderPage('/cases?unassigned=true');
    await caseRows();

    expect(screen.queryByRole('link', { name: 'Alpha Marketplace' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Beta Breach' })).toBeInTheDocument();
    expect(text()).toContain('3 of 4 shown · live from PostgreSQL');
  });

  it('sorts by a deep-linked sort key', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage('/cases?sort=queue');
    await caseRows();

    expect(screen.getByRole('combobox', { name: 'Sort cases' })).toHaveValue('queue');
    const names = [...(await caseRows())].map((row) => row.textContent ?? '');
    expect(names[0] ?? '').toContain('Alpha Marketplace');
  });

  it('expands a row to show why the case is prioritised', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await caseRows();

    const toggle = screen.getByRole('button', { name: /Show why Alpha Marketplace is prioritised/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(toggle);

    expect(await screen.findByText('Critical triage priority')).toBeInTheDocument();
    expect(screen.getByText(/queue score 82\.5/)).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('reads a legacy queue payload without inventing numbers', async () => {
    const legacy = CASES.map((row) => {
      const { sla_state, reasons, queue_score, queue_reason, ...rest } = row;
      void sla_state;
      void reasons;
      void queue_score;
      void queue_reason;
      return rest as unknown as CaseQueueEntry;
    });
    installFetch(async () => jsonResponse(legacy));

    renderPage();
    await caseRows();

    expect(screen.getByRole('link', { name: 'Alpha Marketplace' })).toBeInTheDocument();
    expect(text()).toContain('unscored');
    expect(screen.getAllByText('no deadline set').length).toBeGreaterThan(0);
    // A case with no reported reasons must say so rather than show an empty score.
    await userEvent.click(screen.getByRole('button', { name: /Show why Alpha Marketplace is prioritised/ }));
    expect(await screen.findByText(/no priority reasons for this case/)).toBeInTheDocument();
  });

  it('keeps the new-investigation dialog posting to the cases endpoint', async () => {
    const fetchMock = installFetch(async (input) => {
      if (String(input).endsWith('/api/v1/dashboard/cases')) return jsonResponse([]);
      if (String(input).endsWith('/api/v1/cases')) return jsonResponse(entry({ case_id: 'new', name: 'Nightfall' }));
      return jsonResponse({});
    });

    renderPage();
    await screen.findByText('No investigations yet');

    await userEvent.click(screen.getByRole('button', { name: '+ New investigation' }));
    await userEvent.type(screen.getByLabelText('Name (required)'), 'Operation Nightfall');
    await userEvent.click(screen.getByRole('button', { name: 'Create investigation' }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (call) => String(call[0]).endsWith('/api/v1/cases') && call[1]?.method === 'POST',
        ),
      ).toBe(true);
    });
  });

  it('inspects a case in place instead of navigating away', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderRouted('/cases');
    await caseRows();

    expect(rail()).toBeNull();

    const row = (await caseRows())[0];
    await userEvent.click(row as HTMLElement);

    const panel = await screen.findByRole('complementary', { name: 'Alpha Marketplace' });
    // The register is still behind the rail: selection replaced nothing.
    expect(screen.getByRole('link', { name: 'Gamma Leak' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/cases?inspect=case-c1');
    // The facts the rail is required to carry, all read from the API payload.
    expect(panel).toHaveTextContent('82.5');
    expect(panel).toHaveTextContent('Critical triage priority');
    expect(panel).toHaveTextContent('case-c1');
    expect(screen.getByRole('link', { name: 'Open investigation →' })).toHaveAttribute(
      'href',
      '/cases/case-c1',
    );
    expect(rail()).toHaveAttribute('data-open', 'true');
    void row;
  });

  it('marks the inspected row as the selected one', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage();
    await caseRows();

    await userEvent.click((await caseRows())[1] as HTMLElement);

    await waitFor(() => {
      expect(screen.getByRole('complementary', { name: 'Beta Breach' })).toBeInTheDocument();
    });
    const selected = (await caseRows()).filter((row) => row.getAttribute('aria-selected') === 'true');
    expect(selected).toHaveLength(1);
    expect(selected[0]?.textContent).toContain('Beta Breach');
  });

  it('still opens the workspace from the case name link', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderRouted('/cases');
    await caseRows();

    await userEvent.click(screen.getByRole('link', { name: 'Alpha Marketplace' }));

    expect(await screen.findByText('Case workspace')).toBeInTheDocument();
  });

  it('restores the inspected case from the inspect query parameter', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderPage('/cases?inspect=case-c3');
    await caseRows();

    expect(await screen.findByRole('complementary', { name: 'Gamma Leak' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open investigation →' })).toHaveAttribute(
      'href',
      '/cases/case-c3',
    );
  });

  it('walks the register with the arrow keys and selects with Enter', async () => {
    installFetch(async () => jsonResponse(CASES));

    renderRouted('/cases');
    const all = await caseRows();

    all[0]?.focus();
    await userEvent.keyboard('{ArrowDown}{ArrowDown}');
    expect(all[2]).toHaveFocus();

    await userEvent.keyboard('{Enter}');

    const panel = await screen.findByRole('complementary', { name: 'Gamma Leak' });
    expect(panel).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/cases?inspect=case-c3');
  });

  it('closes the rail on Escape and returns focus to the register', async () => {    installFetch(async () => jsonResponse(CASES));

    renderRouted('/cases');
    await caseRows();

    const row = (await caseRows())[0] as HTMLElement;
    await userEvent.click(row);
    await screen.findByRole('complementary', { name: 'Alpha Marketplace' });

    await userEvent.keyboard('{Escape}');

    await waitFor(() => {
      expect(rail()).toBeNull();
    });
    expect(screen.getByTestId('location')).not.toHaveTextContent('inspect');
    // Focus came back to where it was, so the analyst is not dropped at the top.
    expect(row).toHaveFocus();
  });
});

/** Compile-time guard: the filter unions must stay in step with the types. */
const _status: CaseStatus = 'active';
const _priority: CasePriority = 'critical';
const _sla: SlaState = 'at_risk';
void _status;
void _priority;
void _sla;
