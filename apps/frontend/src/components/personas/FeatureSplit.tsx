/**
 * The three-way feature split, by name.
 *
 * This is the "Aligned / Apart" pattern, and the three lists partition the
 * scorer's vocabulary between them — a feature is in exactly one, so the counts
 * can be added up without double-counting support.
 *
 * The semantics are the part worth stating, because the obvious reading is
 * wrong. `aligned` is **not** "measured on both sides and similar", and it is
 * certainly not "measured on one side":
 *
 * - **aligned** — measured on both sides, and the two values agree closely.
 * - **apart** — measured on both sides, and the two values clearly disagree.
 * - **contested** — everything the analysis could not separate. That includes a
 *   feature measured on only one side, a feature measured inside the band where
 *   neither agreement nor disagreement can honestly be claimed, and a feature
 *   that is zero on both sides — which the similarity function scores as perfect
 *   agreement, and which is absence of evidence rather than evidence of
 *   sameness.
 *
 * So a feature only reaches `aligned` on evidence of sameness. The counts beside
 * the headings are therefore not three more ways of reading one number.
 */

import type { PersonaLinkage } from '../../api/types';

type Bucket = 'aligned' | 'apart' | 'contested';

const BUCKETS: readonly { key: Bucket; heading: string; gloss: string }[] = [
  {
    key: 'aligned',
    heading: 'Aligned',
    gloss: 'measured on both sides, and the values agree',
  },
  {
    key: 'apart',
    heading: 'Apart',
    gloss: 'measured on both sides, and the values disagree',
  },
  {
    key: 'contested',
    heading: 'Contested',
    gloss: 'not separable either way — unmeasured, degenerate, or inside the noise band',
  },
];

const LABELS: Readonly<Record<Bucket, string>> = {
  aligned: 'Aligned features',
  apart: 'Apart features',
  contested: 'Contested features',
};

function namesFor(bucket: Bucket, linkage: PersonaLinkage): readonly string[] {
  if (bucket === 'aligned') return linkage.aligned_features;
  if (bucket === 'apart') return linkage.apart_features;
  return linkage.contested_features;
}

export interface FeatureSplitProps {
  readonly linkage: PersonaLinkage;
  /**
   * Per-feature agreement, when the detail endpoint has been read. Rendered
   * beside each name; absent from the register row, which is list-shaped.
   */
  readonly agreement?: Readonly<Record<string, number>> | undefined;
  /** Hide the glossary when the block is repeated in a dense row expansion. */
  readonly terse?: boolean;
}

export function FeatureSplit({ linkage, agreement, terse = false }: FeatureSplitProps) {
  return (
    <div className="per-split">
      {!terse ? (
        <p className="per-split__gloss">
          A feature is only <strong>aligned</strong> when it was measured on both sides and the
          two values agree. A feature measured on one side only, or measured inside the band where
          neither agreement nor disagreement can be claimed, is <strong>contested</strong> — the
          three lists partition the vocabulary, so nothing is counted as support twice.
        </p>
      ) : null}
      <div className="per-split__cols">
        {BUCKETS.map(({ key, heading, gloss }) => {
          const names = namesFor(key, linkage);
          return (
            <section
              className={`per-split__col per-split__col--${key}`}
              key={key}
              aria-label={LABELS[key]}
            >
              <h4 className="per-split__heading">
                {heading}
                <span className="per-split__count">{names.length}</span>
              </h4>
              <p className="per-split__colgloss">{gloss}</p>
              {names.length === 0 ? (
                <p className="per-split__empty">none recorded</p>
              ) : (
                <ul className="per-split__names">
                  {names.map((name) => (
                    <li key={name}>
                      <span className="per-split__name">{name}</span>
                      {agreement && agreement[name] !== undefined ? (
                        <span
                          className="per-split__value"
                          title={`Agreement for ${name}: ${(agreement[name] ?? 0).toFixed(2)} of 1. A value of 1.00 can also mean the feature was zero on both sides — see Contested.`}
                        >
                          {(agreement[name] ?? 0).toFixed(2)}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
