# AEGIS attribution model card

## Model family

The repository includes transparent weighted fusion, logistic regression,
XGBoost, and Phase 19 R-GCN/HGT/Temporal HGT reference encoders with a
supervised logistic pair head. The current graph encoders use seeded random
projections and fixed message-passing weights. They are not end-to-end learned
GNNs.

## Intended use

Rank candidate links for lawful, authorized, defensive analysis. Outputs are
hypotheses requiring analyst review. The score is not a declaration of identity
and must not be used as sole grounds for action against a person.

## Training and evaluation

Run `make train-graph` to fit baselines and GNN pair heads on the controlled
synthetic benchmark. This reports validation and test metrics. Run `make
benchmark` for scale/timing observations and `make rehearsal` for the end-to-end
synthetic investigation. These synthetic runs are pipeline checks only.

## Calibration

Platt, isotonic, and temperature calibrators plus Brier score, ECE, reliability
bins, and group slices are implemented in `aegis.attribution.calibration`.
Operational confidence requires fitting the selected calibrator only on a
representative, actor-disjoint validation set and monitoring drift. The current
Phase 19 command does not produce a deployment checkpoint or operationally
calibrated probability.

## Limitations and failure modes

- Small synthetic splits can produce deceptively high ROC-AUC and unstable F1.
- Source dependence, missing modalities, adversarial migration, label noise,
  and platform shift require dedicated evaluation.
- Pair scores may be affected by graph construction and candidate selection.
- No real-world identity claims are supported by the repository's current
  synthetic benchmark.

## Human oversight

Review supporting and contradictory evidence, provenance, temporal fit, and
independence before accepting any link. Preserve dissenting evidence and record
the analyst's decision in the case audit trail.
