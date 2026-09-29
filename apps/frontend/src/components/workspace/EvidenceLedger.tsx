import { useMemo, useState } from 'react';
import { apiUrl } from '../../api/client';
import { SOURCE_TYPES } from '../../api/types';
import type { WorkspaceEvidence } from '../../api/types';
import { useApi } from '../../hooks/useApi';
import { formatDateTime, formatPercent, scoreTone, shortId } from '../../lib/format';
import { Badge } from '../Badge';
import { EmptyState, ErrorState, LoadingState } from '../States';
import { metaTitle } from './workspaceFormat';

export interface EvidenceLedgerProps {
  readonly caseId: string;
  /**
   * Evidence already carried by the workspace payload. Used only to derive the
   * filter option lists (entity types, independence groups) — the rows
   * themselves come from the filtered server request below.
   */
  readonly known: readonly WorkspaceEvidence[];
  /** Open the full record (hash, derivation chain, provenance) in a drawer. */
  readonly onOpenEvidence: (evidenceId: string) => void;
}

const LEDGER_ENDPOINT = 'GET /api/v1/cases/{id}/evidence';

/** A 64-character hex digest is the only integrity signal the API exposes. */
const SHA256 = /^[a-fA-F0-9]{64}$/;

function ledgerUrl(caseId: string, filters: {
  sourceType: string;
  entityType: string;
  independenceGroup: string;
  search: string;
}): string {
  const query = new URLSearchParams();
  if (filters.sourceType !== '') query.set('source_type', filters.sourceType);
  if (filters.entityType !== '') query.set('entity_type', filters.entityType);
  if (filters.independenceGroup !== '') query.set('independence_group', filters.independenceGroup);
  if (filters.search.trim() !== '') query.set('search', filters.search.trim());
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`;
  return apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/evidence${suffix}`);
}

function distinct(values: ReadonlyArray<string | null>): string[] {
  return [...new Set(values.filter((value): value is string => typeof value === 'string' && value !== ''))].sort();
}

/**
 * Evidence ledger — the case's evidence as a filterable table.
 *
 * Filtering is a server request rather than an in-memory pass: a case ledger
 * can be thousands of rows, and the count the filter returns is itself part of
 * what the analyst is reading.
 */
