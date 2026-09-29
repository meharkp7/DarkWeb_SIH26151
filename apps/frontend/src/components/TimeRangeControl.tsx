import { useCallback, useEffect, useId, useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  RANGE_CUSTOM,
  RANGE_FROM_PARAM,
  RANGE_PARAM,
  RANGE_TO_PARAM,
  TIME_WINDOW_LABELS,
  TIME_WINDOW_SEGMENTS,
  TIME_WINDOWS,
  countInWindow,
  useTimeRange,
} from '../store/TimeRange';
import type { TimeWindow } from '../store/TimeRange';
// Colocated, for the same reason as `DataBlock`: a control that renders
// unstyled because someone forgot a line in `main.tsx` is a broken topbar.
import '../styles/timerange.css';

/**
 * The console's timeline, in the topbar.
 *
 * The same control appears over every register, so its accessible name says
 * what it scopes rather than what it is: an analyst hearing "time range" has
 * no way to know whether it bounds the investigations, the actors or the
 * collection log, and a screen with two timelines (Infrastructure and Persona
 * Linkage each own one) would leave the question unanswerable.
 */

type OptionId = TimeWindow | typeof RANGE_CUSTOM;

interface SegmentOption {
  readonly id: OptionId;
  /** What the segment shows. */
  readonly text: string;
  /** Spelled out for assistive technology, appended after the visible text. */
  readonly long: string;
  readonly checked: boolean;
}

/**
 * Mirror the window into the address bar.
 *
 * The store reads the URL on mount (so a link scopes the first render); the
 * control writes it, because the control is the only place the window is
 * changed and the only place the router is in scope. Other parameters are
 * preserved, so a register filter typed in the toolbar survives a change of
 * window, and a window survives a change of register filter.
 */
function useTimeRangeUrl(): void {
  const { window, custom } = useTimeRange();
  const [params, setParams] = useSearchParams();

  useEffect(() => {
    const next = new URLSearchParams(params);
    next.delete(RANGE_PARAM);
    next.delete(RANGE_FROM_PARAM);
    next.delete(RANGE_TO_PARAM);
    if (custom !== null) {
      next.set(RANGE_PARAM, RANGE_CUSTOM);
      if (custom.from !== '') next.set(RANGE_FROM_PARAM, custom.from);
      if (custom.to !== '') next.set(RANGE_TO_PARAM, custom.to);
    } else if (window !== 'all') {
      next.set(RANGE_PARAM, window);
    }
    // The comparison is what makes this safe to run on every change: a filter
    // the analyst set elsewhere arrives as a new `params`, the rebuild below
    // reproduces it byte for byte, and nothing is written.
    if (next.toString() === params.toString()) return;
    // `replace`: a window is a refinement of the view an analyst is already
    // reading, not a place they navigated to. The back button belongs to the
    // register, not to every width they tried.
    setParams(next, { replace: true });
  }, [window, custom, params, setParams]);
}

