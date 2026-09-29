import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ReactNode } from 'react';

/**
 * The window every register on the console is read through.
 *
 * Infrastructure and Personas each grew their own timeline while this was
 * missing, which left an analyst able to ask "what did I learn in the last
 * week" on two pages out of seven. This is the store that makes it one control
 * over all of them: a preset window, or a range the analyst typed, resolved
 * once here so that four pages cannot each resolve "last 7 days" differently.
 *
 * Three decisions are worth stating because they are the ones a reader would
 * otherwise have to reverse-engineer:
 *
 * 1. **A relative window is resolved when the window is chosen, not on a
 *    timer.** A window that re-resolved every minute would change the query
 *    under a register mid-read, and an analyst looking at "1,204 in window"
 *    has to be able to say which 1,204 that was. The trade is that a tab left
 *    open for a day eventually shows a window that has drifted by that much;
 *    re-picking the window — or loading any page that carries `?range=7d` —
 *    re-resolves it.
 * 2. **Day boundaries are the analyst's local midnight**, not UTC's. Someone
 *    who types "1 March" means the 1st of March where they are sitting, and
 *    the ISO strings handed to the API are the same instants the browser-side
 *    comparison uses, so a row can never be counted as inside the window on
 *    one side and outside it on the other.
 * 3. **A record with no timestamp cannot be shown to fall inside a window**,
 *    so it is excluded and counted separately (see {@link filterByTimeRange}).
 *    Including it would be a claim the record's own data cannot support.
 *
 * The provider reads the router, so it must be mounted inside one — as every
 * other component that reads the address bar is. Outside a `<Router>` a
 * register still renders, unscoped: {@link useTimeRange} falls back to the
 * all-time view rather than throwing, so a page on its own is not broken by
 * the absence of the control.
 */

export type TimeWindow = '24h' | '7d' | '30d' | '90d' | 'all';

export const TIME_WINDOWS: readonly TimeWindow[] = ['24h', '7d', '30d', '90d', 'all'];

/** What a segment shows. Short, because the topbar has room for five of them. */
export const TIME_WINDOW_SEGMENTS: Readonly<Record<TimeWindow, string>> = {
  '24h': '24h',
  '7d': '7d',
  '30d': '30d',
  '90d': '90d',
  all: 'All',
};

/** What a lead sentence says. Never abbreviated: "7d" is not a window. */
export const TIME_WINDOW_LABELS: Readonly<Record<TimeWindow, string>> = {
  '24h': 'Last 24 hours',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
  '90d': 'Last 90 days',
  all: 'All time',
};

/**
 * Query-string keys.
 *
 * Deliberately not `from`/`until`: Infrastructure and Persona Linkage each
 * own a `from`/`until` pair bound to a different timestamp, and a global
 * control that wrote those keys would silently rewrite another screen's
 * filter. These three cannot collide with a screen that has its own timeline.
 */
export const RANGE_PARAM = 'range';
export const RANGE_FROM_PARAM = 'range_from';
export const RANGE_TO_PARAM = 'range_to';
/** The `range` value that means "the bounds are in `range_from`/`range_to`". */
export const RANGE_CUSTOM = 'custom';

const STORAGE_KEY = 'aegis.timeRange';

const DAY_MS = 86_400_000;
const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const LONG_DATE = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
const SHORT_DATE = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short' });

/** Window length in days; `null` is "no bound". */
const WINDOW_DAYS: Readonly<Record<TimeWindow, number | null>> = {
  '24h': 1,
  '7d': 7,
  '30d': 30,
  '90d': 90,
  all: null,
};

/** A range the analyst typed, as `YYYY-MM-DD` day strings. Either may be empty. */
export interface TimeRangeCustom {
  readonly from: string;
  readonly to: string;
}

export type TimeRangeResult = { readonly ok: true } | { readonly ok: false; readonly reason: string };

