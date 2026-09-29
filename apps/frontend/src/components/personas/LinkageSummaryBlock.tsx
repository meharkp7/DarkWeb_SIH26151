/**
 * Counts over the register, and the one pair of numbers worth reading.
 *
 * The pair is the model's **observed** error rate: confirmations the scorer
 * ranked below the threshold, and rejections it ranked at or above it. Both are
 * counted from analyst decisions rather than reported by the scorer, which is
 * the only version of the number a reader can check — and the reason this block
 * leads with them rather than with the totals.
 *
 * The denominators and the threshold are printed rather than assumed, so a
 * "0 errors" reading over a register of two never looks like a clean bill of
 * health. When nothing here has been adjudicated the block prints the server's
 * `gap` sentence instead of a rate over an empty denominator.
 */

import { DataBlock } from '../DataBlock';
import { formatCount, leadFor, METRICS } from '../../lib/explain';
import type { PersonaLinkageCounts } from '../../api/types';

export interface LinkageSummaryBlockProps {
  readonly summary: PersonaLinkageCounts | null;
  /** Row count the register is showing, so the two can be compared at a glance. */
  readonly shown: number;
  readonly filtersActive: boolean;
}

export function LinkageSummaryBlock({ summary, shown, filtersActive }: LinkageSummaryBlockProps) {
  if (summary === null) {
    return (
      <DataBlock title="Linkage summary" lead={leadFor(METRICS.personaLinkageSummary)} dense>
        <p className="per-empty">Loading the counts for this view…</p>
      </DataBlock>
    );
  }

  const falseNegatives = summary.confirmed_low_score;
  const falsePositives = summary.rejected_high_score;
  const threshold = summary.score_threshold.toFixed(2);

  return (
    <DataBlock
      title="Linkage summary"
      lead={leadFor(METRICS.personaLinkageSummary)}
      actions={
        <span className="per-summary__scope">
          {filtersActive
            ? `${formatCount(shown, 'linkage')} in this view of ${formatCount(summary.total, 'linkage')}`
            : `${formatCount(summary.total, 'linkage')} on file`}
        </span>
      }
    >
      <div className="per-summary">
        <ul className="per-summary__strip">
          <SummaryTile label="Proposals" value={summary.proposed} note="awaiting a ruling" />
          <SummaryTile
            label="Confirmed"
            value={summary.confirmed}
            note="analyst-recorded findings"
            emphasis="ok"
          />
          <SummaryTile
            label="Rejected"
            value={summary.rejected}
            note="ruled not the same actor"
            emphasis="danger"
          />
        </ul>

        <div className="per-summary__errors">
          <h4 className="per-summary__errorsheading">
            Where analysts overruled the model, against the {threshold} line
          </h4>
          {summary.gap ? (
            <p className="per-summary__gap">{summary.gap}</p>
          ) : (
            <ul className="per-summary__errorlist">
              <ErrorTile
                label="Rejected despite a high score"
                count={falsePositives}
                denominator={summary.rejected_total}
                note="model's false positives, as observed"
                emphasis="danger"
              />
              <ErrorTile
                label="Confirmed despite a low score"
                count={falseNegatives}
                denominator={summary.confirmed_total}
                note="model's false negatives, as observed"
                emphasis="ok"
              />
            </ul>
          )}
        </div>

        <p className="per-summary__methods">
          By method:{' '}
          {Object.entries(summary.by_method)
            .filter(([, count]) => count > 0)
            .map(([method, count]) => `${method} ${count}`)
            .join(' · ') || 'none recorded'}
        </p>
      </div>
    </DataBlock>
  );
}

function SummaryTile({
  label,
  value,
  note,
  emphasis,
}: {
  readonly label: string;
  readonly value: number;
  readonly note: string;
  readonly emphasis?: 'ok' | 'danger';
}) {
  return (
    <li className={`per-summary__tile${emphasis ? ` per-summary__tile--${emphasis}` : ''}`}>
      <span className="per-summary__tilelabel">{label}</span>
      <span className="per-summary__tilevalue">{value.toLocaleString('en-GB')}</span>
      <span className="per-summary__tilenote">{note}</span>
    </li>
  );
}

function ErrorTile({
  label,
  count,
  denominator,
  note,
  emphasis,
}: {
  readonly label: string;
  readonly count: number;
  readonly denominator: number;
  readonly note: string;
  readonly emphasis: 'ok' | 'danger';
}) {
  return (
    <li className={`per-summary__error per-summary__error--${emphasis}`}>
      <span className="per-summary__errorlabel">{label}</span>
      <span className="per-summary__errorvalue">
        {count.toLocaleString('en-GB')}
        <span className="per-summary__errorden"> of {denominator.toLocaleString('en-GB')}</span>
      </span>
      <span className="per-summary__errornote">
        {denominator > 0 ? `${Math.round((count / denominator) * 100)}% — ${note}` : note}
      </span>
    </li>
  );
}
