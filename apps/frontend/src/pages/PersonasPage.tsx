/**
 * Persona linkage — linking a candidate handle to a tracked actor.
 *
 * The surface exists because stylometry and behavioural profiling could already
 * be computed and nothing could act on them. It follows the investigations
 * register's interaction model: a dense sortable table, URL-driven filters, row
 * selection filling the inspector rail, and everything a view selects written to
 * the address bar so a particular slice of the register can be linked or handed
 * over.
 *
 * One rule shapes every choice here. **A model score and an analyst decision are
 * not the same kind of thing and must never read as interchangeable.** A
 * `proposed` linkage is a hypothesis: its score is drawn muted, captioned "model
 * estimate · not reviewed", and its status is a dashed outline with a hollow
 * mark. Only `confirmed` is a finding. The alignment, actor, method, case and
 * window filters are sent to the server, because the count a filter returns is
 * part of what an analyst is reading; the handle search and the sort are
 * client-side, because they reorder rather than narrow what the server counted.
 *
 * Not a primary destination — it is reached from an actor profile
 * (`?actor=<actor_id>`) and from a workspace's assessment tab, so it takes the
 * actor from the address bar and proposes for that actor.
 */

import { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { LimitationsPanel } from '../components/personas/LimitationsPanel';

import { formatDateTime } from '../lib/format';
import { leadFor, METRICS } from '../lib/explain';
import { DataBlock } from '../components/DataBlock';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { InspectorRail } from '../components/InspectorRail';
import type { InspectorStatus, InspectorTab } from '../components/InspectorRail';
import { PersonaExportMenu } from '../components/personas/PersonaExportMenu';
import { ProposeLinkageDialog } from '../components/personas/ProposeLinkageDialog';
import { LinkageDetail } from '../components/personas/LinkageDetail';
import { LinkageScoreBar } from '../components/personas/LinkageScoreBar';
import { LinkageStatusPill } from '../components/personas/LinkageStatusPill';
import { LinkageSummaryBlock } from '../components/personas/LinkageSummaryBlock';
import { usePersonaRegister } from '../components/personas/usePersonaRegister';
import {
  PERSONA_LINKAGE_METHODS,
  PERSONA_LINKAGE_STATUSES,
  PERSONA_METHOD_LABELS,
} from '../api/types';
import type {
  AdjudicationResponse,
  PersonaFilters,
  PersonaLinkage,
  PersonaLinkageDetail,
  PersonaLinkageMethod,
  PersonaLinkageStatus,
} from '../api/types';
import '../styles/personas.css';

type SortKey =
  | 'candidate_handle'
  | 'actor_handle'
  | 'method'
  | 'score'
  | 'status'
  | 'aligned_features'
  | 'apart_features'
  | 'contested_features'
  | 'adjudicated_at'
  | 'case_name'
  | 'created_at';

const COLUMNS: readonly { key: SortKey; label: string; numeric: boolean }[] = [
  { key: 'candidate_handle', label: 'Candidate', numeric: false },
  { key: 'actor_handle', label: 'Actor', numeric: false },
  { key: 'method', label: 'Method', numeric: false },
  { key: 'score', label: 'Score', numeric: true },
  { key: 'status', label: 'Status', numeric: false },
  { key: 'aligned_features', label: 'Aligned', numeric: true },
  { key: 'apart_features', label: 'Apart', numeric: true },
  { key: 'contested_features', label: 'Contested', numeric: true },
  { key: 'adjudicated_at', label: 'Adjudicated', numeric: false },
  { key: 'case_name', label: 'Case', numeric: false },
];

/** Column order for a value of each sort key. `adjudicated_at` has no natural order. */
const STATUS_ORDER: Readonly<Record<string, number>> = {
  proposed: 0,
  rejected: 1,
  confirmed: 2,
};

const RAIL_TABS: readonly InspectorTab[] = [
  { id: 'evidence', label: 'Feature comparison' },
  { id: 'limitations', label: 'Limitations' },
  { id: 'adjudication', label: 'Adjudication' },
];
type RailTab = 'evidence' | 'limitations' | 'adjudication';

function compareRows(a: PersonaLinkage, b: PersonaLinkage, key: SortKey): number {
  const left = a[key];
  const right = b[key];
  // Status sorts in a fixed order rather than alphabetically: proposals first,
  // because they are the ones waiting on somebody.
  if (key === 'status') {
    return (STATUS_ORDER[a.status] ?? 0) - (STATUS_ORDER[b.status] ?? 0);
  }
  if (key === 'aligned_features' || key === 'apart_features' || key === 'contested_features') {
    return (left as readonly string[]).length - (right as readonly string[]).length;
  }
  if (key === 'adjudicated_at') {
    // Undated rows last: an unadjudicated proposal has no ruling to compare.
    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;
    return left < right ? -1 : 1;
  }
  if (key === 'score') return (a.score as number) - (b.score as number);
  return String(left ?? '').localeCompare(String(right ?? ''));
}

export function PersonasPage() {
  const [params, setParams] = useSearchParams();
  const [railTab, setRailTab] = useState<RailTab>('evidence');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [proposing, setProposing] = useState(false);

  const status = params.get('status') as PersonaLinkageStatus | null;
  const method = params.get('method') as PersonaLinkageMethod | null;
  const actorId = params.get('actor');
  const caseId = params.get('case');
  const minScoreRaw = params.get('min_score');
  const from = params.get('from');
  const until = params.get('until');
  const sortKey = (params.get('sort') as SortKey | null) ?? 'score';
  const dir = params.get('dir') === 'asc' ? 'asc' : 'desc';
  const selectedId = params.get('inspect');

  const minScore = minScoreRaw === null ? null : Number(minScoreRaw);
  const filtersActive =
    status !== null || method !== null || actorId !== null || from !== null || until !== null || minScore !== null;

  const filters = useMemo<PersonaFilters | undefined>(
    () => ({
      status,
      method,
      actor_id: actorId,
      min_score: Number.isNaN(minScore as number) ? null : minScore,
      from,
      until,
    }),
    [status, method, actorId, minScore, from, until],
  );

  const { rows, summary, loading, error, applyServerRow, reload } = usePersonaRegister(filters);

  const patch = useCallback(
    (next: Record<string, string | null>) => {
      const merged = new URLSearchParams(params);
      for (const [key, value] of Object.entries(next)) {
        if (value === null || value === '') merged.delete(key);
        else merged.set(key, value);
      }
      setParams(merged, { replace: true });
    },
    [params, setParams],
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const matched = needle
      ? rows.filter(
          (row) =>
            row.candidate_handle.toLowerCase().includes(needle) ||
            row.actor_handle.toLowerCase().includes(needle) ||
            (row.case_name ?? '').toLowerCase().includes(needle),
        )
      : [...rows];
    const factor = dir === 'asc' ? 1 : -1;
    matched.sort((a, b) => factor * compareRows(a, b, sortKey));
    return matched;
  }, [dir, rows, search, sortKey]);

  const selected = useMemo(
    () => visible.find((row) => row.linkage_id === selectedId) ?? null,
    [selectedId, visible],
  );

  // The rail reads the detail endpoint for the row under inspection, which is
  // the only place the scorer's name and the per-feature agreement figures are
  // available; the register itself is list-shaped.
  const { data: railDetail } = useApi<PersonaLinkageDetail>(
    selected ? api.getPersonaLinkageUrl(selected.linkage_id) : null,
  );
  const railScorer =
    railDetail && railDetail.linkage_id === selected?.linkage_id
      ? (railDetail.scorer ?? undefined)
      : undefined;

  /**
   * A ruling arrives as the server's own copy of the row. That copy is written
   * into the register immediately — so the row shows the stored record rather
   * than the click's intent — and the register then refetches, because the
   * observed-error pair in the summary is the server's arithmetic and has to
   * move with the ruling.
   */
  const handleRuled = useCallback(
    (response: AdjudicationResponse) => applyServerRow(response.linkage),
    [applyServerRow],
  );

  const handleCreated = useCallback(
    (linkage: PersonaLinkageDetail) => {
      applyServerRow(linkage);
      patch({ inspect: linkage.linkage_id });
    },
    [applyServerRow, patch],
  );

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) patch({ dir: dir === 'asc' ? 'desc' : 'asc' });
    else patch({ sort: key, dir: key === 'score' ? 'desc' : 'asc' });
  };

  const ariaSort = (key: SortKey): 'ascending' | 'descending' | 'none' =>
    key === sortKey ? (dir === 'asc' ? 'ascending' : 'descending') : 'none';

  const reset = () => {
    setSearch('');
    setParams(new URLSearchParams(), { replace: true });
  };

  const openRow = (row: PersonaLinkage) => {
    setExpanded((current) => (current === row.linkage_id ? null : row.linkage_id));
    patch({ inspect: row.linkage_id });
    setRailTab('evidence');
  };

  return (
    <div className="per-page">
      <header className="per-page__head">
        <div>
          <p className="per-page__eyebrow">Attribution · persona linkage</p>
          <h1>Persona linkage</h1>
          <p className="per-page__sub">{leadFor(METRICS.personaLinkageRegister, { total: summary?.total ?? null, shown: visible.length })}</p>
        </div>
        <div className="per-page__actions">
          <PersonaExportMenu filters={filters} disabled={visible.length === 0} rowCount={visible.length} />
          <button
            type="button"
            className="per-btn per-btn--primary"
            disabled={actorId === null}
            title={actorId === null ? 'Open this from an actor profile to propose a linkage' : undefined}
            onClick={() => setProposing(true)}
          >
            Propose linkage
          </button>
        </div>
      </header>

      {actorId === null ? (
        <p className="per-page__hint">
          Showing every tracked actor&rsquo;s linkages. Open this from an actor profile to propose a
          linkage for one actor.
        </p>
      ) : null}

      <LinkageSummaryBlock summary={summary} shown={visible.length} filtersActive={filtersActive} />

      <DataBlock title="Filters" dense>
        <form
          className="per-filters"
          onSubmit={(event) => {
            event.preventDefault();
          }}
        >
          <label className="per-field">
            <span className="per-field__label">Search handles and cases</span>
            <input
              className="per-field__input"
              value={search}
              placeholder="handle or case name"
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>

          <label className="per-field">
            <span className="per-field__label">Status</span>
            <select
              className="per-field__input"
              value={status ?? ''}
              onChange={(event) => patch({ status: event.target.value })}
            >
              <option value="">all statuses</option>
              {PERSONA_LINKAGE_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          <label className="per-field">
            <span className="per-field__label">Method</span>
            <select
              className="per-field__input"
              value={method ?? ''}
              onChange={(event) => patch({ method: event.target.value })}
            >
              <option value="">all methods</option>
              {PERSONA_LINKAGE_METHODS.map((value) => (
                <option key={value} value={value}>
                  {PERSONA_METHOD_LABELS[value]}
                </option>
              ))}
            </select>
          </label>

          <label className="per-field">
            <span className="per-field__label">Minimum score</span>
            <input
              className="per-field__input"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minScoreRaw ?? ''}
              placeholder="0.00"
              onChange={(event) => patch({ min_score: event.target.value })}
            />
          </label>

          <label className="per-field">
            <span className="per-field__label">Proposed from</span>
            <input
              className="per-field__input"
              type="date"
              value={from ?? ''}
              onChange={(event) => patch({ from: event.target.value })}
            />
          </label>

          <label className="per-field">
            <span className="per-field__label">Proposed until</span>
            <input
              className="per-field__input"
              type="date"
              value={until ?? ''}
              onChange={(event) => patch({ until: event.target.value })}
            />
          </label>

          <button type="button" className="per-btn" onClick={reset}>
            Reset
          </button>
        </form>
        <p className="per-filters__note">
          The window bounds when each linkage was <em>proposed</em>, not when it was ruled on: a
          proposal raised in March and judged in June belongs to the March timeline.
        </p>
      </DataBlock>

      {loading ? <LoadingState label="Loading persona linkages" /> : null}
      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {!loading && !error ? (
        <DataBlock
          title="Linkage register"
          dense
          actions={
            <span className="per-register__count">
              {visible.length}
              {search.trim() ? ` of ${rows.length}` : ''} linkages
            </span>
          }
        >
          {visible.length === 0 ? (
            <EmptyState
              title="No linkage matches this view"
              message="A register with nothing in it is a back-of-backlog state, not evidence that no rebrand or migration is out there. Widen the filters or the date window."
              endpoint="GET /api/v1/personas/linkages"
            />
          ) : (
            <table className="per-table">
              <caption className="per-table__caption">
                Linkage register. Select a row to inspect the feature comparison, the limitations and
                the adjudication control. A score is the model&rsquo;s output; a status is an
                analyst&rsquo;s ruling.
              </caption>
              <thead>
                <tr>
                  <th scope="col" aria-sort={ariaSort('candidate_handle')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('candidate_handle')}>
                      Candidate <SortMark state={ariaSort('candidate_handle')} />
                    </button>
                  </th>
                  <th scope="col" aria-sort={ariaSort('actor_handle')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('actor_handle')}>
                      Actor <SortMark state={ariaSort('actor_handle')} />
                    </button>
                  </th>
                  <th scope="col" aria-sort={ariaSort('method')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('method')}>
                      Method <SortMark state={ariaSort('method')} />
                    </button>
                  </th>
                  <th scope="col" className="per-th--numeric" aria-sort={ariaSort('score')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('score')}>
                      Score <SortMark state={ariaSort('score')} />
                    </button>
                  </th>
                  <th scope="col" aria-sort={ariaSort('status')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('status')}>
                      Status <SortMark state={ariaSort('status')} />
                    </button>
                  </th>
                  <th scope="col" className="per-th--numeric" aria-sort={ariaSort('aligned_features')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('aligned_features')}>
                      Aligned <SortMark state={ariaSort('aligned_features')} />
                    </button>
                  </th>
                  <th scope="col" className="per-th--numeric" aria-sort={ariaSort('apart_features')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('apart_features')}>
                      Apart <SortMark state={ariaSort('apart_features')} />
                    </button>
                  </th>
                  <th scope="col" className="per-th--numeric" aria-sort={ariaSort('contested_features')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('contested_features')}>
                      Contested <SortMark state={ariaSort('contested_features')} />
                    </button>
                  </th>
                  <th scope="col" aria-sort={ariaSort('adjudicated_at')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('adjudicated_at')}>
                      Adjudicated <SortMark state={ariaSort('adjudicated_at')} />
                    </button>
                  </th>
                  <th scope="col" aria-sort={ariaSort('case_name')}>
                    <button type="button" className="per-th" onClick={() => toggleSort('case_name')}>
                      Case <SortMark state={ariaSort('case_name')} />
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <PersonaRow
                    key={row.linkage_id}
                    row={row}
                    selected={row.linkage_id === selectedId}
                    expanded={row.linkage_id === expanded}
                    onOpen={() => openRow(row)}
                    onRuled={handleRuled}
                  />
                ))}
              </tbody>
            </table>
          )}
        </DataBlock>
      ) : null}

      {proposing && actorId !== null ? (
        <ProposeLinkageDialog
          actorId={actorId}
          caseId={caseId}
          onCreated={handleCreated}
          onClose={() => setProposing(false)}
        />
      ) : null}

      <InspectorRail
        open={selected !== null}
        onClose={() => patch({ inspect: null })}
        title="Persona linkage"
        subtitle={selected?.candidate_handle}
        facts={buildFacts(selected)}
        // The score is always a model estimate, including on a confirmed
        // linkage: an analyst agreeing with a model output does not turn that
        // output into a measurement. The decision itself is the status strip and
        // the facts below, attributed by name and date.
        confidence={selected ? { value: selected.score, kind: 'estimate' } : undefined}
        status={selected ? [railStatus(selected)] : undefined}
        actions={selected ? <LinkageStatusPill status={selected.status} detailed /> : undefined}
        tabs={RAIL_TABS}
        activeTab={railTab}
        onTabChange={(id) => setRailTab(id as RailTab)}
        tabPanels={
          selected
            ? {
                evidence: (
                  <LinkageDetail
                    linkage={selected}
                    onRuled={handleRuled}
                    withAgreement
                    sections={['features']}
                  />
                ),
                limitations: <LimitationsPanel linkage={selected} scorer={railScorer} />,
                adjudication: (
                  <LinkageDetail
                    linkage={selected}
                    onRuled={handleRuled}
                    sections={['adjudication']}
                  />
                ),
              }
            : undefined
        }
      />
    </div>
  );
}

