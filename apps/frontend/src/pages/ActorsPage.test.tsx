import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ActorsPage } from './ActorsPage';
import type { ActorRegistryRow, ActorSummary } from '../api/types';
import { installFetch, jsonResponse } from '../test/mockFetch';

function actor(overrides: Partial<ActorRegistryRow> & Pick<ActorRegistryRow, 'actor_id' | 'handle'>): ActorRegistryRow {
  return {
    category: 'drugs',
    status: 'active',
    confidence: 0.82,
    first_seen: '2026-01-04T00:00:00Z',
    last_seen: '2026-09-20T00:00:00Z',
    last_scan_at: '2026-09-25T00:00:00Z',
    source_id: 'src-1',
    source_name: 'Synthetic Marketplace Mirror',
    identifier_count: 2,
    marketplace_count: 1,
    case_link_count: 0,
    identifier_kinds: { handle: 1, onion: 1 },
    notes: null,
    ...overrides,
  };
}

const ACTORS: ActorRegistryRow[] = [
  actor({ actor_id: 'actor-1', handle: 'amberlight1supply', confidence: 0.82 }),
  // The row the "unassessed" behaviour is about.
  actor({
    actor_id: 'actor-2',
    handle: 'ironmoss_cell',
    category: 'arms',
    status: 'dormant',
    confidence: null,
    identifier_count: 4,
    marketplace_count: 3,
    identifier_kinds: { handle: 1, pgp: 1, wallet: 1, onion: 1 },
    source_name: null,
  }),
  actor({
    actor_id: 'actor-3',
    handle: 'quietpineunit',
    category: 'extortion',
    status: 'retired',
    confidence: 0.31,
    last_scan_at: null,
  }),
];

const SUMMARY: ActorSummary = {
  total: 3,
  by_status: [
    { status: 'active', count: 1 },
    { status: 'dormant', count: 1 },
    { status: 'retired', count: 1 },
  ],
  by_category: [
    { category: 'drugs', count: 1 },
    { category: 'arms', count: 1 },
    { category: 'extortion', count: 1 },
  ],
  identifier_kinds: [
    { kind: 'handle', count: 3 },
    { kind: 'onion', count: 2 },
    { kind: 'pgp', count: 1 },
    { kind: 'wallet', count: 1 },
  ],
  identifiers: 7,
  marketplaces: 5,
  stale_days: 30,
  stale: 1,
  unassessed: 1,
};

const CATEGORIES = SUMMARY.by_category;

/**
 * The register fires three requests — the filtered list, the summary and the
 * category vocabulary. Stubbed per-URL rather than returning one body for
 * everything, so a test can tell a wrong URL from a wrong payload.
 */
function installRegistryFetch(rows: ActorRegistryRow[] = ACTORS) {
  return installFetch(async (input) => {
    const url = String(input);
    if (url.includes('/v1/actors/summary')) return jsonResponse(SUMMARY);
    if (url.includes('/v1/actors/categories')) return jsonResponse(CATEGORIES);
    if (url.includes('/v1/actors')) return jsonResponse(rows);
    throw new Error(`Unexpected request: ${url}`);
  });
}

function renderPage(initialEntry = '/actors'): void {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ActorsPage />
    </MemoryRouter>,
  );
}