export function EvidenceLedger({ caseId, known, onOpenEvidence }: EvidenceLedgerProps) {
  const [sourceType, setSourceType] = useState('');
  const [entityType, setEntityType] = useState('');
  const [independenceGroup, setIndependenceGroup] = useState('');
  const [search, setSearch] = useState('');

  const url = useMemo(
    () => ledgerUrl(caseId, { sourceType, entityType, independenceGroup, search }),
    [caseId, sourceType, entityType, independenceGroup, search],
  );
  const ledger = useApi<WorkspaceEvidence[]>(url);

  const entityTypes = useMemo(() => distinct(known.map((row) => row.entity_type)), [known]);
  const groups = useMemo(() => distinct(known.map((row) => row.independence_group)), [known]);
  const rows = ledger.data ?? [];
  const dirty = sourceType !== '' || entityType !== '' || independenceGroup !== '' || search.trim() !== '';

  return (
    <div className="panel">
      <div className="panel__head">
        <div className="panel__headings">
          <h2 className="panel__title">Evidence ledger</h2>
          <p className="panel__desc">
            Every record collected against this investigation, newest first. Open a row for the
            full hash, derivation chain and provenance.
          </p>
        </div>
        <div className="panel__actions">
          <span className="surface-meta">
            {rows.length} record{rows.length === 1 ? '' : 's'}
          </span>
          <button type="button" className="btn btn--ghost btn--small" onClick={ledger.reload}>
            Refresh
          </button>
        </div>
      </div>

      <div className="inv-ledger-filters">
        <label className="sr-only" htmlFor="inv-ledger-search">
          Search evidence metadata
        </label>
        <input
          id="inv-ledger-search"
          className="inv-select"
          style={{ minWidth: 200 }}
          value={search}
          placeholder="Search metadata…"
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="sr-only" htmlFor="inv-ledger-source">
          Filter by source type
        </label>
        <select
          id="inv-ledger-source"
          className="inv-select"
          value={sourceType}
          onChange={(event) => setSourceType(event.target.value)}
        >
          <option value="">All source types</option>
          {SOURCE_TYPES.map((value) => (
            <option key={value} value={value}>
              {value.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="inv-ledger-entity">
          Filter by entity type
        </label>
        <select
          id="inv-ledger-entity"
          className="inv-select"
          value={entityType}
          onChange={(event) => setEntityType(event.target.value)}
        >
          <option value="">All entity types</option>
          {entityTypes.map((value) => (
            <option key={value} value={value}>
              {value.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="inv-ledger-group">
          Filter by independence group
        </label>
        <select
          id="inv-ledger-group"
          className="inv-select"
          value={independenceGroup}
          onChange={(event) => setIndependenceGroup(event.target.value)}
        >
          <option value="">All independence groups</option>
          {groups.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        {dirty && (
          <button
            type="button"
            className="btn btn--ghost btn--small"
            onClick={() => {
              setSourceType('');
              setEntityType('');
              setIndependenceGroup('');
              setSearch('');
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      <div className="panel__body">
        {ledger.loading && <LoadingState label="Reading evidence ledger…" />}
        {ledger.error !== null && (
          <ErrorState message={ledger.error} onRetry={ledger.reload} />
        )}
        {!ledger.loading && ledger.error === null && rows.length === 0 && (
          <EmptyState
            title="No evidence"
            message={
              dirty
                ? 'No record in this case matches the current ledger filters. Clear them to see the full ledger.'
                : 'No evidence has been collected against this investigation yet.'
            }
            endpoint={LEDGER_ENDPOINT}
          />
        )}
        {!ledger.loading && ledger.error === null && rows.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <caption className="sr-only">
                Evidence records collected against this investigation
              </caption>
              <thead>
                <tr>
                  <th scope="col">Evidence ID</th>
                  <th scope="col">Source</th>
                  <th scope="col">Type</th>
                  <th scope="col">Actor / entity</th>
                  <th scope="col">Timestamp</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Integrity</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const title = metaTitle(row.metadata);
                  const hashed = SHA256.test(row.sha256 ?? '');
                  return (
                    <tr
                      key={row.evidence_id}
                      className="inv-ledger__row"
                      onClick={() => onOpenEvidence(row.evidence_id)}
                    >
                      <td>
                        <span className="inv-id-cell">
                          <button
                            type="button"
                            className="link-button mono"
                            onClick={(event) => {
                              event.stopPropagation();
                              onOpenEvidence(row.evidence_id);
                            }}
                          >
                            {shortId(row.evidence_id, 12)}
                          </button>
                          {title !== null && <small className="table-sub">{title}</small>}
                        </span>
                      </td>
                      <td>
                        <span className="mono">{shortId(row.source_id, 10)}</span>
                      </td>
                      <td>
                        <Badge tone="info">{row.source_type.replaceAll('_', ' ')}</Badge>
                      </td>
                      <td>
                        {row.entity_type === null ? (
                          <span className="hint">not entity-bound</span>
                        ) : (
                          row.entity_type.replaceAll('_', ' ')
                        )}
                      </td>
                      <td>
                        {formatDateTime(row.observed_at ?? row.collected_at)}
                        <small className="table-sub">
                          {row.observed_at === null ? 'observed: not recorded' : 'observed'} ·
                          collected {formatDateTime(row.collected_at)}
                        </small>
                      </td>
                      <td>
                        <Badge tone={scoreTone(row.reliability)}>
                          {formatPercent(row.reliability)}
                        </Badge>
                      </td>
                      <td>
                        <span className="integrity" title={row.sha256 ?? 'no hash recorded'}>
                          {hashed ? shortId(row.sha256, 12) : '—'}
                        </span>
                      </td>
                      <td>
                        <Badge tone={hashed ? 'ok' : 'warn'}>
                          {hashed ? 'hashed' : 'no hash'}
                        </Badge>
                        <small className="table-sub mono">{row.independence_group}</small>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
