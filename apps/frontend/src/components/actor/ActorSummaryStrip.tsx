import { Link } from 'react-router-dom';
import type { ActorSummary } from '../../api/types';

export interface ActorSummaryStripProps {
  readonly summary: ActorSummary | null;
}

/**
 * The four registry-wide figures, each paired with the filter that produces it.
 *
 * A tile that cannot be clicked through to the thing it counts is decoration,
 * so every tile that *has* a filter behind it is a link into the register
 * filtered to exactly that condition. `unassessed` is carried in the subtitle
 * because it is the population a confidence filter silently excludes, and a
 * silent exclusion is the thing this console keeps arguing against.
 *
 * The stale figure is deliberately not a link: the registry API takes no stale
 * filter, and linking to a URL that would silently ignore the parameter would be
 * a tile that counts something and does nothing.
 */
export function ActorSummaryStrip({ summary }: ActorSummaryStripProps) {
  if (summary === null) return null;

  const active = summary.by_status.find((row) => row.status === 'active');
  const largest = summary.by_category[0];

  return (
    <div className="act-summary">
      <Tile
        to="/actors"
        label="Actors"
        value={summary.total}
        sub={`${summary.identifiers} identifiers · ${summary.marketplaces} venue presences`}
      />
      <Tile
        to="/actors?status=active"
        label="Active"
        value={active?.count ?? 0}
        sub="status is active"
      />
      {largest !== undefined && (
        <Tile
          to={`/actors?category=${encodeURIComponent(largest.category)}`}
          label="Largest category"
          value={largest.count}
          sub={largest.category}
        />
      )}
      <Tile
        label={`Not scanned in ${summary.stale_days}d`}
        value={summary.stale}
        sub={`${summary.unassessed} never assessed`}
        warn={summary.stale > 0}
      />
    </div>
  );
}

function Tile({
  to,
  label,
  value,
  sub,
  warn = false,
}: {
  to?: string;
  label: string;
  value: number;
  sub: string;
  warn?: boolean;
}) {
  const className = warn ? 'act-tile act-tile--warn' : 'act-tile';
  const body = (
    <>
      <span className="act-tile__value">{value}</span>
      <span className="act-tile__label">{label}</span>
      <span className="act-tile__sub">{sub}</span>
    </>
  );
  if (to === undefined) {
    return (
      <div className={className} title={`${label}: ${value} — ${sub}`}>
        {body}
      </div>
    );
  }
  return (
    <Link className={className} to={to} title={`${label}: ${value} — ${sub}`}>
      {body}
    </Link>
  );
}