export interface TimeRangeValue {
  readonly window: TimeWindow;
  readonly setWindow: (next: TimeWindow) => void;
  /** The typed range, or null while a preset is in force. */
  readonly custom: TimeRangeCustom | null;
  /**
   * Apply a typed range. A range that is not a range is refused with a reason
   * and the current window is left exactly as it was — never silently clamped
   * or reordered, because a window an analyst did not ask for is a window
   * they will read numbers off without noticing.
   */
  readonly applyCustom: (from: string, to: string) => TimeRangeResult;
  readonly clearCustom: () => void;
  /** The resolved lower bound, or null for an open or unbounded window. */
  readonly from: Date | null;
  /** The resolved upper bound, inclusive to the end of the day, or null. */
  readonly to: Date | null;
  /** ISO strings for a query parameter, or undefined when unbounded. */
  readonly isoFrom: string | undefined;
  readonly isoTo: string | undefined;
  /** Prose, for a lead sentence: "Last 7 days", "12 Mar – 19 Mar 2026". */
  readonly label: string;
  /** False only when nothing is bounded, so a page can drop the parameter. */
  readonly isActive: boolean;
}

interface TimeRangeState {
  readonly window: TimeWindow;
  readonly customFrom: string | null;
  readonly customTo: string | null;
}

const EMPTY_STATE: TimeRangeState = { window: 'all', customFrom: null, customTo: null };

// ---------------------------------------------------------------------------
// Day arithmetic
// ---------------------------------------------------------------------------

