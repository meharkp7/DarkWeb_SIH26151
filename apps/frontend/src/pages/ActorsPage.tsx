import { useCallback, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { ActorCategoryCount, ActorRegistryRow, ActorSummary } from '../api/types';
import { ActorExportButton } from '../components/ActorExportButton';
import { Badge } from '../components/Badge';
import type { Tone } from '../components/Badge';
import { DataBlock } from '../components/DataBlock';
import { InspectorRail } from '../components/InspectorRail';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { ActorConfidence } from '../components/actor/ActorConfidence';
import { ActorIdentifierCell, actorRailProps } from '../components/actor/ActorPieces';
import { ActorScanMark } from '../components/actor/ActorScanMark';
import { ActorSummaryStrip } from '../components/actor/ActorSummaryStrip';
import { useApi } from '../hooks/useApi';
import { formatDateTime, shortId } from '../lib/format';
import { leadFor } from '../lib/explain';
// Colocated, for the same reason as `DataBlock`: a page that renders
// unstyled because someone forgot a line in `main.tsx` is a broken page, and
// the entry point is not this component's to edit.
import '../styles/actors.css';

type SortKey = 'handle' | 'category' | 'confidence' | 'identifiers' | 'last_seen' | 'last_scan';

const SORT_OPTIONS: ReadonlyArray<{ id: SortKey; label: string }> = [
  { id: 'handle', label: 'Handle' },
  { id: 'confidence', label: 'Attribution confidence' },
  { id: 'identifiers', label: 'Identifier count' },
  { id: 'last_seen', label: 'Last seen' },
  { id: 'last_scan', label: 'Last scan' },
  { id: 'category', label: 'Category' },
];

/**
 * Only `handle` reads naturally in ascending order. Confidence, counts and
 * dates all answer "biggest / most recent" far more often than "smallest /
 * oldest", and defaulting them to `desc` is what makes the first view of the
 * registry useful rather than an alphabetical wall.
 */
const ASCENDING: ReadonlySet<SortKey> = new Set<SortKey>(['handle']);

const STATUS_TONE: Record<string, Tone> = {
  active: 'ok',
  dormant: 'warn',
  rebranded: 'info',
  retired: 'neutral',
  unknown: 'neutral',
};

interface Column {
  readonly key: string;
  readonly label: string;
  readonly sort: SortKey | null;
  readonly end?: boolean;
}

const COLUMNS: readonly Column[] = [
  { key: 'actor', label: 'Actor', sort: 'handle' },
  { key: 'category', label: 'Category', sort: 'category' },
  { key: 'status', label: 'Status', sort: null },
  { key: 'confidence', label: 'Confidence', sort: 'confidence' },
  { key: 'identifiers', label: 'Identifiers', sort: 'identifiers', end: true },
  { key: 'marketplaces', label: 'Venues', sort: null, end: true },
  { key: 'links', label: 'Links', sort: null, end: true },
  { key: 'last_seen', label: 'Last seen', sort: 'last_seen' },
  { key: 'last_scan', label: 'Last scan', sort: 'last_scan' },
  { key: 'source', label: 'Source', sort: null },
];

function isSortKey(value: string | null): value is SortKey {
  return value !== null && SORT_OPTIONS.some((option) => option.id === value);
}

/**
 * Actor registry.
 *
 * The problem statement's result set, so it is built like the investigations
 * register: every filter and the sort live in the query string, an analyst can
 * link a filtered view into a handover note, the browser back button steps
 * through filter changes, and selection is `?inspect={actorId}` so the exact
 * view — filters, sort and the row under inspection — is one URL.
 *
 * Server-side sorting and filtering only. The registry is a cross-case object
 * set rather than a per-case slice, so re-computing it in the browser would
 * mean shipping the whole registry to render a filtered view of it.
 */
export function ActorsPage() {
  const [params, setParams] = useSearchParams();

  const query = params.get('q') ?? '';
  const category = params.get('category') ?? 'all';
  const status = params.get('status') ?? 'all';
  const minConfidenceParam = params.get('min_confidence');
  const minConfidence =
    minConfidenceParam !== null && Number.isFinite(Number(minConfidenceParam))
      ? Number(minConfidenceParam)
      : null;
  const sort: SortKey = isSortKey(params.get('sort')) ? (params.get('sort') as SortKey) : 'handle';
  const dirParam = params.get('dir');
  const dir: 'asc' | 'desc' = dirParam === 'asc' || dirParam === 'desc'
    ? dirParam
    : ASCENDING.has(sort)
      ? 'asc'
      : 'desc';
  const inspect = params.get('inspect');

  const filters = useMemo(
    () => ({
      ...(query.trim() === '' ? {} : { q: query.trim() }),
      ...(category === 'all' ? {} : { category }),
      ...(status === 'all' ? {} : { status }),
      ...(minConfidence === null ? {} : { min_confidence: minConfidence }),
      sort,
      dir,
    }),
    [query, category, status, minConfidence, sort, dir],
  );

  const list = useApi<ActorRegistryRow[]>(api.actorQueryUrl(filters));
  const summary = useApi<ActorSummary>(api.actorSummaryUrl());
  const categories = useApi<ActorCategoryCount[]>(api.actorCategoriesUrl());

  // Memoised so the selection lookup below does not see a new array identity
  // on every render and re-resolve the rail for an unchanged dataset.
  const rows = useMemo(() => list.data ?? [], [list.data]);
  const staleDays = summary.data?.stale_days ?? null;

  /** Typing replaces, sorting and selection push: the back button must work. */
  const update = useCallback(
    (patch: Readonly<Record<string, string | null>>, replace = true) => {
      const next = new URLSearchParams(params);
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === '') next.delete(key);
        else next.set(key, value);
      }
      setParams(next, { replace });
    },
    [params, setParams],
  );

  const toggleSort = (key: SortKey) => {
    if (key === sort) update({ dir: dir === 'desc' ? 'asc' : 'desc' }, false);
    else update({ sort: key, dir: ASCENDING.has(key) ? 'asc' : 'desc' }, false);
  };

  const select = useCallback(
    (actorId: string | null) => update({ inspect: actorId }, false),
    [update],
  );

  // Roving tabindex: a registry of hundreds of actors must not be hundreds of
  // tab stops. One stop enters the grid, the arrow keys move within it.
  const [focusIndex, setFocusIndex] = useState(0);
  const bodyRef = useRef<HTMLTableSectionElement>(null);

  const moveFocus = (from: number, delta: number) => {
    const next = Math.min(rows.length - 1, Math.max(0, from + delta));
    setFocusIndex(next);
    bodyRef.current?.querySelectorAll<HTMLElement>('tr[aria-selected]')[next]?.focus();
  };

  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, index: number, actorId: string) => {
    switch (event.key) {
      case 'Enter':
      case ' ':
        // Selecting never navigates; the handle link is the way in.
        event.preventDefault();
        select(actorId);
        break;
      case 'ArrowDown':
        event.preventDefault();
        moveFocus(index, 1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        moveFocus(index, -1);
        break;
      case 'Home':
        event.preventDefault();
        moveFocus(index, -index);
        break;
      case 'End':
        event.preventDefault();
        moveFocus(index, rows.length - 1 - index);
        break;
      default:
        break;
    }
  };

  const selected = useMemo(
    () => rows.find((row) => row.actor_id === inspect) ?? null,
    [rows, inspect],
  );
  const rail = selected === null ? null : actorRailProps(selected, staleDays, () => select(null));

  const filtersActive =
    query.trim() !== '' || category !== 'all' || status !== 'all' || minConfidence !== null;
  const total = summary.data?.total ?? null;

  return (
    <div className="page-stack act-page">
      <header className="act-page__head">
        <div>
          <span className="eyebrow">Registry</span>
          <h1>Actors</h1>
          <p>
            Every tracked actor across all investigations: the handle, the identifiers that pin the
            persona down, the venues it trades on, and how confident the platform is about the
            attribution. Filters live in the address bar, so a view can be linked or handed over.
          </p>
        </div>
        <div className="act-page__actions">
          {/* Export sits with the register it exports, not on a page of its own,
              and it carries the filters currently applied. */}
          <ActorExportButton filters={filters} />
        </div>
      </header>

      <ActorSummaryStrip summary={summary.data} />

      <DataBlock
        title="Actor registry"
        eyebrow="Result set"
        lead={leadFor('actor.registry', { total, shown: rows.length })}
      >
        <div className="act-toolbar" role="search" aria-label="Filter the actor registry">
          <div className="act-toolbar__search">
            <span aria-hidden="true">⌕</span>
            <input
              value={query}
              onChange={(event) => update({ q: event.target.value })}
              placeholder="Search handle or identifier value…"
              aria-label="Search actors by handle or identifier"
            />
          </div>

          <label className="sr-only" htmlFor="act-filter-category">
            Filter by category
          </label>
          <select
            id="act-filter-category"
            className="act-select"
            value={category}
            onChange={(event) => update({ category: event.target.value === 'all' ? null : event.target.value })}
            aria-label="Filter by category"
          >
            <option value="all">All categories</option>
            {(categories.data ?? []).map((row) => (
              <option key={row.category} value={row.category}>
                {`${row.category} (${row.count})`}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="act-filter-status">
            Filter by status
          </label>
          <select
            id="act-filter-status"
            className="act-select"
            value={status}
            onChange={(event) => update({ status: event.target.value === 'all' ? null : event.target.value })}
            aria-label="Filter by status"
          >
            <option value="all">All statuses</option>
            {(summary.data?.by_status ?? []).map((row) => (
              <option key={row.status} value={row.status}>
                {`${row.status} (${row.count})`}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="act-filter-confidence">
            Minimum attribution confidence
          </label>
          <select
            id="act-filter-confidence"
            className="act-select"
            value={minConfidence === null ? 'all' : String(minConfidence)}
            onChange={(event) =>
              update({ min_confidence: event.target.value === 'all' ? null : event.target.value })
            }
            aria-label="Minimum attribution confidence"
          >
            <option value="all">Any confidence</option>
            {[0.9, 0.75, 0.5, 0.25].map((value) => (
              <option key={value} value={value}>
                {`${Math.round(value * 100)}%+ assessed`}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="act-sort">
            Sort actors
          </label>
          <select
            id="act-sort"
            className="act-select"
            value={sort}
            onChange={(event) => {
              const next = event.target.value;
              if (!isSortKey(next)) return;
              update({ sort: next === 'handle' ? null : next, dir: ASCENDING.has(next) ? 'asc' : 'desc' });
            }}
            aria-label="Sort actors"
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {`Sort: ${option.label}`}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="btn btn--ghost btn--small inv-toolbar__clear"
            onClick={() => setParams(new URLSearchParams(), { replace: true })}
          >
            Reset
          </button>
        </div>

        {summary.error !== null && <ErrorState message={summary.error} onRetry={summary.reload} />}
        {list.error !== null && <ErrorState message={list.error} onRetry={list.reload} />}
        {list.loading && <LoadingState label="Loading the actor registry…" />}

        {!list.loading && list.error === null && rows.length === 0 && (
          <EmptyState
            title={filtersActive ? 'No actors match these filters' : 'No actors in the registry'}
            message={
              filtersActive
                ? 'No actor matches the current filters. Reset to see the whole registry.'
                : 'The registry is empty. Actors are cross-case records, so they arrive from collection rather than from opening an investigation.'
            }
            endpoint="GET /api/v1/actors"
          />
        )}

        {!list.loading && rows.length > 0 && (
          <div className={rail === null ? 'insp-shell' : 'insp-shell has-rail'}>
            <div className="table-wrap">
              <table className="act-register" role="grid" aria-label="Actor registry">
                <caption className="sr-only">
                  Actor registry: {rows.length} of {total ?? rows.length} actors, sorted by{' '}
                  {SORT_OPTIONS.find((option) => option.id === sort)?.label ?? sort}. Use the arrow
                  keys to move between rows and Enter to inspect an actor without leaving the
                  register.
                </caption>
                <thead>
                  <tr>
                    {COLUMNS.map((column) => (
                      <th
                        key={column.key}
                        scope="col"
                        style={{ textAlign: column.end === true ? 'end' : 'start' }}
                        aria-sort={
                          column.sort === null
                            ? undefined
                            : column.sort === sort
                              ? dir === 'asc'
                                ? 'ascending'
                                : 'descending'
                              : 'none'
                        }
                      >
                        {column.sort === null ? (
                          column.label
                        ) : (
                          <button
                            type="button"
                            className="act-sort"
                            onClick={() => toggleSort(column.sort as SortKey)}
                          >
                            {column.label}
                            <span className="act-sort__arrow" aria-hidden="true" />
                          </button>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody ref={bodyRef}>
                  {rows.map((actor, index) => {
                    const isSelected = selected?.actor_id === actor.actor_id;
                    return (
                      <tr
                        key={actor.actor_id}
                        className={isSelected ? 'insp-selected-row' : undefined}
                        aria-selected={isSelected}
                        tabIndex={index === focusIndex ? 0 : -1}
                        onFocus={() => setFocusIndex(index)}
                        onClick={() => select(actor.actor_id)}
                        onKeyDown={(event) => onRowKeyDown(event, index, actor.actor_id)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td>
                          <Link
                            className="act-handle"
                            to={`/actors/${encodeURIComponent(actor.actor_id)}`}
                            onClick={(event) => event.stopPropagation()}
                          >
                            {actor.handle}
                          </Link>
                          <span className="act-handle-id" title={actor.actor_id}>
                            {shortId(actor.actor_id, 8)}
                          </span>
                          {actor.notes !== null && actor.notes !== '' && (
                            <span className="act-cat">{actor.notes}</span>
                          )}
                        </td>
                        <td>{actor.category}</td>
                        <td>
                          <Badge tone={STATUS_TONE[actor.status] ?? 'neutral'}>{actor.status}</Badge>
                        </td>
                        <td>
                          <ActorConfidence confidence={actor.confidence} />
                        </td>
                        <td className="act-num">
                          <ActorIdentifierCell actor={actor} />
                        </td>
                        <td className="act-num">{actor.marketplace_count}</td>
                        <td className="act-num">{actor.case_link_count}</td>
                        <td>{formatDateTime(actor.last_seen)}</td>
                        <td>
                          <ActorScanMark lastScanAt={actor.last_scan_at} staleDays={staleDays} />
                        </td>
                        <td>
                          {actor.source_name === null ? (
                            <span className="hint">—</span>
                          ) : (
                            actor.source_name
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {rail !== null && <InspectorRail {...rail} />}
          </div>
        )}

        <p className="act-foot">
          <span>
            {total === null
              ? `${rows.length} shown`
              : `${rows.length} of ${total} shown · live from PostgreSQL`}
          </span>
          <span>
            {filtersActive
              ? 'Filters applied from the address bar — Reset clears them.'
              : 'No filters applied.'}
          </span>
        </p>
      </DataBlock>
    </div>
  );
}