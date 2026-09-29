import { formatDate } from '../../lib/format';

const DAY_MS = 86_400_000;

/**
 * When an actor was last re-scanned, and whether that is a problem.
 *
 * "Never scanned" and "scanned long ago" are different failures with different
 * remedies, so they get different marks. The staleness threshold is the one
 * the API reports in its summary rather than a number baked into this
 * component: when the backend changes its definition of stale, the mark changes
 * with it instead of quietly disagreeing with the summary tile.
 *
 * With no threshold available there is no mark at all. Rendering a stale
 * indicator against an invented cut-off would be exactly the kind of number
 * this console refuses to show.
 */
export interface ActorScanMarkProps {
  readonly lastScanAt: string | null;
  /** Threshold in days, from `GET /api/v1/actors/summary`. */
  readonly staleDays: number | null;
}

export function ActorScanMark({ lastScanAt, staleDays }: ActorScanMarkProps) {
  if (lastScanAt === null) {
    return (
      <span className="act-stale act-stale--none">
        <span className="act-stale__dot" aria-hidden="true" />
        <span>never scanned</span>
      </span>
    );
  }

  const scanned = new Date(lastScanAt).getTime();
  const ageDays = Number.isFinite(scanned) ? Math.floor((Date.now() - scanned) / DAY_MS) : null;
  const stale = staleDays !== null && ageDays !== null && ageDays > staleDays;

  return (
    <span className={stale ? 'act-stale' : 'act-stale act-stale--none'}>
      <span className="act-stale__dot" aria-hidden="true" />
      <span>{formatDate(lastScanAt)}</span>
      {stale && (
        <span className="sr-only">
          {` — last scanned ${ageDays} days ago, beyond the ${staleDays}-day threshold this registry reports`}
        </span>
      )}
    </span>
  );
}