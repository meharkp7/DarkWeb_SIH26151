import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { TimeRangeControl, TimeRangeNotice } from '../components/TimeRangeControl';
import { TimeRangeProvider, countInWindow, filterByTimeRange, useTimeRange } from './TimeRange';
import type { TimeRangeResult, TimeRangeValue } from './TimeRange';

/**
 * The window is the answer to "what did I learn in the last week", and it has
 * three failure modes worth a test each: a window that resolves to something
 * the analyst did not ask for, a typed range that is silently corrected
 * instead of refused, and a filtered register whose count reads like the whole
 * picture. The fourth is the URL round trip, because a window that cannot be
 * linked cannot be handed to a colleague.
 */

/** Renders the control in a router and reports the address bar it writes. */
function renderControl(initialEntry = '/cases'): () => string {
  let latest = '';
  function Probe() {
    latest = useLocation().search;
    return null;
  }
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <TimeRangeProvider>
        <TimeRangeControl />
        <Probe />
      </TimeRangeProvider>
    </MemoryRouter>,
  );
  return () => latest;
}

/** Renders the store alone and hands back the value it is exposing. */
function renderStore(initialEntry = '/cases'): { current: TimeRangeValue | null } {
  const seen: { current: TimeRangeValue | null } = { current: null };
  function Probe() {
    seen.current = useTimeRange();
    return null;
  }
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <TimeRangeProvider>
        <Probe />
      </TimeRangeProvider>
    </MemoryRouter>,
  );
  return seen;
}

function group(): HTMLElement {
  return screen.getByRole('radiogroup', { name: 'Time range for all registers' });
}

function segment(name: RegExp): HTMLElement {
  return screen.getByRole('radio', { name });
}