/** `YYYY-MM-DD` for a local date, so it round-trips through a date input. */
function dayString(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

/**
 * A real calendar day, or null.
 *
 * `Date` accepts `2026-02-31` and hands back 3 March, so the round trip is the
 * only thing standing between a typo and a window that quietly starts a day
 * later than the analyst typed.
 */
function parseDay(value: string): Date | null {
  const trimmed = value.trim();
  if (!DAY_PATTERN.test(trimmed)) return null;
  // A date-time with no offset is local time, which is the day boundary wanted.
  const parsed = new Date(`${trimmed}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  return dayString(parsed) === trimmed ? parsed : null;
}

/** Local midnight at the start of a `YYYY-MM-DD` day. */
function startOfDay(value: string): Date | null {
  return parseDay(value);
}

/** The last millisecond of a `YYYY-MM-DD` day, so the bound is inclusive. */
function endOfDay(value: string): Date | null {
  const parsed = parseDay(value);
  if (parsed === null) return null;
  parsed.setHours(23, 59, 59, 999);
  return parsed;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/**
 * Whether a typed pair is a range, and if not, why.
 *
 * The reasons are written for the analyst rather than for a log: "you cannot
 * query a window with no ends" is a different sentence from "the start is
 * after the end", and only the second one is fixable by swapping two fields.
 */
export function validateRange(from: string, to: string): TimeRangeResult {
  const start = from.trim();
  const end = to.trim();

  if (start === '' && end === '') {
    return {
      ok: false,
      reason: 'Enter a start date, an end date, or both. An empty range is not a window.',
    };
  }
  if (start !== '' && startOfDay(start) === null) {
    return { ok: false, reason: `${start} is not a date the platform recognises.` };
  }
  if (end !== '' && endOfDay(end) === null) {
    return { ok: false, reason: `${end} is not a date the platform recognises.` };
  }
  if (start !== '' && end !== '' && start > end) {
    return {
      ok: false,
      reason: `The start date (${LONG_DATE.format(startOfDay(start) as Date)}) is after the end date (${LONG_DATE.format(
        startOfDay(end) as Date,
      )}). Swap them, or pick a start that is not later than the end.`,
    };
  }
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Persistence and the URL
// ---------------------------------------------------------------------------

function isTimeWindow(value: unknown): value is TimeWindow {
  return typeof value === 'string' && (TIME_WINDOWS as readonly string[]).includes(value);
}

/**
 * A stored range, or null when there is nothing usable to restore.
 *
 * A stored value that no longer validates is dropped rather than repaired: a
 * range saved by an older build, or hand-edited in devtools, must not become a
 * window nobody chose.
 */
function stateFrom(
  windowValue: unknown,
  fromValue: unknown,
  toValue: unknown,
): TimeRangeState | null {
  if (typeof fromValue === 'string' || typeof toValue === 'string') {
    const from = typeof fromValue === 'string' ? fromValue : '';
    const to = typeof toValue === 'string' ? toValue : '';
    if (!validateRange(from, to).ok) return null;
    // A typed range and a preset are alternatives, not a pair: the typed
    // bounds are the window, so the preset is recorded as "all" and the
    // segmented control shows no segment checked rather than a wrong one.
    return { window: 'all', customFrom: from === '' ? null : from, customTo: to === '' ? null : to };
  }
  return isTimeWindow(windowValue) ? { window: windowValue, customFrom: null, customTo: null } : null;
}

function readStored(): TimeRangeState | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === null) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown> | null;
    if (parsed === null || typeof parsed !== 'object') return null;
    return stateFrom(parsed['window'], parsed['from'], parsed['to']);
  } catch {
    // Not our envelope. An unreadable preference is an absent one.
    return null;
  }
}

/**
 * The range the address bar asks for, or null when it asks for nothing.
 *
 * Read through the router rather than off `window.location`, so the router is
 * the only account of where the analyst is. It is read in the provider's
 * initialiser, not in an effect: a link that arrives with `?range=7d` has to
 * scope the *first* render, or the register fetches the whole history and
 * corrects itself a frame later — and the correction is invisible, which is
 * the same class of failure as a filter that is applied and not stated.
 *
 * A range the address bar cannot be queried by is dropped rather than repaired.
 * A stale or hand-edited link must resolve to all time, not to a window
 * somebody chose by accident.
 */
function readUrl(params: URLSearchParams): TimeRangeState | null {
  const range = params.get(RANGE_PARAM);
  const from = params.get(RANGE_FROM_PARAM);
  const to = params.get(RANGE_TO_PARAM);
  if (range === null && from === null && to === null) return null;
  if (range === RANGE_CUSTOM || from !== null || to !== null) {
    return stateFrom(RANGE_CUSTOM, from ?? '', to ?? '') ?? EMPTY_STATE;
  }
  if (range === 'all' || !isTimeWindow(range)) return EMPTY_STATE;
  return { window: range, customFrom: null, customTo: null };
}

function initialState(params: URLSearchParams): TimeRangeState {
  // A link wins over a stored preference: someone handed over this exact view.
  return readUrl(params) ?? readStored() ?? EMPTY_STATE;
}

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

function resolve(state: TimeRangeState): { from: Date | null; to: Date | null } {
  if (state.customFrom !== null || state.customTo !== null) {
    return {
      from: state.customFrom === null ? null : startOfDay(state.customFrom),
      to: state.customTo === null ? null : endOfDay(state.customTo),
    };
  }
  const days = WINDOW_DAYS[state.window];
  return days === null ? { from: null, to: null } : { from: new Date(Date.now() - days * DAY_MS), to: null };
}

function labelFor(state: TimeRangeState): string {
  if (state.customFrom === null && state.customTo === null) return TIME_WINDOW_LABELS[state.window];
  const from = state.customFrom === null ? null : startOfDay(state.customFrom);
  const to = state.customTo === null ? null : endOfDay(state.customTo);
  if (from !== null && to !== null) {
    return from.getFullYear() === to.getFullYear()
      ? `${SHORT_DATE.format(from)} – ${LONG_DATE.format(to)}`
      : `${LONG_DATE.format(from)} – ${LONG_DATE.format(to)}`;
  }
  if (from !== null) return `Since ${LONG_DATE.format(from)}`;
  if (to !== null) return `Until ${LONG_DATE.format(to)}`;
  return TIME_WINDOW_LABELS[state.window];
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

/** What a window did to a set of already-loaded rows. */
export interface TimeRangeFilter<T> {
  /** The rows that can be shown to fall inside the window. */
  readonly rows: readonly T[];
  /** Every row the page had, filtered or not. */
  readonly total: number;
  /**
   * Rows carrying no usable timestamp. Excluded from `rows`, because nothing
   * about them places them in or out of a window, and reported so the page can
   * say so rather than let the count quietly shrink.
   */
  readonly undated: number;
}

/**
 * Narrow already-loaded rows to the window.
 *
 * `at` reads the timestamp the window is about — the field each register
 * actually means by "when this happened". Rows with no readable timestamp are
 * counted in `undated` and left out, because a record that has never been
 * dated cannot be shown to have happened in the last seven days.
 */
export function filterByTimeRange<T>(
  rows: readonly T[],
  at: (row: T) => string | null | undefined,
  from: Date | null,
  to: Date | null,
): TimeRangeFilter<T> {
  if (from === null && to === null) return { rows, total: rows.length, undated: 0 };

  const kept: T[] = [];
  let undated = 0;
  for (const row of rows) {
    const raw = at(row);
    if (raw === null || raw === undefined || raw === '') {
      undated += 1;
      continue;
    }
    const stamp = new Date(raw);
    if (Number.isNaN(stamp.getTime())) {
      undated += 1;
      continue;
    }
    if (from !== null && stamp.getTime() < from.getTime()) continue;
    // A preset window has no upper bound: "last 7 days" ends at now, and a
    // record stamped a moment from now is inside it.
    if (to !== null && stamp.getTime() > to.getTime()) continue;
    kept.push(row);
  }
  return { rows: kept, total: rows.length, undated };
}

/**
 * `1,204 of 3,880 in window` — the filtered count against the unfiltered one.
 *
 * The two numbers are always shown together. A register that reports 1,204 with
 * nothing about how many are hidden reads as the whole picture, and an analyst
 * cannot tell the difference between a quiet week and a filter.
 */
export function countInWindow(shown: number, total: number | null): string {
  const filtered = shown.toLocaleString('en-GB');
  return total === null ? `${filtered} in window` : `${filtered} of ${total.toLocaleString('en-GB')} in window`;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const TimeRangeContext = createContext<TimeRangeValue | null>(null);

export function TimeRangeProvider({ children }: { children: ReactNode }) {
  // The router is read here so the address bar is the one account of where
  // the analyst is. It settles a link on load; afterwards the window is
  // application state and the control writes it back, which is what makes a
  // hand-edited URL in an already-open tab a no-op rather than a second
  // source of truth fighting the first.
  const [params] = useSearchParams();
  const [state, setState] = useState<TimeRangeState>(() => initialState(params));

  useEffect(() => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        window: state.window,
        from: state.customFrom,
        to: state.customTo,
      }),
    );
  }, [state]);

  // A preset and a typed range are alternatives, so whichever is set clears
  // the other. That invariant is what lets the segmented control show "no
  // segment checked" for a typed range without a separate mode flag.
  const setWindow = useCallback((next: TimeWindow) => {
    setState({ window: next, customFrom: null, customTo: null });
  }, []);

  const applyCustom = useCallback((from: string, to: string): TimeRangeResult => {
    const trimmedFrom = from.trim();
    const trimmedTo = to.trim();
    const verdict = validateRange(trimmedFrom, trimmedTo);
    // Rejected with a reason, and the window in force is left alone.
    if (!verdict.ok) return verdict;
    setState({
      window: 'all',
      customFrom: trimmedFrom === '' ? null : trimmedFrom,
      customTo: trimmedTo === '' ? null : trimmedTo,
    });
    return verdict;
  }, []);

  const clearCustom = useCallback(() => setState(EMPTY_STATE), []);

  const bounds = useMemo(() => resolve(state), [state]);
  const custom = useMemo<TimeRangeCustom | null>(
    () =>
      state.customFrom === null && state.customTo === null
        ? null
        : { from: state.customFrom ?? '', to: state.customTo ?? '' },
    [state.customFrom, state.customTo],
  );

  const value = useMemo<TimeRangeValue>(
    () => ({
      window: state.window,
      setWindow,
      custom,
      applyCustom,
      clearCustom,
      from: bounds.from,
      to: bounds.to,
      isoFrom: bounds.from === null ? undefined : bounds.from.toISOString(),
      isoTo: bounds.to === null ? undefined : bounds.to.toISOString(),
      label: labelFor(state),
      isActive: state.window !== 'all' || state.customFrom !== null || state.customTo !== null,
    }),
    [state, setWindow, custom, applyCustom, clearCustom, bounds],
  );

  return <TimeRangeContext.Provider value={value}>{children}</TimeRangeContext.Provider>;
}

/**
 * Unscoped, for a tree rendered without the provider.
 *
 * A register rendered on its own — a test, a story — still has to render. It
 * renders unscoped, which is the state every screen was in before the window
 * existed, and the pages' "no window applied" wording stays true. Throwing here
 * would make the provider a hard dependency of four pages for no benefit.
 */
const UNSCOPED: TimeRangeValue = {
  window: 'all',
  setWindow: () => undefined,
  custom: null,
  applyCustom: () => ({ ok: false, reason: 'No time range is mounted, so no window can be applied.' }),
  clearCustom: () => undefined,
  from: null,
  to: null,
  isoFrom: undefined,
  isoTo: undefined,
  label: TIME_WINDOW_LABELS.all,
  isActive: false,
};

export function useTimeRange(): TimeRangeValue {
  return useContext(TimeRangeContext) ?? UNSCOPED;
}
