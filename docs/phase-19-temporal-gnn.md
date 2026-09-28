# Phase 19 — Temporal Heterogeneous GNN

## Status

Phase 19 now contains two layers of implementation:

1. **NumPy reference encoders** — deterministic R-GCN, HGT and Temporal-HGT used for transparent comparison and reproducibility.
2. **Learned Temporal-HGT** — a trainable core-PyTorch implementation with relation-aware attention, node-type projections, temporal encoding, point-in-time graph construction, actor/group-disjoint splitting, early stopping, class balancing and gradient clipping.

The learned model returns `raw_score`. It must not be described as a calibrated probability until the Phase 18 calibration pipeline is applied.

## Graph contract

Production callers should construct a `HeteroGraph` through `build_gnn_graph()` from the canonical `InMemoryGraphStore`. They must provide:

- one fixed-width feature vector per included node;
- one timezone-aware observation time per included node;
- a point-in-time cutoff when evaluating historical snapshots.

The adapter deliberately does not hash identifiers or infer missing timestamps. This prevents identity leakage and silent temporal leakage.

## Temporal behavior

For a cutoff `t`, a relationship is included only when its observation interval intersects `t` and both endpoints existed by `t`. Its message timestamp is clipped to the cutoff when necessary. Edge recency is converted into an exponential half-life weight during message passing.

## Learned model

`TemporalHeterogeneousGNN` contains:

- per-node-type input projections;
- node-type embeddings;
- sinusoidal temporal encoding;
- relation-specific key/value projections;
- node-type-specific query projections;
- multi-head attention;
- temporal half-life weighting;
- residual connections, LayerNorm, GELU and dropout;
- pair decoder using `|h_i-h_j|` and `h_i ⊙ h_j`;
- explicit contradiction logit penalty.

The implementation uses core PyTorch only; PyG/DGL are not required.

## Leakage controls

The production experiment must keep feature generation point-in-time as well as graph topology point-in-time. The provided `split_by_group()` prevents the same actor group from appearing in multiple evaluation partitions. For a strict inductive experiment, construct separate train/validation/test graph snapshots so test-only nodes and edges are absent from training.

## Required comparison

The final benchmark should retain:

- XGBoost;
- deterministic R-GCN;
- deterministic HGT;
- deterministic Temporal-HGT;
- learned Temporal-HGT;
- learned Temporal-HGT + contradiction.

Calibration should be evaluated separately using Brier score and ECE from Phase 18.