/**
 * The rail's status strip answers "who decided this", not "what is the score" —
 * the score is in the confidence meter, permanently labelled a model estimate.
 */
function railStatus(row: PersonaLinkage): InspectorStatus {
  if (row.status === 'proposed') {
    return { label: 'No ruling yet — this is a hypothesis', tone: 'warn' };
  }
  return {
    label: `Ruled ${row.status} by ${row.adjudicated_by_name ?? 'an unrecorded analyst'}`,
    tone: row.status === 'confirmed' ? 'ok' : 'danger',
  };
}

function buildFacts(row: PersonaLinkage | null): { label: string; value: string }[] {
  if (row === null) return [];
  const facts: { label: string; value: string }[] = [
    { label: 'Candidate', value: row.candidate_handle },
    { label: 'Actor', value: row.actor_handle },
    { label: 'Method', value: PERSONA_METHOD_LABELS[row.method] },
    { label: 'Proposed', value: formatDateTime(row.created_at) },
  ];
  if (row.case_name) facts.push({ label: 'Case', value: row.case_name });
  facts.push({
    label: 'Adjudicated',
    value: row.adjudicated_at
      ? `${row.adjudicated_by_name ?? 'unknown analyst'} · ${formatDateTime(row.adjudicated_at)}`
      : '— not ruled on',
  });
  if (row.rationale) facts.push({ label: 'Rationale', value: row.rationale });
  facts.push({ label: 'Linkage id', value: row.linkage_id });
  return facts;
}

