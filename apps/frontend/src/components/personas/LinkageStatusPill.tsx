/**
 * The status of a linkage, drawn so the three states cannot be confused.
 *
 * Three channels carry the meaning, not one. Colour alone would fail anyone who
 * cannot separate the tones, and this row is the difference between a
 * hypothesis and a finding:
 *
 * - the **word** — `proposed`, `confirmed`, `rejected`, always spelled out;
 * - the **mark** — a hollow `?` for a proposal nobody has ruled on, a `✓` for a
 *   confirmation, a `✕` for a rejection;
 * - the **shape** — a proposal's outline is dashed, because it has no recorded
 *   decision behind it and the dashed edge says exactly that.
 */

import type { PersonaLinkageStatus } from '../../api/types';

export const PERSONA_STATUS_MARKS: Readonly<Record<PersonaLinkageStatus, string>> = {
  proposed: '?',
  confirmed: '✓',
  rejected: '✕',
};

/** Longer form for tooltips, the rail and screen-reader labels. */
export const PERSONA_STATUS_LABELS: Readonly<Record<PersonaLinkageStatus, string>> = {
  proposed: 'Proposed — a model score nobody has ruled on yet',
  confirmed: 'Confirmed — an analyst ruled this the same actor',
  rejected: 'Rejected — an analyst ruled this not the same actor',
};

export interface LinkageStatusPillProps {
  readonly status: PersonaLinkageStatus;
  /** Renders the longer label under the word. Used in the inspector rail. */
  readonly detailed?: boolean;
}

export function LinkageStatusPill({ status, detailed = false }: LinkageStatusPillProps) {
  return (
    <span
      className={`per-status per-status--${status}${detailed ? ' per-status--detailed' : ''}`}
      title={PERSONA_STATUS_LABELS[status]}
    >
      <span className="per-status__mark" aria-hidden="true">
        {PERSONA_STATUS_MARKS[status]}
      </span>
      <span className="per-status__word">{status}</span>
      {detailed ? <span className="per-status__note">{PERSONA_STATUS_LABELS[status]}</span> : null}
    </span>
  );
}