/** The notice, driven by fixed numbers so the wording is the assertion. */
function NoticeProbe() {
  return (
    <TimeRangeNotice
      window="Last 7 days"
      shown={1204}
      total={3880}
      basis="in the browser over 3,880 loaded records"
    />
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe('the time range store', () => {
  it('reports no window applied until one is chosen', () => {
    const seen = renderStore().current;

    expect(seen?.isActive).toBe(false);
    expect(seen?.from).toBeNull();
    expect(seen?.to).toBeNull();
    // `undefined`, not an empty string: a page with no window must be able to
    // omit the parameter rather than send a bound of nothing.
    expect(seen?.isoFrom).toBeUndefined();
    expect(seen?.isoTo).toBeUndefined();
    expect(seen?.label).toBe('All time');
  });

  it('resolves a preset into a bound and a spelled-out label', () => {
    const seen = renderStore();
    act(() => seen.current?.setWindow('7d'));

    expect(seen.current?.isActive).toBe(true);
    expect(seen.current?.label).toBe('Last 7 days');
    // A preset has no upper bound: "last 7 days" ends at now, not at midnight.
    expect(seen.current?.to).toBeNull();
    expect(seen.current?.isoTo).toBeUndefined();
    expect(seen.current?.isoFrom).toEqual(expect.any(String));
    const days = (Date.now() - (seen.current?.from?.getTime() ?? 0)) / 86_400_000;
    expect(days).toBeGreaterThan(6.9);
    expect(days).toBeLessThan(7.1);
  });

  it('refuses a range it cannot query and leaves the window in force alone', () => {
    const seen = renderStore();
    act(() => seen.current?.setWindow('7d'));

    const verdicts: TimeRangeResult[] = [];
    act(() => {
      const verdict = seen.current?.applyCustom('2026-03-19', '2026-03-12');
      if (verdict !== undefined) verdicts.push(verdict);
    });

    const verdict = verdicts[0] as TimeRangeResult;
    expect(verdict.ok).toBe(false);
    // The point of the rule: a window the analyst did not ask for is never
    // substituted, reordered or clamped on their behalf.
    expect(seen.current?.label).toBe('Last 7 days');
    if (!verdict.ok) expect(verdict.reason).toMatch(/after the end date/);
  });

  it('refuses an empty range and accepts a one-sided one', () => {
    const seen = renderStore();
    act(() => {
      expect(seen.current?.applyCustom('', '').ok).toBe(false);
    });
    act(() => {
      expect(seen.current?.applyCustom('2026-03-12', '').ok).toBe(true);
    });

    expect(seen.current?.label).toBe('Since 12 Mar 2026');
    expect(seen.current?.from).toBeInstanceOf(Date);
    expect(seen.current?.to).toBeNull();
  });

  it('adopts the window a link arrived with, on the first render', () => {
    // Read in the initialiser, not in an effect: a link that scopes the second
    // render instead of the first shows the analyst the whole register for a
    // frame, and nothing on screen says so.
    const seen = renderStore('/cases?range=7d');
    expect(seen.current?.window).toBe('7d');
    expect(seen.current?.isActive).toBe(true);
  });

  it('prefers a stored window over nothing, and a link over both', () => {
    localStorage.setItem('aegis.timeRange', JSON.stringify({ window: '30d' }));
    expect(renderStore().current?.window).toBe('30d');
    expect(renderStore('/cases?range=90d').current?.window).toBe('90d');
  });

  it('does not let a date JavaScript would roll over pass as a day', () => {
    const seen = renderStore();
    act(() => {
      expect(seen.current?.applyCustom('2026-02-31', '').ok).toBe(false);
    });
    expect(seen.current?.isActive).toBe(false);
  });

  it('names the two ends of a typed range', () => {
    const seen = renderStore();
    act(() => {
      seen.current?.applyCustom('2026-03-12', '2026-03-19');
    });

    expect(seen.current?.label).toBe('12 Mar – 19 Mar 2026');
    expect(seen.current?.window).toBe('all');
    expect(seen.current?.isActive).toBe(true);
  });
});

describe('narrowing already-loaded rows', () => {
  const rows = [
    { id: 'a', at: '2026-03-18T09:00:00Z' },
    { id: 'b', at: '2026-03-01T09:00:00Z' },
    { id: 'c', at: null },
    { id: 'd', at: 'not a date' },
  ];

  it('leaves everything alone when no window is applied', () => {
    const result = filterByTimeRange(rows, (row) => row.at, null, null);
    expect(result.rows).toHaveLength(4);
    expect(result.undated).toBe(0);
  });

  it('counts a record with no usable date apart rather than folding it in', () => {
    const result = filterByTimeRange(
      rows,
      (row) => row.at,
      new Date('2026-03-10T00:00:00Z'),
      new Date('2026-03-20T00:00:00Z'),
    );

    expect(result.rows.map((row) => row.id)).toEqual(['a']);
    expect(result.total).toBe(4);
    // Nothing about an undated record places it in a window, so it is neither
    // listed nor quietly counted as out.
    expect(result.undated).toBe(2);
  });

  it('reads a preset as open-ended above, so a record stamped now is inside', () => {
    const fresh = [
      { id: 'now', at: new Date().toISOString() },
      { id: 'old', at: '2026-03-18T09:00:00Z' },
    ];
    const result = filterByTimeRange(fresh, (row) => row.at, new Date(Date.now() - 1000), null);
    expect(result.rows.map((row) => row.id)).toEqual(['now']);
  });

  it('states the filtered count against the unfiltered one', () => {
    expect(countInWindow(1204, 3880)).toBe('1,204 of 3,880 in window');
    // A page that cannot produce the denominator says so rather than inventing
    // one — an invented one is the failure this whole thing exists to prevent.
    expect(countInWindow(1204, null)).toBe('1,204 in window');
  });
});

describe('the topbar control', () => {
  it('names what it scopes rather than what it is called', () => {
    renderControl();
    expect(group()).toBeInTheDocument();
  });

  it('marks the chosen window in a way that is not colour alone', async () => {
    renderControl();
    await userEvent.click(segment(/^30d/));

    const chosen = segment(/^30d/);
    expect(chosen).toHaveAttribute('aria-checked', 'true');
    expect(chosen.className).toContain('is-on');
    // The rule under the segment is a shape, so the selection survives a
    // greyscale read and a colourblind analyst alike.
    expect(chosen.querySelector('.tr-seg__mark')).not.toBeNull();
    expect(segment(/^7d/)).toHaveAttribute('aria-checked', 'false');
  });

  it('moves between windows with the arrow keys and wraps at both ends', async () => {
    renderControl();
    segment(/^24h/).focus();

    await userEvent.keyboard('{ArrowRight}');
    expect(segment(/^7d/)).toHaveFocus();
    expect(segment(/^7d/)).toHaveAttribute('aria-checked', 'true');

    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}');
    // Wrapping, so there is no dead end in either direction.
    expect(segment(/^All/)).toHaveFocus();
    expect(segment(/^All/)).toHaveAttribute('aria-checked', 'true');

    await userEvent.keyboard('{Home}');
    expect(segment(/^24h/)).toHaveAttribute('aria-checked', 'true');
    await userEvent.keyboard('{End}');
    expect(segment(/^All/)).toHaveAttribute('aria-checked', 'true');
  });

  it('keeps one tab stop for the whole group', () => {
    renderControl();
    const stops = screen
      .getAllByRole('radio')
      .filter((item) => item.getAttribute('tabindex') === '0');
    expect(stops).toHaveLength(1);
  });

  it('writes the window into the address bar, so a view can be linked', async () => {
    const search = renderControl();
    await userEvent.click(segment(/^90d/));
    await waitFor(() => expect(search()).toContain('range=90d'));
  });

  it('leaves the address bar alone when the window is all time', () => {
    const search = renderControl();
    expect(search()).not.toContain('range');
  });

  it('adopts the window a link arrived with', () => {
    renderControl('/cases?range=7d');
    expect(segment(/^7d/)).toHaveAttribute('aria-checked', 'true');
  });

  it('drops a window the address bar asks for but the platform cannot query', () => {
    // A hand-edited or stale link must not become a window nobody chose.
    renderControl('/cases?range=custom&range_from=2026-03-19&range_to=2026-03-12');
    expect(segment(/^All/)).toHaveAttribute('aria-checked', 'true');
  });

  it('keeps a register filter in the address bar when the window changes', async () => {
    const search = renderControl('/cases?q=nightjar&status=open');
    await userEvent.click(segment(/^30d/));

    await waitFor(() => {
      expect(search()).toContain('q=nightjar');
      expect(search()).toContain('status=open');
      expect(search()).toContain('range=30d');
    });
  });

  it('refuses an inverted range with a reason instead of correcting it', async () => {
    const search = renderControl();
    await userEvent.click(segment(/^7d/));
    await waitFor(() => expect(search()).toContain('range=7d'));

    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    await userEvent.type(screen.getByLabelText('Range start'), '2026-03-19');
    await userEvent.type(screen.getByLabelText('Range end'), '2026-03-12');
    await userEvent.click(screen.getByRole('button', { name: 'Apply range' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/after the end date/);
    expect(screen.getByLabelText('Range start')).toHaveAttribute('aria-invalid', 'true');
    // The window in force is the one the analyst chose, not a repaired range.
    await waitFor(() => expect(search()).toContain('range=7d'));
  });

  it('applies a typed range and clears it again', async () => {
    const search = renderControl();
    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    await userEvent.type(screen.getByLabelText('Range start'), '2026-03-12');
    await userEvent.type(screen.getByLabelText('Range end'), '2026-03-19');
    await userEvent.click(screen.getByRole('button', { name: 'Apply range' }));

    await waitFor(() => {
      expect(search()).toContain('range=custom');
      expect(search()).toContain('range_from=2026-03-12');
      expect(search()).toContain('range_to=2026-03-19');
    });
    // A typed range shows as a checked segment of its own, and leaves no
    // preset looking like the window that is in force.
    const checked = screen.getAllByRole('radio').filter((item) => item.getAttribute('aria-checked') === 'true');
    expect(checked).toHaveLength(1);
    expect(segment(/^Custom/)).toHaveAttribute('aria-checked', 'true');
    expect(segment(/^7d/)).toHaveAttribute('aria-checked', 'false');

    await userEvent.click(screen.getByRole('button', { name: 'Hide custom range' }));
    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear window' }));

    await waitFor(() => expect(search()).not.toContain('range'));
    expect(segment(/^All/)).toHaveAttribute('aria-checked', 'true');
  });
});

describe('what a register says about the window', () => {
  it('says nothing at all when no window is applied', () => {
    render(
      <MemoryRouter>
        <TimeRangeProvider>
          <NoticeProbe />
        </TimeRangeProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId('tr-notice')).toBeNull();
  });

  it('states the window, both counts and how the narrowing was done', async () => {
    render(
      <MemoryRouter>
        <TimeRangeProvider>
          <TimeRangeControl />
          <NoticeProbe />
        </TimeRangeProvider>
      </MemoryRouter>,
    );
    await userEvent.click(segment(/^7d/));

    const notice = await screen.findByTestId('tr-notice');
    expect(notice).toHaveTextContent('Last 7 days — 1,204 of 3,880 in window.');
    // The failure this exists to prevent: a filtered list beside a count that
    // reads like the whole register.
    expect(notice).toHaveTextContent('Filtered in the browser over 3,880 loaded records.');
  });

  it('refuses to imply a denominator the page could not produce', async () => {
    render(
      <MemoryRouter>
        <TimeRangeProvider>
          <TimeRangeControl />
          <TimeRangeNotice
            window="Last 30 days"
            shown={7}
            total={null}
            basis="by the server, on GET /v1/collection/jobs"
          />
        </TimeRangeProvider>
      </MemoryRouter>,
    );
    await userEvent.click(segment(/^30d/));

    expect(screen.getByTestId('tr-notice')).toHaveTextContent(
      'This endpoint does not return an unfiltered total, so none is stated here.',
    );
  });
});