function SortMark({ state }: { readonly state: 'ascending' | 'descending' | 'none' }) {
  return (
    <span className="per-sortmark" aria-hidden="true">
      {state === 'ascending' ? '▲' : state === 'descending' ? '▼' : '·'}
    </span>
  );
}

function PersonaRow({
  row,
  selected,
  expanded,
  onOpen,
  onRuled,
}: {
  readonly row: PersonaLinkage;
  readonly selected: boolean;
  readonly expanded: boolean;
  readonly onOpen: () => void;
  readonly onRuled: (response: AdjudicationResponse) => void;
}) {
  return (
    <>
      <tr
        className={`per-table__row${selected ? ' is-selected' : ''}`}
        aria-selected={selected}
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onOpen();
          }
        }}
      >
        <td className="per-td per-td--primary">
          <button
            type="button"
            className="per-rowbtn"
            aria-expanded={expanded}
            onClick={(event) => {
              event.stopPropagation();
              onOpen();
            }}
          >
            {row.candidate_handle}
          </button>
          <span className="per-td__sub">{formatDateTime(row.created_at)}</span>
        </td>
        <td className="per-td">{row.actor_handle}</td>
        <td className="per-td">{PERSONA_METHOD_LABELS[row.method]}</td>
        <td className="per-td per-td--numeric">
          <LinkageScoreBar score={row.score} linkage={row} compact />
        </td>
        <td className="per-td">
          <LinkageStatusPill status={row.status} />
        </td>
        <td className="per-td per-td--numeric">{row.aligned_features.length}</td>
        <td className="per-td per-td--numeric">{row.apart_features.length}</td>
        <td className="per-td per-td--numeric">{row.contested_features.length}</td>
        <td className="per-td">
          {row.adjudicated_at && row.adjudicated_by_name ? (
            <span className="per-td__adjudicated">
              <span className="per-td__who">{row.adjudicated_by_name}</span>
              <span className="per-td__when">{formatDateTime(row.adjudicated_at)}</span>
            </span>
          ) : (
            <span className="per-td__none">—</span>
          )}
        </td>
        <td className="per-td">{row.case_name ?? <span className="per-td__none">—</span>}</td>
      </tr>
      {expanded ? (
        <tr className="per-table__expansion">
          <td colSpan={COLUMNS.length}>
            <LinkageDetail linkage={row} onRuled={onRuled} terse />
          </td>
        </tr>
      ) : null}
    </>
  );
}