function renderRouted(initialEntry: string): void {
  function Probe() {
    const location = useLocation();
    return <span data-testid="location">{location.pathname + location.search}</span>;
  }
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/actors"
          element={
            <>
              <ActorsPage />
              <Probe />
            </>
          }
        />
        <Route path="/actors/:actorId" element={<p>Actor profile</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Body rows only — the header row is not an actor. */
async function bodyRows(): Promise<HTMLElement[]> {
  const rows = await screen.findAllByRole('row');
  return rows.filter((row) => row.closest('tbody') !== null);
}

function text(): string {
  return document.body.textContent ?? '';
}

describe('ActorsPage', () => {
  it('renders one dense table row per actor the API returned', async () => {
    installRegistryFetch();
    renderPage();

    const rows = await bodyRows();
    expect(rows).toHaveLength(3);
    for (const handle of ['amberlight1supply', 'ironmoss_cell', 'quietpineunit']) {
      expect(screen.getByRole('link', { name: handle })).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'amberlight1supply' })).toHaveAttribute(
      'href',
      '/actors/actor-1',
    );
    expect(text()).toContain('3 of 3 shown');
  });

  it('states every figure on screen says what it counts', async () => {
    installRegistryFetch();
    renderPage();

    // The lead sentence is a claim about how the numbers were produced, so it is
    // asserted as content rather than left to exist.
    await screen.findByRole('grid', { name: 'Actor registry' });
    expect(text()).toContain('distinct investigations citing one of this actor');

    const caption = screen.getByText(/Actor registry: 3 of 3 actors/);
    expect(caption).toHaveClass('sr-only');
  });

  it('never renders an unassessed confidence as zero', async () => {
    installRegistryFetch();
    renderPage();
    await bodyRows();

    const dormant = screen.getByRole('link', { name: 'ironmoss_cell' }).closest('tr');
    expect(dormant).not.toBeNull();
    // The unscored actor reads "Not assessed", not "0%".
    expect(within(dormant as HTMLElement).getByText('Not assessed')).toBeInTheDocument();
    expect(within(dormant as HTMLElement).queryByText('0%')).not.toBeInTheDocument();

    const scored = screen.getByRole('link', { name: 'amberlight1supply' }).closest('tr');
    expect(within(scored as HTMLElement).getByText('82%')).toBeInTheDocument();
    // A recorded score says where it came from.
    expect(within(scored as HTMLElement).getAllByText('Recorded score').length).toBeGreaterThan(0);
  });

  it('marks a never-scanned actor without inventing a threshold', async () => {
    installRegistryFetch();
    renderPage();
    await bodyRows();

    const retired = screen.getByRole('link', { name: 'quietpineunit' }).closest('tr');
    expect(within(retired as HTMLElement).getByText('never scanned')).toBeInTheDocument();
  });

  it('puts filters and sort in the URL, not in component state', async () => {
    const fetchMock = installRegistryFetch();
    const user = userEvent.setup();
    renderRouted('/actors');

    await screen.findByRole('grid', { name: 'Actor registry' });

    await user.type(screen.getByLabelText('Search actors by handle or identifier'), 'nightjar');
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('q=nightjar');
    });

    await user.selectOptions(screen.getByLabelText('Filter by category'), 'drugs');
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('category=drugs');
    });

    // The category the analyst chose has to be one the API actually offered;
    // inventing an option would offer a filter that returns nothing.
    const categorySelect = screen.getByLabelText('Filter by category') as HTMLSelectElement;
    expect(Array.from(categorySelect.options).map((option) => option.value)).toEqual([
      'all',
      'drugs',
      'arms',
      'extortion',
    ]);

    await user.selectOptions(screen.getByLabelText('Minimum attribution confidence'), '0.9');
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('min_confidence=0.9');
    });

    // The *latest* list request carries every filter, rather than the register
    // filtering what the API already sent.
    const latest = fetchMock.mock.calls.map((call) => String(call[0])).at(-1) ?? '';
    expect(latest).toContain('q=nightjar');
    expect(latest).toContain('category=drugs');
    expect(latest).toContain('min_confidence=0.9');
  });

  it('sorts through the address bar with a stated direction', async () => {
    const fetchMock = installRegistryFetch();
    const user = userEvent.setup();
    renderRouted('/actors');

    const grid = await screen.findByRole('grid', { name: 'Actor registry' });
    const handleHeader = within(grid).getByRole('columnheader', { name: /Actor/ });
    expect(handleHeader).toHaveAttribute('aria-sort', 'ascending');

    await user.click(within(handleHeader).getByRole('button', { name: /Actor/ }));
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('dir=desc');
    });
    expect(handleHeader).toHaveAttribute('aria-sort', 'descending');

    // And it reached the API rather than being re-sorted in the browser.
    await waitFor(() => {
      const last = fetchMock.mock.calls.map((call) => String(call[0])).at(-1) ?? '';
      expect(last).toContain('sort=handle');
      expect(last).toContain('dir=desc');
    });
  });

  it('selects a row into the inspector without leaving the register', async () => {
    const user = userEvent.setup();
    installRegistryFetch();
    renderRouted('/actors');

    await screen.findByRole('grid', { name: 'Actor registry' });
    await user.click(screen.getByRole('link', { name: 'amberlight1supply' }).closest('tr') as HTMLElement);

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('inspect=actor-1');
    });
    // The register is still mounted behind the rail — the rail never navigates.
    expect(screen.getByRole('grid', { name: 'Actor registry' })).toBeInTheDocument();
    expect(screen.getByRole('complementary')).toBeInTheDocument();
  });

  it('does not render a rail until something is selected', async () => {
    installRegistryFetch();
    renderPage();
    await bodyRows();
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  });

  it('surfaces the stale and unassessed populations rather than hiding them', async () => {
    installRegistryFetch();
    renderPage();
    await bodyRows();

    expect(text()).toContain('Not scanned in 30d');
    expect(text()).toContain('1 never assessed');
  });

  it('offers the export control and says it carries the active filters', async () => {
    const user = userEvent.setup();
    installRegistryFetch();
    renderPage();
    await bodyRows();

    await user.click(screen.getByRole('button', { name: /Export registry/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Export the actor registry' });
    expect(within(dialog).getByText(/carries the filters currently applied/)).toBeInTheDocument();
    expect(within(dialog).getByRole('radio', { name: /CSV/ })).toBeInTheDocument();
    expect(within(dialog).getByRole('radio', { name: /STIX/ })).toBeInTheDocument();
  });

  it('says the registry is empty rather than showing a header over nothing', async () => {
    installRegistryFetch([]);
    renderPage();

    expect(await screen.findByText('No actors in the registry')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryAllByRole('row')).toHaveLength(0);
    });
  });
});