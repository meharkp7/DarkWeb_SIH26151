/**
 * Everything one linkage has to say, in one place.
 *
 * Rendered twice — inline under a table row and inside the inspector rail —
 * because those are two views of the same record, and a component that exists
 * once cannot drift between them. The difference is not the content but the
 * framing: the row expansion wants all three sections at once, while the rail
 * has a tab per section so an analyst can go straight to the part they came for.
 *
 * The per-feature agreement figures come from the detail endpoint, so the rail
 * can show the terms the score was decomposed from rather than asking the reader
 * to take the three counts on trust. The register row is list-shaped and shows
 * the names without the numbers.
 */

import { useApi } from '../../hooks/useApi';
import { api } from '../../api/client';
import { DataBlock } from '../DataBlock';
import { leadFor, METRICS } from '../../lib/explain';
import type { AdjudicationResponse, PersonaLinkage, PersonaLinkageDetail } from '../../api/types';
import { AdjudicationControl } from './AdjudicationControl';
import { FeatureSplit } from './FeatureSplit';
import { LimitationsPanel } from './LimitationsPanel';

export type LinkageSection = 'features' | 'limitations' | 'adjudication';

const ALL_SECTIONS: readonly LinkageSection[] = ['features', 'limitations', 'adjudication'];

export interface LinkageDetailProps {
  readonly linkage: PersonaLinkage;
  readonly onRuled: (response: AdjudicationResponse) => void;
  /** Read the detail endpoint for the per-feature agreement. */
  readonly withAgreement?: boolean;
  /** Which sections to render. Defaults to all three. */
  readonly sections?: readonly LinkageSection[];
  /** Drop the glossary and the lead sentence; a dense row already has context. */
  readonly terse?: boolean;
}

export function LinkageDetail({
  linkage,
  onRuled,
  withAgreement = false,
  sections = ALL_SECTIONS,
  terse = false,
}: LinkageDetailProps) {
  // The rail reads the scorer's name and the agreement terms once, here, rather
  // than each section fetching the same record.
  const { data: detail } = useApi<PersonaLinkageDetail>(
    withAgreement ? api.getPersonaLinkageUrl(linkage.linkage_id) : null,
  );
  const current = detail?.linkage_id === linkage.linkage_id ? detail : undefined;

  return (
    <div className="per-detail">
      {!terse && sections.length > 1 ? (
        <p className="per-detail__lead">{leadFor(METRICS.personaLinkageDetail)}</p>
      ) : null}

      {sections.includes('features') ? (
        <DataBlock title="Feature comparison" dense>
          <FeatureSplit
            linkage={linkage}
            agreement={current?.feature_agreement}
            terse={terse}
          />
        </DataBlock>
      ) : null}

      {sections.includes('limitations') ? (
        <LimitationsPanel linkage={linkage} scorer={current?.scorer ?? undefined} />
      ) : null}

      {sections.includes('adjudication') ? (
        <DataBlock
          title="Adjudication"
          dense
          actions={
            linkage.rationale ? (
              <span className="per-detail__ruling">
                {linkage.status} by {linkage.adjudicated_by_name ?? 'an unrecorded analyst'}
              </span>
            ) : undefined
          }
        >
          <AdjudicationControl linkage={linkage} onRuled={onRuled} terse={terse} />
        </DataBlock>
      ) : null}
    </div>
  );
}
