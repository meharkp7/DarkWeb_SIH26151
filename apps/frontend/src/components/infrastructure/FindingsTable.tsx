import type { InfraFinding } from '../../api/types';
import { INFRA_FINDING_KINDS, INFRA_SEVERITIES } from '../../api/types';
import { formatDateTime, shortId } from '../../lib/format';
import { Limitations } from './Limitations';
import { Confidence, Severity } from './Primitives';

export type FindingSortKey = 'detected_at' | 'severity' | 'kind' | 'confidence' | 'subject';
export type SortDir = 'asc' | 'desc';

export interface FindingSort {
  readonly key: FindingSortKey;
  readonly dir: SortDir;
}

/**
 * Client-side sort of the page the API returned.
 *
 * The filters are server-side and the *count* they return is part of what is
 * being read; the sort is applied to the rows on screen because re-fetching
 * for a column order would make a click feel like a page load. The label
 * says how many rows this is sorted over so the scope is never ambiguous.
 */
export function sortFindings(rows: readonly InfraFinding[], sort: FindingSort): InfraFinding[] {
  const direction = sort.dir === 'asc' ? 1 : -1;
  const severityRank = new Map(INFRA_SEVERITIES.map((name, index) => [name, index]));
  const kindRank = new Map(INFRA_FINDING_KINDS.map((name, index) => [name, index]));
  return [...rows].sort((a, b) => {
    switch (sort.key) {
      case 'severity':
        return ((severityRank.get(a.severity) ?? 99) - (severityRank.get(b.severity) ?? 99)) * direction;
      case 'kind':
        return ((kindRank.get(a.kind) ?? 99) - (kindRank.get(b.kind) ?? 99)) * direction;
      case 'confidence':
        // Unscored sorts last in both directions rather than to the top as
        // if zero: a detector the platform declines to score has no position
        // on a scale it is not on.
        if (a.confidence === null && b.confidence === null) return 0;
        if (a.confidence === null) return 1;
        if (b.confidence === null) return -1;
        return (a.confidence - b.confidence) * direction;
      case 'subject':
        return a.subject.localeCompare(b.subject) * direction;
      case 'detected_at':
      default:
        return (
          (new Date(a.detected_at).getTime() - new Date(b.detected_at).getTime()) * direction
        );
    }
  });
}

const COLUMNS: ReadonlyArray<{
  readonly key: FindingSortKey;
  readonly label: string;
  readonly numeric?: boolean;
}> = [
  { key: 'subject', label: 'Subject' },
  { key: 'kind', label: 'Kind' },
  { key: 'severity', label: 'Severity' },
  { key: 'confidence', label: 'Confidence', numeric: true },
  { key: 'detected_at', label: 'Detected' },
];

/**
 * The misconfiguration list.
 *
 * Every column an analyst needs to triage without a second lookup, and the
 * limitations count on the row rather than buried in a detail view — the
 * caveats are the difference between a finding and an accusation.
 */
export function FindingsTable({
  rows,
  sort,
  onSort,
  selectedId,
  onSelect,
}: {
  readonly rows: readonly InfraFinding[];
  readonly sort: FindingSort;
  readonly onSort: (key: FindingSortKey) => void;
  readonly selectedId: string | null;
  readonly onSelect: (row: InfraFinding) => void;
}): JSX.Element {
  return (
    <div className="inf-table-wrap">
      <table className="inf-table">
        <caption className="sr-only">
          Misconfigurations observed in Tor hidden services, with the benign alternative for each.
        </caption>
        <thead>
          <tr>
            {COLUMNS.map((column) => {
              const active = sort.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={column.numeric ? 'inf-cell--num' : undefined}
                >
                  <button
                    type="button"
                    onClick={() => onSort(column.key)}
                    style={{
                      all: 'unset',
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                    }}
                  >
                    {column.label}
                    <span className="inf-sort" aria-hidden="true">
                      {active ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}
                    </span>
                  </button>
                </th>
              );
            })}
            <th scope="col">Limitations</th>
            <th scope="col">Case</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.finding_id}
              data-selected={row.finding_id === selectedId}
              aria-selected={row.finding_id === selectedId}
              onClick={() => onSelect(row)}
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(row);
                }
              }}
              style={{ cursor: 'pointer' }}
            >
              <td>
                <span className="inf-mono">{row.subject}</span>
                <div className="inf-caption">
                  {row.network} · observed {formatDateTime(row.observed_at)}
                </div>
              </td>
              <td>
                <span className="inf-nowrap">{row.kind_label}</span>
                <div className="inf-caption inf-mono">{row.kind}</div>
              </td>
              <td>
                <Severity value={row.severity} />
              </td>
              <td className="inf-cell--num">
                <Confidence value={row.confidence} />
              </td>
              <td className="inf-nowrap inf-num">{formatDateTime(row.detected_at)}</td>
              <td>
                <Limitations notes={row.limitations} compact />
              </td>
              <td className="inf-caption inf-mono">
                {row.case_id === null ? 'unattributed' : shortId(row.case_id)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