export function TimeRangeControl({ scope = 'all registers' }: { readonly scope?: string }): JSX.Element {
  const { window, custom, setWindow, applyCustom, clearCustom, label, isActive } = useTimeRange();
  useTimeRangeUrl();

  const [open, setOpen] = useState(false);
  const [draftFrom, setDraftFrom] = useState(custom?.from ?? '');
  const [draftTo, setDraftTo] = useState(custom?.to ?? '');
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<OptionId | null>(null);

  const panelId = useId();
  const errorId = useId();

  const options = useMemo<readonly SegmentOption[]>(() => {
    const presets: SegmentOption[] = TIME_WINDOWS.map((value) => ({
      id: value,
      text: TIME_WINDOW_SEGMENTS[value],
      long: TIME_WINDOW_LABELS[value],
      // A typed range is in force, so no preset is the one in force either.
      checked: custom === null && window === value,
    }));
    if (custom === null) return presets;
    return [
      ...presets,
      { id: RANGE_CUSTOM, text: 'Custom', long: label, checked: true },
    ];
  }, [window, custom, label]);

  const checked = options.find((option) => option.checked) ?? null;
  const roving =
    activeId !== null && options.some((option) => option.id === activeId)
      ? activeId
      : (checked?.id ?? options[0]?.id ?? 'all');

  const choose = useCallback(
    (id: OptionId) => {
      setActiveId(id);
      // The custom segment is not a window in its own right: it is the range
      // already typed, and picking it opens the fields rather than discarding
      // the bounds the analyst entered.
      if (id === RANGE_CUSTOM) {
        setOpen(true);
        return;
      }
      setWindow(id);
    },
    [setWindow],
  );

  const onSegmentKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let target: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') target = index + 1;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') target = index - 1;
    else if (event.key === 'Home') target = 0;
    else if (event.key === 'End') target = options.length - 1;
    else if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      const option = options[index];
      if (option !== undefined) choose(option.id);
      return;
    } else return;

    event.preventDefault();
    // Wrapping, so there is no dead end in either direction.
    const next = options[(target + options.length) % options.length];
    if (next === undefined) return;
    choose(next.id);
    document.getElementById(`tr-seg-${next.id}`)?.focus();
  };

  // The disclosure always opens on the range actually in force, never on a
  // stale draft left behind by a window that has since changed.
  const reveal = useCallback(() => {
    setDraftFrom(custom?.from ?? '');
    setDraftTo(custom?.to ?? '');
    setError(null);
    setOpen((value) => !value);
  }, [custom]);

  const submit = useCallback(() => {
    const verdict = applyCustom(draftFrom, draftTo);
    setError(verdict.ok ? null : verdict.reason);
    setApplied(verdict.ok ? 'Window applied.' : null);
  }, [applyCustom, draftFrom, draftTo]);

  const clear = useCallback(() => {
    clearCustom();
    setDraftFrom('');
    setDraftTo('');
    setError(null);
    setApplied('Window cleared. Every record is shown.');
    setOpen(false);
  }, [clearCustom]);

  return (
    <div className="tr">
      {/* Decorative: the group below carries the name that says what the
          window scopes, which is the sentence an analyst needs. */}
      <span className="tr__label" aria-hidden="true">Timeline</span>

      <div className="tr-seg" role="radiogroup" aria-label={`Time range for ${scope}`}>
        {options.map((option, index) => (
          <button
            key={option.id}
            id={`tr-seg-${option.id}`}
            type="button"
            role="radio"
            aria-checked={option.checked}
            // Roving tabindex: one stop enters the group and the arrow keys
            // move within it, which is what a radiogroup promises.
            tabIndex={roving === option.id ? 0 : -1}
            className={option.checked ? 'tr-seg__item is-on' : 'tr-seg__item'}
            onClick={() => choose(option.id)}
            onFocus={() => setActiveId(option.id)}
            onKeyDown={(event) => onSegmentKeyDown(event, index)}
          >
            {option.text}
            {/* The visible text stays inside the accessible name, and the
                spelled-out window follows it, so the segment is not announced
                as a bare "7d". */}
            <span className="sr-only">{` — ${option.long}`}</span>
            {/* A selected segment is marked by a rule under it as well as by
                its fill: the state must not be carried by colour alone. */}
            <span className="tr-seg__mark" aria-hidden="true" />
          </button>
        ))}
      </div>

      <button
        type="button"
        className="tr-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={reveal}
      >
        {open ? 'Hide custom range' : 'Custom range'}
      </button>

      {/* Kept outside the panel on purpose: clearing the window closes the
          panel, and a live region that unmounts with it announces nothing. */}
      <p className="sr-only" role="status">
        {applied ?? ''}
      </p>

      {open && (
        <div className="tr-panel" id={panelId}>
          <div className="tr-panel__fields">
            <label className="tr-field" htmlFor="tr-range-from">
              <span className="tr-field__label">Range start</span>
              <input
                id="tr-range-from"
                type="date"
                value={draftFrom}
                aria-invalid={error !== null}
                aria-describedby={error !== null ? errorId : undefined}
                onChange={(event) => {
                  setDraftFrom(event.target.value);
                  setError(null);
                  setApplied(null);
                }}
              />
            </label>
            <label className="tr-field" htmlFor="tr-range-to">
              <span className="tr-field__label">Range end</span>
              <input
                id="tr-range-to"
                type="date"
                value={draftTo}
                aria-invalid={error !== null}
                aria-describedby={error !== null ? errorId : undefined}
                onChange={(event) => {
                  setDraftTo(event.target.value);
                  setError(null);
                  setApplied(null);
                }}
              />
            </label>
          </div>
          <p className="tr-panel__hint">
            Both ends are optional: a start on its own means everything since that day. A range that
            cannot be queried is refused with a reason rather than quietly corrected.
          </p>
          <div className="tr-panel__actions">
            <button type="button" className="tr-btn tr-btn--primary" onClick={submit}>
              Apply range
            </button>
            <button
              type="button"
              className="tr-btn"
              disabled={!isActive && draftFrom === '' && draftTo === ''}
              onClick={clear}
            >
              Clear window
            </button>
          </div>
          {error !== null && (
            <p className="tr-panel__error" id={errorId} role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export interface TimeRangeNoticeProps {
  /** The resolved window, from `useTimeRange().label`. */
  readonly window: string;
  /** Rows currently in the window. */
  readonly shown: number;
  /** Rows before the window was applied, or null when the page cannot say. */
  readonly total: number | null;
  /**
   * How the narrowing was done, in the words of the page that did it — "in the
   * browser over 3,880 loaded records" or "by the server on this endpoint".
   * A page that filtered client-side must not let the sentence imply the API
   * did the work.
   */
  readonly basis: string;
  /** Loaded rows carrying no usable timestamp, excluded from `shown`. */
  readonly undated?: number;
  /** Anything else the reader needs in order to trust the count. */
  readonly footnote?: string;
}

/**
 * The sentence a register has to say about the window.
 *
 * Silently showing a filtered list beside a count that looks like the whole
 * register is the failure this exists to prevent: an analyst who cannot tell
 * that 2,676 records are hidden will read 1,204 as the size of the world. So
 * the window, the filtered count, the unfiltered count and the way the
 * narrowing happened are all in one place, and a page with no window applied
 * renders nothing at all rather than an empty reassurance.
 */
export function TimeRangeNotice({
  window,
  shown,
  total,
  basis,
  undated = 0,
  footnote,
}: TimeRangeNoticeProps): JSX.Element | null {
  const { isActive } = useTimeRange();
  if (!isActive) return null;

  const sentences = [`${window} — ${countInWindow(shown, total)}.`];
  if (total === null) {
    sentences.push(
      `Filtered ${basis}. This endpoint does not return an unfiltered total, so none is stated here.`,
    );
  } else {
    sentences.push(`Filtered ${basis}.`);
  }
  if (undated > 0) {
    sentences.push(
      `${undated} of the loaded records carry no timestamp, and nothing about them places them in or out of a window, so they are not listed.`,
    );
  }
  if (footnote !== undefined && footnote !== '') sentences.push(footnote);

  return (
    <span className="tr-notice" data-testid="tr-notice">
      {sentences.join(' ')}
    </span>
  );
}
