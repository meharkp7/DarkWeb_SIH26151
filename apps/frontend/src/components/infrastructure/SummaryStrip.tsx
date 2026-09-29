import type { InfraSummary } from '../../api/types';
import { INFRA_FINDING_KINDS } from '../../api/types';
import { formatCount } from '../../lib/explain';
import { formatDate, formatPercent } from '../../lib/format';

/**
 * The capability at a glance, with the weak-match figure given its own tile.
 *
 * The single-channel count is styled rather than merely printed. A dashboard
 * that showed only the total would let a 0.92 resting on one shared JA3 read
 * as the same finding as one corroborated across certificate, TLS and
 * content, and the two are not the same finding.
 */
export function SummaryStrip({ summary }: { readonly summary: InfraSummary }): JSX.Element {
  const corroborated =
    typeof summary.single_channel_matches === 'number' && typeof summary.matches_total === 'number'
      ? summary.matches_total - summary.single_channel_matches
      : null;

  return (
    <>
      <div className="inf-summary">
        <Stat
          value={summary.matches_total}
          label="correlations"
          note={`${summary.onion_services} onion · ${summary.clearnet_hosts} clearnet`}
        />
        <Stat
          value={summary.single_channel_matches}
          label="single-channel"
          variant="weak"
          note={
            corroborated === null
              ? 'score carried by one dimension'
              : `${formatCount(corroborated, 'match', 'matches')} corroborated`
          }
        />
        <Stat value={summary.findings_total} label="misconfigurations" />
        <Stat
          value={summary.findings_unscored}
          label="unscored"
          note="detectors the platform declines to score"
        />
        <Stat
          value={summary.observations_total}
          label="observations"
          note={`${
            summary.earliest_observation === null || summary.latest_observation === null
              ? 'window not returned'
              : `${formatDate(summary.earliest_observation)} → ${formatDate(summary.latest_observation)}`
          }`}
        />
      </div>

      {summary.findings_total > 0 && (
        <div className="inf-breakdown">
          {INFRA_FINDING_KINDS.map((kind) => (
            <div className="inf-breakdown__row" key={kind}>
              <span className="inf-breakdown__name">{kind.replace(/_/g, ' ')}</span>
              <span className="inf-breakdown__count">{summary.findings_by_kind[kind] ?? 0}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function Stat({
  value,
  label,
  note,
  variant,
}: {
  readonly value: number;
  readonly label: string;
  readonly note?: string;
  readonly variant?: 'weak';
}): JSX.Element {
  return (
    <div className={variant === 'weak' ? 'inf-stat inf-stat--weak' : 'inf-stat'}>
      <span className="inf-stat__value">{formatCount(value, '').trim()}</span>
      <span className="inf-stat__label">{label}</span>
      {note !== undefined && <span className="inf-stat__note">{note}</span>}
    </div>
  );
}

/**
 * The single-channel fraction, stated as a share.
 *
 * Rendered as a percentage with the numerator beside it, because "78% of
 * correlations rest on one dimension" is a different and more actionable
 * sentence than the count alone.
 */
export function WeakShare({ summary }: { readonly summary: InfraSummary }): JSX.Element {
  if (summary.matches_total === 0) {
    return <p className="inf-footnote">no correlations above the threshold in this window</p>;
  }
  const share = summary.single_channel_matches / summary.matches_total;
  return (
    <p className="inf-footnote">
      {formatPercent(share)} of correlations in this window rest on a single channel (
      {summary.single_channel_matches} of {summary.matches_total}). A single dimension is not
      corroboration, and these are the ones to read most carefully before acting on the score.
    </p>
  );
}
