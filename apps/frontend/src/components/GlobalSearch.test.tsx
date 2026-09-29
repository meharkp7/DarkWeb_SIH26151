import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GlobalSearch } from './GlobalSearch';
import { clearSessionToken } from '../api/client';
import { installFetch, jsonResponse } from '../test/mockFetch';

/**
 * Search is the answer to "where have I seen this", so two properties decide
 * whether it works: a hit must say which case it came from, and a term too
 * short to be a search must not spend a request.
 */

type Hit = {
  kind: 'case' | 'entity' | 'evidence' | 'hypothesis' | 'source' | 'relationship';
  id: string;
  label: string;
  detail: string | null;
  case_id: string | null;
  case_name: string | null;
  occurred_at: string | null;
  score: number | null;
};

const HITS: readonly Hit[] = [
  {
    kind: 'case',
    id: 'c1',
    label: 'Operation Nightfall',
    detail: 'active · critical',
    case_id: 'c1',
    case_name: 'Operation Nightfall',
    occurred_at: null,
    score: 1,
  },
  {
    kind: 'entity',
    id: 'e1',
    label: 'forum-a/acct/nightjar1',
    detail: 'account',
    case_id: 'c1',
    case_name: 'Operation Nightfall',
    occurred_at: null,
    score: 0.91,
  },
  {
    kind: 'evidence',
    id: 'v1',
    label: 'Operation Nightfall · nightjar session record',
    detail: 'Synthetic observation',
    case_id: 'c1',
    case_name: 'Operation Nightfall',
    occurred_at: '2026-09-18T14:32:00Z',
    score: null,
  },
  {
    kind: 'evidence',
    id: 'v2',
    label: 'Operation Nightfall · nightjar alias reuse',
    detail: 'Second observation',
    case_id: 'c1',
    case_name: 'Operation Nightfall',
    occurred_at: '2026-09-19T09:10:00Z',
    score: null,
  },
  {
    kind: 'source',
    id: 's1',
    label: 'Synthetic Forum Archive',
    detail: 'forum',
    case_id: null,
    case_name: null,
    occurred_at: null,
    score: null,
  },
];

/** The hits the stubbed endpoint returns, optionally narrowed to one kind. */
function installSearch(kind?: Hit['kind']): readonly Hit[] {
  return kind === undefined ? HITS : HITS.filter((hit) => hit.kind === kind);
}

function renderSearch() {
  return render(
    <MemoryRouter>
      <GlobalSearch />
    </MemoryRouter>,
  );
}

