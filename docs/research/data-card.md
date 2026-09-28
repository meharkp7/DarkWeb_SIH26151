# AEGIS synthetic data card

## Dataset identity

- Generator: `aegis.synthetic.generator.SyntheticActorGenerator` and
  `aegis.synthetic.evidence_generator.SyntheticEvidenceGenerator`.
- Version: current repository implementation; record the Git commit and seed
  with every generated artifact.
- Intended use: software integration, regression checks, and controlled
  algorithm development only.
- Prohibited interpretation: synthetic results do not estimate real-world
  actor attribution accuracy, source reliability, or operational effectiveness.

## Composition and labels

The generator emits synthetic actor profiles, platform handles, writing-style
tokens, timezone observations, wallet indicators, timestamps, and
within-actor evidence relationships. Ground-truth links are explicitly
controlled in the generator and benchmark helpers. `scripts/train_graph_models.py`
creates a separate deterministic feature-level pair dataset with isolated
four-actor groups and one positive pair per group.

## Splits and leakage controls

The Phase 19 training command separates groups into train, validation, and test
cohorts before fitting baselines or pair heads. The Phase 21 utilities also
provide actor-disjoint, temporal, and platform-disjoint split primitives.
Report the split method and seed; do not tune on test scores.

## Known limitations

- Synthetic feature distributions are hand-controlled and much cleaner than
  collected intelligence.
- The Phase 19 encoders are deterministic NumPy reference transforms; only the
  pair classifier is supervised-trained.
- The generator's fixed positive links are not a representative prevalence
  estimate.
- No real personal data or collected dark-web content belongs in the synthetic
  artifacts.

## Versioning checklist

For each dataset artifact, retain generator version, seed, actor count, pair
construction rules, split assignments, evidence schema version, and a content
hash. Preserve synthetic labels separately from observed evidence in any future
real-data pipeline.
