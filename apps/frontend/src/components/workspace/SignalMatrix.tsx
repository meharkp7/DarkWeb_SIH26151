import { Badge } from '../Badge';
import type { Tone } from '../Badge';
import { EmptyState, ErrorState, LoadingState } from '../States';
import type { ApiResource } from '../../hooks/useApi';
import type { Band, SignalBand } from '../../api/types';

export interface SignalMatrixProps {
  /** Case-scoped signal bands, already fetched by the page. */
  readonly signals: ApiResource<SignalBand[]>;
}

const SIGNALS_ENDPOINT = 'GET /api/v1/cases/{id}/signals';

const SUPPORT_TONE: Record<Band, Tone> = { HIGH: 'ok', MEDIUM: 'warn', LOW: 'danger' };
const CONTRADICT_TONE: Record<Band, Tone> = { HIGH: 'danger', MEDIUM: 'warn', LOW: 'ok' };

/**
 * A band on its own is unreadable in a dense table, so every cell carries the
 * band word *and* the number behind it. The number is what an analyst can
 * check against the ledger; the band is only there to make columns scannable.
 */
function BandCell({ band, value, tone }: { band: Band; value: number; tone: Tone }) {
  return (
    <span className="inv-band">
      <Badge tone={tone}>{band}</Badge>
      <span className="inv-band__value">{value.toFixed(3)}</span>
    </span>
  );
}

function Modality({ value }: { value: string }) {
  return <span className="inv-matrix__modality">{value.replaceAll('_', ' ')}</span>;
}

function Freshness({ value }: { value: number }) {
  const clamped = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  return (
    <span className="inv-freshness">
      <span className="inv-band__value">{clamped.toFixed(3)}</span>
      <span className="inv-freshness__track" aria-hidden="true">
        <i style={{ width: `${Math.round(clamped * 100)}%` }} />
      </span>
    </span>
  );
}

/**
 * Case signal matrix — the per-modality support / contradiction / freshness
 * band for one investigation.
 *
 * Rendered as a real table rather than a set of coloured chips: an attribution
 * claim that cannot be read column-by-column is a claim nobody can challenge.
 */
export function SignalMatrix({ signals }: SignalMatrixProps) {
  if (signals.loading) return <LoadingState label="Loading case signals…" />;
  if (signals.error !== null) return <ErrorState message={signals.error} onRetry={signals.reload} />;

  const rows = signals.data ?? [];
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No signal matrix"
        message="No per-modality support, contradiction or freshness band has been computed for this investigation."
        endpoint={SIGNALS_ENDPOINT}
      />
    );
  }

  return (
    <div className="table-wrap">
      <table className="inv-matrix">
        <caption className="sr-only">
          Signal matrix: support, contradiction and freshness per modality
        </caption>
        <thead>
          <tr>
            <th scope="col">Modality</th>
            <th scope="col">Support</th>
            <th scope="col">Contradict</th>
            <th scope="col">Freshness</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.modality}>
              <th scope="row">
                <Modality value={row.modality} />
              </th>
              <td>
                <BandCell band={row.support} value={row.support_value} tone={SUPPORT_TONE[row.support]} />
              </td>
              <td>
                <BandCell
                  band={row.contradict}
                  value={row.contradict_value}
                  tone={CONTRADICT_TONE[row.contradict]}
                />
              </td>
              <td>
                <Freshness value={row.freshness} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
