import { api } from '../../api/client';
import type { CollectionStatus, SourceReliabilityBand } from '../../api/types';
import { DataBlock } from '../DataBlock';
import { EmptyState, ErrorState, LoadingState } from '../States';
import { useApi } from '../../hooks/useApi';
import { formatPercent } from '../../lib/format';
import { leadFor } from '../../lib/explain';
// Colocated for the same reason as `DataBlock`: a strip that renders unstyled
// because the entry point forgot to import it is a broken strip.
import '../../styles/quality.css';

/**
 * What an analyst needs before they trust a source, in the order they need it:
 * how much of the corpus each reliability band is actually carrying, and how
 * many of those sources are one voice wearing several hats.
 *
 * Everything here is a field the API already returned. The bands are named by
 * `GET /v1/collection/status` and the figures are counted server-side, because
 * a browser that re-derived "which sources are high reliability" from a
 * different threshold would be reporting a different corpus from the one the
 * register describes — and the two would sit on the same page disagreeing.
 */

/** Word, not colour. A band carried only by a hue is invisible to some readers. */
const BAND_TONE: Readonly<Record<string, string>> = {
  high: 'strong',
  medium: 'mixed',
  low: 'weak',
};

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

function BandRow({
  band,
  totalRecords,
}: {
  readonly band: SourceReliabilityBand;
  readonly totalRecords: number;
}) {
  const share = totalRecords > 0 ? (band.records / totalRecords) * 100 : 0;
  return (
    <li className="q-band" data-band={band.band}>
      <span className="q-band__name">
        {`${BAND_TONE[band.band] ?? band.band} · ${band.band} reliability`}
      </span>
      <span className="q-band__bar" aria-hidden="true">
        <i style={{ width: `${share.toFixed(1)}%` }} />
      </span>
      <span className="q-band__figures">
        <b className="mono">{band.sources.toLocaleString('en-GB')}</b>
        {` ${plural(band.sources, 'source', 'sources')}`}
        <span className="q-band__records">
          {` · ${band.records.toLocaleString('en-GB')} `}
          {plural(band.records, 'record', 'records')}
        </span>
        <span className="q-band__contributing">
          {` · ${band.contributing_sources.toLocaleString('en-GB')} of them `}
          {band.contributing_sources === 1 ? 'has' : 'have'} produced any
        </span>
      </span>
      <span className="q-band__floor">
        {`reliability ${band.min_reliability.toFixed(2)} and above`}
      </span>
    </li>
  );
}

/**
 * The sentence an analyst is most often not told.
 *
 * Six registered sources in two groups is two observations, and an attribution
 * that leans on "six sources agree" has counted one press release six times.
 * The register's own row count cannot see this, so it is stated here in words
 * rather than left as a column the reader has to join up themselves.
 */
function independenceNote(status: CollectionStatus) {
  const { sources_total: total, independence_groups: groups, dominant_independence_group_size: dominant } =
    status;
  const lead =
    total === 0
      ? 'No sources are registered, so there is no corpus to weigh.'
      : `${total} registered ${plural(total, 'source spans', 'sources span')} ${groups} independence ${plural(groups, 'group', 'groups')}.`;

  if (total === 0) return lead;
  if (groups >= total) {
    return `${lead} Every source sits in a group of its own, so for this corpus the source count and the independent-observation count are the same number.`;
  }
  const shared = Math.max(0, total - groups);
  return (
    `${lead} That is ${shared} fewer independent ${plural(shared, 'observation', 'observations')} ` +
    `than the source count suggests, and corroboration drawn across the register is not ` +
    `${total}-fold.` +
    (dominant > 1
      ? ` The largest group holds ${dominant} of the ${total} sources: those are one outlet restated, not ${dominant} confirmations.`
      : '')
  );
}

export function SourceReliabilityStrip() {
  const status = useApi<CollectionStatus>(api.collectionStatusUrl());
  const data = status.data;
  const totalRecords = (data?.reliability_bands ?? []).reduce(
    (sum, band) => sum + band.records,
    0,
  );

  return (
    <DataBlock
      title="Source reliability"
      eyebrow="Which sources to trust, and how much they have actually produced"
      lead={leadFor('source.reliability', { count: data?.contributing_sources ?? null })}
      headingLevel={2}
    >
      {status.loading ? (
        <LoadingState label="Loading the source register…" />
      ) : status.error !== null ? (
        <ErrorState message={status.error} onRetry={status.reload} />
      ) : data === null ? (
        <EmptyState
          title="No reliability figures returned"
          message="The collection status endpoint returned nothing to weigh, so this block states no reliability rather than guessing at one."
          endpoint="GET /api/v1/collection/status"
        />
      ) : data.sources_total === 0 ? (
        <EmptyState
          title="No sources registered"
          message="Nothing has been registered to collect from, so there is no reliability to report and no records behind one."
          endpoint="GET /api/v1/collection/status"
        />
      ) : (
        <>
          <ul className="q-bands" aria-label="Records by source reliability band">
            {data.reliability_bands.map((band) => (
              <BandRow key={band.band} band={band} totalRecords={totalRecords} />
            ))}
          </ul>

          {totalRecords === 0 && (
            <p className="q-note">
              No source in this register has produced a record. Every weight above is a claim
              about an outlet, not a description of evidence in hand.
            </p>
          )}

          <p className="q-independence">{independenceNote(data)}</p>

          <dl className="q-means">
            <div>
              <dt>Mean reliability, sources that produced records</dt>
              <dd>
                {data.mean_contributing_reliability === null
                  ? '—'
                  : formatPercent(data.mean_contributing_reliability)}
              </dd>
            </div>
            <div>
              <dt>Mean reliability, all registered sources</dt>
              <dd>
                {data.mean_registered_reliability === null
                  ? '—'
                  : formatPercent(data.mean_registered_reliability)}
              </dd>
            </div>
            <div>
              <dt>Sources that produced records</dt>
              <dd>{`${data.contributing_sources} of ${data.sources_total}`}</dd>
            </div>
          </dl>
          {(data.mean_contributing_reliability === null ||
            data.mean_registered_reliability === null ||
            data.mean_contributing_reliability < data.mean_registered_reliability) && (
            <p className="q-note">
              The two means are not interchangeable. The first is the weight of the evidence in
              hand; the second is the weight of everything on the register, including the sources
              that have never run. A second figure below the first is a coverage gap, not a
              downgrade of the records that exist.
            </p>
          )}
        </>
      )}
    </DataBlock>
  );
}
