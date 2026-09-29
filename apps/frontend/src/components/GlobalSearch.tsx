import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, formatApiError } from '../api/client';
import { openCommandPalette } from './CommandPalette';
import type { SearchHit, SearchKind, SearchResponse } from '../api/types';

/**
 * Global search, always on screen.
 *
 * A shortcut-only search is invisible search: an analyst who does not know
 * the binding has no way to discover that it exists, and the questions a
 * global box is for — "where have I seen this handle", "which case holds
 * this wallet" — are not the questions a person is thinking of as needing a
 * case already open. So this is a visible input, always present, and the
 * command palette is the accelerator, not the discovery surface.
 *
 * Every hit names the case it came from. Without that the box answers a
 * narrower question than the one asked.
 */

/** Backend rejects terms under 3 characters; do not spend a request on one. */
const MIN_TERM = 3;
/** Long enough to avoid a request per keystroke, short enough to feel live. */
const DEBOUNCE_MS = 220;

const KIND_ORDER: readonly SearchKind[] = [
  'case', 'entity', 'evidence', 'hypothesis', 'relationship', 'source',
];

const KIND_LABEL: Record<SearchKind, string> = {
  case: 'Investigation',
  entity: 'Entity',
  evidence: 'Evidence',
  hypothesis: 'Hypothesis',
  relationship: 'Relationship',
  source: 'Source',
};

const KIND_PLURAL: Record<SearchKind, string> = {
  case: 'investigations',
  entity: 'entities',
  evidence: 'records',
  hypothesis: 'hypotheses',
  relationship: 'relationships',
  source: 'sources',
};

/** Where a hit of each kind takes the analyst. */
function destinationFor(hit: SearchHit): string | null {
  switch (hit.kind) {
    case 'case':
    case 'entity':
    case 'evidence':
    case 'hypothesis':
    case 'relationship':
      return hit.case_id ? `/cases/${hit.case_id}` : null;
    default:
      // A source is not case-scoped, so there is nowhere to take the analyst
      // yet. Better no destination than a link that goes nowhere.
      return null;
  }
}

export function GlobalSearch() {
  const navigate = useNavigate();
  const listId = useId();
  const [term, setTerm] = useState('');
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const trimmed = term.trim();
  const searchable = trimmed.length >= MIN_TERM;

  // Debounced, cancellable. The abort signal is what stops a slow response
  // for "night" landing after the response for "nightjar" and overwriting it.
  useEffect(() => {
    if (!searchable) {
      setResponse(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api.search(trimmed, controller.signal)
        .then((result) => {
          setResponse(result);
          setError(null);
          setActive(0);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setError(formatApiError(reason));
          setResponse(null);
        });
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [trimmed, searchable]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  /**
   * No client-side re-filtering.
   *
   * An earlier version narrowed the response on a three-field guess (label,
   * detail, case name). That is strictly worse than the server: the backend
   * also matches tags, summaries and normalised forms, so a case matched on
   * its tags came back as a legitimate hit and was then hidden by the client
   * — the box silently dropped results it had correctly found. The server
   * ranks; the client renders what it is given.
   */
  const visible = useMemo(() => (response?.hits ?? []).slice(0, 40), [response]);

  const grouped = useMemo(() => {
    const buckets = new Map<SearchKind, SearchHit[]>();
    for (const hit of visible) {
      const list = buckets.get(hit.kind) ?? [];
      list.push(hit);
      buckets.set(hit.kind, list);
    }
    return KIND_ORDER.filter((kind) => buckets.has(kind)).map((kind) => ({
      kind,
      hits: buckets.get(kind) ?? [],
    }));
  }, [visible]);

  const flat = useMemo(() => grouped.flatMap((group) => group.hits), [grouped]);

  const go = (hit: SearchHit) => {
    const destination = destinationFor(hit);
    setOpen(false);
    setTerm('');
    if (destination) navigate(destination);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (event.key === 'Enter') {
      // With results, Enter takes the highlighted one. Without, it falls
      // through to the palette, which is the accelerator for "I know what I
      // want, I just want to go there".
      if (flat.length > 0) {
        event.preventDefault();
        const hit = flat[active];
        if (hit) go(hit);
        return;
      }
      openCommandPalette.open();
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (flat.length === 0) return;
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive((value) => (value + delta + flat.length) % flat.length);
    }
  };

  return (
    <div className="gsearch" ref={rootRef}>
      <div className="gsearch__field">
        <span className="gsearch__icon" aria-hidden="true">⌕</span>
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={open && flat.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && flat.length > 0 ? `${listId}-${active}` : undefined}
          aria-label="Search investigations, entities and evidence"
          placeholder="Search cases, entities, evidence…"
          value={term}
          onChange={(event) => {
            setTerm(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {!searchable && term.length > 0 ? (
          <small className="gsearch__hint">{MIN_TERM}+ characters</small>
        ) : null}
        <button
          type="button"
          className="gsearch__command"
          onClick={() => openCommandPalette.open()}
          title="Command palette"
        >
          <kbd>⌘K</kbd>
        </button>
      </div>

      {open && searchable ? (
        <div className="gsearch__panel" id={listId} role="listbox" aria-label="Search results">
          {error ? (
            <p className="gsearch__state gsearch__state--error" role="alert">{error}</p>
          ) : flat.length === 0 ? (
            <p className="gsearch__state">
              Nothing matches <strong>{trimmed}</strong> across{' '}
              {response ? Object.keys(response.counts).length : 0} indexed record types.
            </p>
          ) : (
            <>
              {grouped.map((group) => {
                const total = response?.counts[group.kind] ?? group.hits.length;
                return (
                  <div className="gsearch__group" key={group.kind}>
                    <p className="gsearch__groupHead">
                      {KIND_LABEL[group.kind]}
                      <span>
                        {group.hits.length}
                        {total > group.hits.length ? ` of ${total}` : ''}{' '}
                        {KIND_PLURAL[group.kind]}
                        {response?.truncated?.[group.kind] ? ' · truncated' : ''}
                      </span>
                    </p>
                    {group.hits.map((hit) => {
                      const index = flat.indexOf(hit);
                      const destination = destinationFor(hit);
                      return (
                        <button
                          key={`${hit.kind}:${hit.id}`}
                          id={`${listId}-${index}`}
                          type="button"
                          role="option"
                          aria-selected={index === active}
                          className={`gsearch__hit${index === active ? ' is-active' : ''}`}
                          onMouseEnter={() => setActive(index)}
                          onClick={() => go(hit)}
                          // A hit with no case to open is still shown — it is a
                          // real match — but it is not advertised as
                          // navigable, so nothing implies a link that is
                          // not there.
                          aria-disabled={destination === null}
                        >
                          <span className={`gsearch__badge gsearch__badge--${hit.kind}`}>
                            {KIND_LABEL[hit.kind]}
                          </span>
                          <span className="gsearch__label">{hit.label}</span>
                          {hit.case_name ? (
                            <span className="gsearch__case">{hit.case_name}</span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
              <p className="gsearch__foot">
                <kbd>↑</kbd> <kbd>↓</kbd> to move · <kbd>↵</kbd> to open · <kbd>esc</kbd> to dismiss
              </p>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
