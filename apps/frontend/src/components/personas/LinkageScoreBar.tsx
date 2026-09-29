/**
 * A model score, drawn as a bar and a number, and labelled as what it is.
 *
 * The bar is hand-rolled SVG: no dependency, and the two rectangles are the
 * whole thing. Its width is the score; nothing else about it is data.
 *
 * Two rules keep the number from reading as a conclusion:
 *
 * 1. An **unreviewed** score is drawn in the muted ink, not the magnitude tone.
 *    A green bar beside `proposed` would say "good" where the row means
 *    "unexamined", and that gap between what a colour implies and what the row
 *    says is exactly the misreading this surface exists to prevent.
 * 2. The caption under the number always calls it a model estimate, even on a
 *    confirmed linkage. The score did not stop being a model output because a
 *    human agreed with it — the *decision* is what an analyst recorded, and it
 *    is attributed separately, by name and date.
 */

import type { PersonaLinkage } from '../../api/types';

const BAR_WIDTH = 100;
const BAR_HEIGHT = 6;

export interface LinkageScoreBarProps {
  readonly score: number;
  readonly linkage: Pick<PersonaLinkage, 'status' | 'adjudicated_by_name' | 'adjudicated_at'>;
  /** Rendered inside a dense table cell; omit for the inspector rail. */
  readonly compact?: boolean;
}

/** Prose for the number, so the row is readable without seeing the bar. */
function scoreCaption(linkage: LinkageScoreBarProps['linkage']): string {
  if (linkage.status === 'proposed') return 'model estimate · not reviewed';
  const who = linkage.adjudicated_by_name ?? 'an analyst';
  const verb = linkage.status === 'confirmed' ? 'confirmed' : 'rejected';
  return `model estimate · ${who} ${verb} it`;
}

export function LinkageScoreBar({ score, linkage, compact = false }: LinkageScoreBarProps) {
  const clamped = Math.max(0, Math.min(1, score));
  const percent = clamped * 100;
  const reviewed = linkage.status !== 'proposed';
  const label = `Model estimate ${clamped.toFixed(2)} of 1. ${scoreCaption(linkage)}`;

  return (
    <span className={`per-score${compact ? ' per-score--compact' : ''}`}>
      <svg
        className="per-score__bar"
        viewBox={`0 0 ${BAR_WIDTH} ${BAR_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={label}
        focusable="false"
      >
        <title>{label}</title>
        <rect className="per-score__track" x={0} y={0} width={BAR_WIDTH} height={BAR_HEIGHT} rx={3} />
        <rect
          className={`per-score__fill${reviewed ? '' : ' per-score__fill--unreviewed'}`}
          x={0}
          y={0}
          width={percent}
          height={BAR_HEIGHT}
          rx={3}
        />
      </svg>
      <span className="per-score__value">{clamped.toFixed(2)}</span>
      <span className="per-score__caption">{scoreCaption(linkage)}</span>
    </span>
  );
}
