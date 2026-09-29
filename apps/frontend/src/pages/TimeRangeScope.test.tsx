import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, beforeEach } from 'vitest';
import { CasesPage } from './CasesPage';
import { CollectionPage } from './CollectionPage';
import { TimeRangeControl } from '../components/TimeRangeControl';
import { TimeRangeProvider } from '../store/TimeRange';
import { installFetch, jsonResponse } from '../test/mockFetch';
import type { CaseQueueEntry } from '../api/types';

/**
 * The requirement is not "the rows are filtered" — it is that the page says
 * what the window did. A register that quietly drops 2,676 rows beside a count
 * reading like the whole picture is the failure these tests exist to catch, so
 * both halves are asserted: the rows that go, and the sentence that says they
 * went, and who did it.
 */

const NOW = Date.now();
const hoursAgo = (hours: number) => new Date(NOW - hours * 3_600_000).toISOString();

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
    counts: { evidence: 0, entities: 0, relationships: 0, assessments: 0, contradictions: 0, recent_evidence: 0 },
    last_activity: hoursAgo(2),
    attribution: null,
    ...overrides,
  };
}

const CASES: CaseQueueEntry[] = [
  entry({ case_id: 'c1', name: 'Fresh Lead', queue_score: 90 }),
  entry({ case_id: 'c2', name: 'Older Lead', last_activity: hoursAgo(24 * 30) }),
  // Never worked on: nothing about it places it inside a window, so it is
  // excluded and counted rather than presented as if it were inside one.
  entry({ case_id: 'c3', name: 'Untouched Case', last_activity: null }),
];

function renderRegister(node: JSX.Element, initialEntry = '/cases') {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <TimeRangeProvider>
        <TimeRangeControl />
        {node}
      </TimeRangeProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // The window persists, which is the point of it; a test that inherits the
  // previous test's window is not testing what it thinks it is.
  localStorage.clear();
});

describe('the investigations register under a window', () => {
  it('shows the whole register, and says no window is applied', async () => {
    installFetch(async () => jsonResponse(CASES));
    renderRegister(<CasesPage />);
    await screen.findByRole('link', { name: 'Fresh Lead' });

    expect(screen.getByRole('link', { name: 'Older Lead' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Untouched Case' })).toBeInTheDocument();
    // No window applied: nothing is claimed, rather than a reassurance that
    // would be false the moment an analyst narrowed it.
    expect(screen.queryByTestId('tr-notice')).toBeNull();
  });

  it('narrows by last activity and states the window, both counts and the basis', async () => {
    installFetch(async () => jsonResponse(CASES));
    renderRegister(<CasesPage />);
    await screen.findByRole('link', { name: 'Fresh Lead' });

    await userEvent.click(screen.getByRole('radio', { name: /^7d/ }));

    await waitFor(() =>
      expect(screen.queryByRole('link', { name: 'Older Lead' })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole('link', { name: 'Fresh Lead' })).toBeInTheDocument();

    const notice = screen.getByTestId('tr-notice');
    expect(notice).toHaveTextContent('Last 7 days — 1 of 3 in window.');
    // The endpoint takes no time bound, so a sentence that let the reader
    // assume the server did it would be a false claim about provenance.
    expect(notice).toHaveTextContent('in the browser over 3 loaded records');
    expect(notice).toHaveTextContent('GET /v1/dashboard/cases takes no time bound');
    // The record with no activity is accounted for rather than vanishing.
    expect(notice).toHaveTextContent('carry no timestamp');
    // The register's own footer carries the count too, so the numbers beside
    // the rows cannot disagree with the sentence above them.
    expect(screen.getByText('1 of 3 in window · Last 7 days')).toBeInTheDocument();
  });

  it('does not claim an empty window is an all-clear', async () => {
    installFetch(async () => jsonResponse(CASES.map((row) => ({ ...row, last_activity: hoursAgo(24 * 90) }))));
    renderRegister(<CasesPage />);
    await screen.findByRole('link', { name: 'Fresh Lead' });

    await userEvent.click(screen.getByRole('radio', { name: /^24h/ }));

    expect(await screen.findByText(/No matches/)).toBeInTheDocument();
    expect(document.body.textContent).toContain('inside Last 24 hours');
  });
});

describe('the collection run log under a window', () => {
  it('sends the window to the server, which already bounds the log by started_at', async () => {
    const fetchMock = installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/collection/jobs')) {
        return jsonResponse([
          {
            job_id: 'j1',
            source_id: 's1',
            source_name: 'Forum',
            source_type: 'forum',
            collector_name: 'crawl',
            collector_version: '1.0.0',
            status: 'completed',
            candidates: 3,
            records: 2,
            errors: 0,
            error_samples: [],
            duration_seconds: 1.5,
            independence_group: null,
            reliability: null,
            synthetic: false,
            started_at: hoursAgo(1),
            finished_at: hoursAgo(1),
          },
        ]);
      }
      if (url.includes('/collection/status')) return jsonResponse(null);
      if (url.includes('/collection/sources')) return jsonResponse([]);
      return jsonResponse({});
    });

    renderRegister(<CollectionPage />, '/collection?tab=jobs');
    await screen.findByText('crawl');

    await userEvent.click(screen.getByRole('radio', { name: /^7d/ }));

    // A query, not a slice: the parameter is on the request.
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((item) => String(item[0]));
      const jobCalls = urls.filter((url) => url.includes('/collection/jobs'));
      const latest = jobCalls[jobCalls.length - 1] ?? '';
      expect(latest).toContain('since=');
    });
    const notice = screen.getByTestId('tr-notice');
    expect(notice).toHaveTextContent('by the server, on GET /v1/collection/jobs');
    // The log is paged, so the unfiltered register size is not claimed.
    expect(notice).toHaveTextContent('paged at 60 runs');
    expect(notice).toHaveTextContent('does not return an unfiltered total');
  });
});
