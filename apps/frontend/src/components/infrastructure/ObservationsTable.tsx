import type { InfraObservation } from '../../api/types';
import { formatDateTime, shortId } from '../../lib/format';

export type ObservationSortKey = 'observed_at' | 'network' | 'source' | 'subject' | 'relations';
export type SortDir = 'asc' | 'desc';

export interface ObservationSort {
  readonly key: ObservationSortKey;
  readonly dir: SortDir;
}

export function sortObservations(
  rows: readonly InfraObservation[],
  sort: ObservationSort,
): InfraObservation[] {
  const direction = sort.dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    switch (sort.key) {
      case 'network':
        return a.network.localeCompare(b.network) * direction;
      case 'source':
        return a.source.localeCompare(b.source) * direction;
      case 'subject':
        return a.subject.localeCompare(b.subject) * direction;
      case 'relations':
        return (
          (a.finding_count + a.match_count - (b.finding_count + b.match_count)) * direction
        );
      case 'observed_at':
      default:
        return (
          (new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime()) * direction
        );
    }
  });
}

function text(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '—';
}

/**
 * The extracted features of one observation, read off the stored document.
 *
 * The document is returned whole rather than pre-formatted by the API, so the
 * numbers a correlation was computed from can be checked against the score it
 * produced instead of taken on trust. Anything the extractor did not observe
 * reads "not captured" — never 0, and never a blank that reads as a value.
 */
export function FeatureDigest({ features }: { readonly features: Readonly<Record<string, unknown>> }): JSX.Element {
  const inner = (features.observation ?? {}) as Record<string, unknown>;
  const tls = (inner.tls ?? {}) as Record<string, unknown>;
  const http = (inner.http ?? {}) as Record<string, unknown>;
  const certificate = (inner.certificate ?? {}) as Record<string, unknown>;
  const content = (features.content ?? null) as Record<string, unknown> | null;
  const window = (inner.observed_range ?? {}) as Record<string, unknown>;
  const technologies = Array.isArray(inner.technologies) ? inner.technologies : [];

  const lines: ReadonlyArray<[string, string]> = [
    ['TLS version', text(tls.version)],
    ['Cipher suite', text(tls.cipher_suite)],
    ['ALPN', Array.isArray(tls.alpn) ? tls.alpn.join(', ') : 'not captured'],
    ['JA3 client fingerprint', text(tls.ja3)],
    ['HTTP status', text(http.status_code)],
    ['Server banner', text(http.server)],
    ['Content type', text(http.content_type)],
    [
      'Response headers',
      http.headers && typeof http.headers === 'object'
        ? Object.keys(http.headers as Record<string, unknown>).join(', ') || 'none captured'
        : 'not captured',
    ],
    ['Certificate subject', text(certificate.subject)],
    ['Certificate issuer', text(certificate.issuer)],
    ['Certificate serial', text(certificate.serial_number)],
    ['Certificate fingerprint', text(certificate.fingerprint_sha256)],
    [
      'Certificate SANs',
      Array.isArray(certificate.sans) ? certificate.sans.join(', ') : 'not captured',
    ],
    ['Certificate valid from', text(certificate.not_before)],
    ['Certificate valid to', text(certificate.not_after)],
    ['Content SHA-256', text(content?.sha256)],
    ['Content simhash (64-bit)', content?.simhash === undefined ? 'not captured' : text(content?.simhash)],
    [
      'Technologies',
      technologies.length === 0
        ? 'not captured'
        : technologies.map((item) => text(item)).join(', '),
    ],
    ['Observation window start', text(window.start)],
    ['Observation window end', text(window.end)],
  ];

  return (
    <dl className="inf-kv">
      {lines.map(([key, value]) => (
        <div className="inf-kv__row" key={key}>
          <dt className="inf-kv__key">{key}</dt>
          <dd className={value === 'not captured' ? 'inf-kv__value inf-muted' : 'inf-kv__value'}>
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * The observation register: what was seen, where it came from, and what was
 * derived from it.
 */
export function ObservationsTable({
  rows,
  sort,
  onSort,
  selectedId,
  onSelect,
}: {
  readonly rows: readonly InfraObservation[];
  readonly sort: ObservationSort;
  readonly onSort: (key: ObservationSortKey) => void;
  readonly selectedId: string | null;
  readonly onSelect: (row: InfraObservation) => void;
}): JSX.Element {
  const columns: ReadonlyArray<{ key: ObservationSortKey; label: string }> = [
    { key: 'subject', label: 'Subject' },
    { key: 'network', label: 'Network' },
    { key: 'source', label: 'Source' },
    { key: 'observed_at', label: 'Observed' },
    { key: 'relations', label: 'Relations' },
  ];

  return (
    <div className="inf-table-wrap">
      <table className="inf-table">
        <caption className="sr-only">
          Stored infrastructure observations and the features extracted from each one.
        </caption>
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
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
            <th scope="col">Extracted features</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.observation_id}
              data-selected={row.observation_id === selectedId}
              aria-selected={row.observation_id === selectedId}
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
                <div className="inf-caption inf-mono">{shortId(row.observation_id)}</div>
              </td>
              <td className="inf-nowrap">
                <span className={row.network === 'onion' ? 'badge badge--info' : 'badge badge--neutral'}>
                  {row.network}
                </span>
              </td>
              <td>{row.source}</td>
              <td className="inf-nowrap inf-num">
                {formatDateTime(row.observed_at)}
                {row.observed_until !== null && (
                  <div className="inf-caption">window to {formatDateTime(row.observed_until)}</div>
                )}
              </td>
              <td className="inf-num">
                {row.finding_count} finding{row.finding_count === 1 ? '' : 's'}
                <div className="inf-caption">
                  {row.match_count} match{row.match_count === 1 ? '' : 'es'}
                </div>
              </td>
              <td>
                <details>
                  <summary className="inf-caption" style={{ cursor: 'pointer' }}>
                    show extracted features
                  </summary>
                  <div style={{ marginTop: 8, minWidth: 280 }}>
                    <FeatureDigest features={row.features} />
                  </div>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
