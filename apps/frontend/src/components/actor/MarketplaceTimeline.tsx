import { formatDate } from '../../lib/format';
import type { ActorMarketplacePresence } from '../../api/types';

const DAY_MS = 86_400_000;

/**
 * Where a persona traded, as presence windows on one shared time axis.
 *
 * The second core capability is mapping one actor across many venues, and the
 * question that matters is comparative — "still on two of the four, gone from
 * the others" — so the venues share an axis instead of each getting its own
 * bar. Hand-drawn SVG-free geometry: four absolutely-positioned spans, which is
 * all a presence window needs to be legible and is one less dependency than a
 * charting library.
 *
 * Every value on screen is a date the API returned. There is no default start
 * for a window whose `first_seen` is missing: an open-ended bar would be a
 * shape the data does not support.
 */
export interface MarketplaceTimelineProps {
  readonly presences: readonly ActorMarketplacePresence[];
}

export function MarketplaceTimeline({ presences }: MarketplaceTimelineProps) {
  const bounds = timeBounds(presences);
  if (bounds === null) {
    return (
      <p className="hint">
        No marketplace presence is on file for this actor, so there is no window to draw. That is an
        absence of records rather than a claim that the actor has never traded.
      </p>
    );
  }

  const span = Math.max(bounds.to - bounds.from, DAY_MS);

  return (
    <div>
      {presences.map((presence) => {
        const first = presence.first_seen === null ? null : new Date(presence.first_seen).getTime();
        const last = presence.last_seen === null ? null : new Date(presence.last_seen).getTime();
        const start = first ?? bounds.from;
        const end = last ?? bounds.to;
        const left = ((start - bounds.from) / span) * 100;
        const width = Math.max(1.5, ((end - start) / span) * 100);
        const open = presence.last_seen === null;

        return (
          <div className="act-venue" key={presence.presence_id}>
            <span>
              <span className="act-venue__name">{presence.marketplace}</span>
              {presence.role !== null && <span className="act-venue__role"> · {presence.role}</span>}
            </span>
            <span
              className="act-tl"
              role="img"
              aria-label={`${presence.marketplace}: seen from ${formatDate(presence.first_seen)} to ${formatDate(presence.last_seen)}${presence.listing_count === null ? '' : `, ${presence.listing_count} listings`}`}
            >
              <i
                className={open ? 'act-tl__span act-tl__span--open' : 'act-tl__span act-tl__span--closed'}
                style={{ left: `${Math.min(98, Math.max(0, left))}%`, width: `${Math.min(100, width)}%` }}
              />
              <i className="act-tl__now" style={{ left: `${((bounds.now - bounds.from) / span) * 100}%` }} />
            </span>
            <span className="act-venue__window">
              {formatDate(presence.first_seen)} → {formatDate(presence.last_seen)}
              {presence.listing_count === null ? '' : ` · ${presence.listing_count} listings`}
            </span>
          </div>
        );
      })}
      <div className="act-tl__axis">
        <span>{formatDate(new Date(bounds.from).toISOString())}</span>
        <span>now</span>
        <span>{formatDate(new Date(bounds.to).toISOString())}</span>
      </div>
    </div>
  );
}

/**
 * The axis every venue is drawn against: the earliest presence start through
 * whichever is later, the last presence end or now.
 *
 * Extending the axis to today rather than to the last sighting is deliberate —
 * a venue abandoned two years ago must be visibly *abandoned*, and an axis that
 * stopped at the last sighting would draw it as if it were still open.
 */
function timeBounds(presences: readonly ActorMarketplacePresence[]): {
  from: number;
  to: number;
  now: number;
} | null {
  let from = Number.POSITIVE_INFINITY;
  let to = Number.NEGATIVE_INFINITY;
  for (const presence of presences) {
    const first = presence.first_seen === null ? null : new Date(presence.first_seen).getTime();
    const last = presence.last_seen === null ? null : new Date(presence.last_seen).getTime();
    if (first !== null && Number.isFinite(first)) from = Math.min(from, first);
    if (last !== null && Number.isFinite(last)) to = Math.max(to, last);
  }
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  const now = Date.now();
  return { from, to: Math.max(to, now), now };
}