import { Link } from 'react-router-dom';
import type { InspectorStatus } from '../InspectorRail';
import { Badge } from '../Badge';
import type { Tone } from '../Badge';
import { formatDate, formatPercent } from '../../lib/format';
import type { ActorRegistryRow, PersonaLinkageSummary } from '../../api/types';
import { ActorConfidence } from './ActorConfidence';
import { ActorKindGlyphs } from './ActorKindGlyphs';

const STATUS_RAIL_TONE: Record<string, 'ok' | 'warn' | 'danger' | 'muted'> = {
  active: 'ok',
  dormant: 'warn',
  rebranded: 'muted',
  retired: 'muted',
  unknown: 'muted',
};

const LINKAGE_TONE: Record<string, Tone> = {
  proposed: 'info',
  confirmed: 'ok',
  rejected: 'danger',
};

/**
 * Rail content for one registry row.
 *
 * The same shapes the investigations register uses, for the same reasons: a
 * status is colour *and* word, a confidence is a number *and* its basis, and a
 * count the API did not return is absent rather than zero. The rail never
 * navigates on its own — the action link is the way in, and selecting a row
 * leaves the register where it is.
 */
export function actorRailProps(actor: ActorRegistryRow, staleDays: number | null, onClose: () => void) {
  const kindChips = Object.entries(actor.identifier_kinds)
    .filter(([, count]) => count > 0)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([kind, count]) => ({ kind, value: `${count}×` }));

  return {
    open: true,
    onClose,
    title: actor.handle,
    subtitle: `${actor.category} · ${actor.status}`,
    status: [
      { label: actor.status, tone: STATUS_RAIL_TONE[actor.status] ?? 'muted' },
      {
        label: `${actor.identifier_count} identifier${actor.identifier_count === 1 ? '' : 's'}`,
        tone: 'muted',
      },
      {
        label: `${actor.marketplace_count} venue${actor.marketplace_count === 1 ? '' : 's'}`,
        tone: 'muted',
      },
    ] satisfies readonly InspectorStatus[],
    facts: [
      { label: 'Confidence', value: <ActorConfidence confidence={actor.confidence} compact /> },
      { label: 'First seen', value: formatDate(actor.first_seen) },
      { label: 'Last seen', value: formatDate(actor.last_seen) },
      { label: 'Last scan', value: formatDate(actor.last_scan_at) },
      { label: 'Source', value: actor.source_name ?? 'no source recorded' },
      { label: 'Linked investigations', value: actor.case_link_count, mono: true },
      { label: 'Actor ID', value: actor.actor_id, mono: true },
    ],
    identifiers: kindChips.length === 0 ? undefined : kindChips,
    confidence:
      actor.confidence === null ? undefined : { value: actor.confidence, kind: 'recorded' as const },
    summary:
      staleDays !== null && actor.last_scan_at === null
        ? `Never re-scanned. The registry reports ${staleDays} days as its stale threshold.`
        : undefined,
    actions: (
      <Link className="btn btn--primary insp-rail__action" to={`/actors/${encodeURIComponent(actor.actor_id)}`}>
        Open profile →
      </Link>
    ),
    empty: 'No actor selected.',
  };
}

/** Count plus kind glyphs: "six identifiers" reads as "two keys and a wallet". */
export function ActorIdentifierCell({ actor }: { actor: ActorRegistryRow }) {
  return (
    <>
      <span>{actor.identifier_count}</span>
      <ActorKindGlyphs kinds={actor.identifier_kinds} />
    </>
  );
}

export interface PersonaLinkageListProps {
  readonly linkages: readonly PersonaLinkageSummary[];
}

/**
 * Proposed merges of a candidate handle into this actor.
 *
 * A linkage is a proposal until an analyst rules on it, so the status badge is
 * the difference between "the platform suggests these are one person" and "an
 * analyst has said so". The model's score sits beside the ruling rather than
 * being replaced by it — a rejected 0.94 is exactly the row somebody most
 * needs to be able to read back.
 */
export function PersonaLinkageList({ linkages }: PersonaLinkageListProps) {
  if (linkages.length === 0) {
    return (
      <p className="hint">
        No persona linkages are on file for this actor. That means nothing has been proposed — not
        that no relationship exists.
      </p>
    );
  }
  return (
    <ul className="act-linkage-list">
      {linkages.map((linkage) => (
        <li className="act-linkage" key={linkage.linkage_id}>
          <div className="act-linkage__head">
            <span className="act-linkage__handle">{linkage.candidate_handle}</span>
            <Badge tone={LINKAGE_TONE[linkage.status] ?? 'neutral'}>{linkage.status}</Badge>
            <span className="hint">{linkage.method}</span>
            <span className="act-linkage__score">
              {formatPercent(linkage.score)}
              <span className="sr-only"> model score, unchanged by the analyst ruling</span>
            </span>
          </div>
          <div className="act-features">
            {linkage.aligned_features.map((feature) => (
              <span className="act-feature act-feature--aligned" key={`aligned-${feature}`}>
                {`aligned: ${feature}`}
              </span>
            ))}
            {linkage.apart_features.map((feature) => (
              <span className="act-feature act-feature--apart" key={`apart-${feature}`}>
                {`apart: ${feature}`}
              </span>
            ))}
            {linkage.contested_features.map((feature) => (
              <span className="act-feature act-feature--contested" key={`contested-${feature}`}>
                {`contested: ${feature}`}
              </span>
            ))}
          </div>
          {linkage.rationale !== null && <p className="hint">{linkage.rationale}</p>}
        </li>
      ))}
    </ul>
  );
}