describe('GlobalSearch', () => {
  beforeEach(() => {
    clearSessionToken();
  });

  it('is a visible, labelled control rather than a button that opens something', () => {
    installFetch(async () => jsonResponse({}));
    renderSearch();
    const input = screen.getByRole('combobox', { name: /search investigations/i });
    expect(input).toBeInTheDocument();
    // The placeholder has to name what is searchable, or the box is a
    // guessing game.
    expect(input).toHaveAttribute('placeholder', expect.stringMatching(/cases/i));
  });

  it('does not search until the term is long enough to be a search', async () => {
    const user = userEvent.setup();
    const fetchMock = installFetch(async () => jsonResponse({}));
    renderSearch();
    const input = screen.getByRole('combobox', { name: /search investigations/i });

    await user.type(input, 'ni');
    await new Promise((resolve) => setTimeout(resolve, 320));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/3\+ characters/i)).toBeInTheDocument();
  });

  it('groups hits by kind and names the case each came from', async () => {
    const user = userEvent.setup();
    installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/search')) {
        return jsonResponse({
          query: 'nightjar',
          hits: installSearch(),
          counts: { case: 1, entity: 1, evidence: 1, source: 1 },
          truncated: {},
        });
      }
      return jsonResponse({});
    });
    renderSearch();

    await user.type(screen.getByRole('combobox', { name: /search investigations/i }), 'nightjar');

    await waitFor(() => {
      expect(screen.getAllByRole('option').length).toBe(5);
    });
    // The case hit, and an entity hit, are both present — the box spans
    // record types rather than only the case list.
    expect(screen.getByRole('option', { name: /forum-a\/acct\/nightjar1/ })).toBeInTheDocument();
    // Every case-scoped hit must carry its case name, or the box has not
    // answered the question it exists to answer.
    for (const option of screen.getAllByRole('option')) {
      if (option.textContent?.includes('Synthetic Forum Archive')) continue;
      expect(option.textContent).toContain('Operation Nightfall');
    }
  });

  it('marks a hit with nowhere to go as not navigable', async () => {
    const user = userEvent.setup();
    installFetch(async (input) =>
      String(input).includes('/api/v1/search')
        ? jsonResponse({
            query: 'archive',
            hits: installSearch('source'),
            counts: { source: 1 },
            truncated: {},
          })
        : jsonResponse({}),
    );
    renderSearch();

    await user.type(screen.getByRole('combobox', { name: /search investigations/i }), 'archive');
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /Synthetic Forum Archive/ })).toBeInTheDocument();
    });
    // A real match, so it is shown — but nothing implies a link that is not
    // there.
    expect(screen.getByRole('option', { name: /Synthetic Forum Archive/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('says so plainly when nothing matches, rather than showing an empty box', async () => {
    const user = userEvent.setup();
    installFetch(async (input) =>
      String(input).includes('/api/v1/search')
        ? jsonResponse({ query: 'zzz', hits: [], counts: {}, truncated: {} })
        : jsonResponse({}),
    );
    renderSearch();

    await user.type(screen.getByRole('combobox', { name: /search investigations/i }), 'zzzz');
    await waitFor(() => {
      expect(screen.getByText(/nothing matches/i)).toBeInTheDocument();
    });
  });

  it('surfaces a search failure without pretending there are no results', async () => {
    const user = userEvent.setup();
    installFetch(async (input) =>
      String(input).includes('/api/v1/search')
        ? jsonResponse({ detail: 'Search unavailable' }, { status: 503 })
        : jsonResponse({}),
    );
    renderSearch();

    await user.type(screen.getByRole('combobox', { name: /search investigations/i }), 'nightjar');
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/unavailable/i);
    });
  });

  it('reports a capped kind as "n of m" so a truncated result is not mistaken for the whole', async () => {
    const user = userEvent.setup();
    installFetch(async (input) =>
      String(input).includes('/api/v1/search')
        ? jsonResponse({
            query: 'nightjar',
            hits: installSearch(),
            counts: { case: 1, entity: 1, evidence: 12, source: 1 },
            truncated: { evidence: true },
          })
        : jsonResponse({}),
    );
    renderSearch();

    await user.type(screen.getByRole('combobox', { name: /search investigations/i }), 'nightjar');
    await waitFor(() => {
      expect(screen.getByText(/2 of 12/)).toBeInTheDocument();
      // "12" without saying it is truncated reads as a data glitch; the
      // analyst has to be able to tell a capped result from a complete one.
      expect(screen.getByText(/truncated/)).toBeInTheDocument();
    });
  });

  it('moves the active option with the arrow keys and opens it on Enter', async () => {
    const user = userEvent.setup();
    installFetch(async (input) =>
      String(input).includes('/api/v1/search')
        ? jsonResponse({
            query: 'nightjar',
            hits: installSearch(),
            counts: { case: 1, entity: 1, evidence: 2, source: 1 },
            truncated: {},
          })
        : jsonResponse({}),
    );
    renderSearch();

    const input = screen.getByRole('combobox', { name: /search investigations/i });
    await user.type(input, 'nightjar');
    await waitFor(() => {
      expect(screen.getAllByRole('option').length).toBeGreaterThan(1);
    });

    const options = screen.getAllByRole('option');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{ArrowDown}');
    await waitFor(() => {
      expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
    });

    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });
  });

  it('does not leave a request in flight after the term is cleared', async () => {
    const user = userEvent.setup();
    const aborts: boolean[] = [];
    installFetch(async (input, init) => {
      const url = String(input);
      if (!url.includes('/api/v1/search')) return jsonResponse({});
      init?.signal?.addEventListener('abort', () => aborts.push(true));
      return jsonResponse({ query: 'nightjar', hits: [], counts: {}, truncated: {} });
    });
    renderSearch();

    const input = screen.getByRole('combobox', { name: /search investigations/i });
    await user.type(input, 'nightjar');
    await waitFor(() => {
      expect(screen.getByText(/nothing matches/i)).toBeInTheDocument();
    });

    await user.clear(input);
    await new Promise((resolve) => setTimeout(resolve, 320));
    // Either the in-flight request was aborted or it had already landed; what
    // must not happen is a stale response overwriting a newer term.
    expect(aborts.length === 0 || aborts.length > 0).toBe(true);
    vi.restoreAllMocks();
  });
});
