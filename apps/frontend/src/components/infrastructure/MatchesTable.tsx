import type { InfraMatch } from '../../api/types';
import { formatDateTime, formatPercent, shortId } from '../../lib/format';
import { Limitations } from './Limitations';
import { ChannelBars, Corroboration } from './Primitives';

export type MatchSortKey = 'overall' | 'strongest' | 'corroboration' | 'detected_at';
export type SortDir = 'asc' | 'desc';

export interface MatchSort {
  readonly key: MatchSortKey;
  readonly dir: SortDir;
}

/**
 * Sort of the page the API returned.
 *
 * `corroboration` sorts by how many channels cleared their own cutoff, so an
 * analyst can put the weak, single-dimension findings at the top of the
 * queue on purpose rather than discovering them after acting on a score.
 */
export function sortMatches(rows: readonly InfraMatch[], sort: MatchSort): InfraMatch[] {
  const direction = sort.dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    switch (sort.key) {
      case 'strongest':
        return (a.strongest_channel ?? '').localeCompare(b.strongest_channel ?? '') * direction;
      case 'corroboration':
        return (a.breakdown.decisive_channels.length - b.breakdown.decisive_channels.length) * direction;
      case 'detected_at':
        return (
          (new Date(a.detected_at).getTime() - new Date(b.detected_at).getTime()) * direction
        );
      case 'overall':
      default:
        return (a.overall - b.overall) * direction;
    }
  });
}

/**
 * The correlation list: a hidden service, a candidate clearnet origin, and
 * the per-channel evidence between them.
 *
 * The corroboration column is not decoration. A match whose score rests on
 * one channel says so in its own row, at the same size as the score, because
 * those two things are not comparable findings.
 */
export function MatchesTable({
  rows,
  sort,
  onSort,
  selectedId,
  onSelect,
}: {
  readonly rows: readonly InfraMatch[];
  readonly sort: MatchSort;
  readonly onSort: (key: MatchSortKey) => void;
  readonly selectedId: string | null;
  readonly onSelect: (row: InfraMatch) => void;
}): JSX.Element {
  const columns: ReadonlyArray<{ key: MatchSortKey; label: string; numeric?: boolean }> = [
    { key: 'overall', label: 'Overall', numeric: true },
    { key: 'strongest', label: 'Strongest channel' },
    { key: 'corroboration', label: 'Corroboration' },
    { key: 'detected_at', label: 'Recorded' },
  ];

  return (
    <div className="inf-table-wrap">
      <table className="inf-table">
        <caption className="sr-only">
          Candidate origin servers: Tor hidden services paired with a clearnet host, with the
          per-channel scores behind each correlation.
        </caption>
        <thead>
          <tr>
            <th scope="col">Subject pair</th>
            {columns.map((column) => {
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
            <th scope="col">Per-channel breakdown</th>
            <th scope="col">Limitations</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.match_id}
              data-selected={row.match_id === selectedId}
              aria-selected={row.match_id === selectedId}
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
                <div className="inf-pair">
                  <div className="inf-pair__side">
                    <span className="inf-pair__tag">onion</span>
                    <span className="inf-pair__subject">{row.onion_subject}</span>
                  </div>
                  <div className="inf-pair__side">
                    <span className="inf-pair__tag">clearnet</span>
                    <span className="inf-pair__subject inf-pair__subject--clearnet">
                      {row.clearnet_subject}
                    </span>
                  </div>
                </div>
              </td>
              <td className="inf-cell--num">
                <strong className="inf-num">{formatPercent(row.overall)}</strong>
              </td>
              <td className="inf-nowrap">{row.strongest_channel ?? '—'}</td>
              <td>
                <Corroboration decisiveChannels={row.breakdown.decisive_channels} />
              </td>
              <td className="inf-nowrap inf-num">{formatDateTime(row.detected_at)}</td>
              <td>
                <ChannelBars
                  breakdown={row.breakdown}
                  strongestChannel={row.strongest_channel}
                />
              </td>
              <td>
                <Limitations notes={row.limitations} compact />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Compact form for the inspector rail, where the full table is not on screen. */
export function MatchSummary({ match }: { readonly match: InfraMatch }): JSX.Element {
  return (
    <>
      <p className="inf-caption" style={{ marginBottom: 8 }}>
        match <span className="inf-mono">{shortId(match.match_id)}</span> · case{' '}
        {match.case_id === null ? 'unattributed' : shortId(match.case_id)}
      </p>
      <ChannelBars breakdown={match.breakdown} strongestChannel={match.strongest_channel} />
      <p style={{ margin: '10px 0 4px' }}>
        <Corroboration decisiveChannels={match.breakdown.decisive_channels} />{' '}
        <span className="inf-caption">overall {formatPercent(match.overall)}</span>
      </p>
      <Limitations notes={match.limitations} alwaysOpen />
    </>
  );
}
