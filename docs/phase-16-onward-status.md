# Phase 16 onward status

This is an implementation audit against the build plan, updated after the
Phase 19–21 reference implementation.

| Phase | Status | Evidence / remaining work |
| --- | --- | --- |
| 16 Attribution baseline | complete | Transparent, logistic-regression, and XGBoost baselines are in `aegis.attribution.baseline`; raw scores retain model/evidence metadata. |
| 17 Contradiction fusion | complete | Supporting, contradictory, and unknown evidence are separated, with temporal/reliability/quality and independence discounts. Tests distinguish copied from independent sources. |
| 18 Calibration | complete | Platt, isotonic, and temperature calibration plus Brier, ECE, plot-ready reliability bins, and metric slices by modality/evidence count are implemented. |
| 19 Temporal heterogeneous GNN | reference training complete | Typed graph encoders and a supervised pair-classification head are available under `aegis.gnn`. `make train-graph` runs a deterministic synthetic comparison against Phase 16 baselines and writes `artifacts/training/phase19-comparison.json`. Encoder layers are fixed deterministic NumPy transforms; only the pair head is trained. Replace with end-to-end PyTorch/PyG/DGL training and validate on authorized labeled data before operational use. |
| 20 Adversarial persona simulator | foundation complete | Deterministic L1–L5 alias/vocabulary/behaviour/platform/multimodal migrations are in `aegis.synthetic.persona_simulator`. Connect it to the benchmark runner to calculate detection latency and degradation plots. |
| 21 Benchmark and ablation | foundation complete | Actor-disjoint splitting and the L1–L5 ladder are present. Implement temporal/platform-disjoint splits, run all specified modality ablations, and persist comparison tables. |
| 22 Analyst copilot | partial | Secure types, deterministic intent routing, evidence isolation, prompt-injection indicators, citation validation, and evidence-grounded synthesis are implemented. Connect the retrieval-tool adapters and report-builder service to production stores. |
| 23 Investigation UI | partial | The React case, evidence, actor, graph, timeline, attribution, hypothesis, and report pages build successfully. API wiring and user-flow testing remain. |
| 24 Reporting + STIX | partial | Reproducible JSON, CSV, and conservative STIX 2.1 note exports preserve case/query/evidence/model/dataset provenance. Add PDF rendering and API/UI integration. |
| 25 Security hardening | partial | A security scan script and focused tests exist. Complete DAST/container scanning and operational rate-limit/access-control exercises. |
| 26 MLOps + observability | incomplete | Experiment registry scaffolding exists; metrics, traces, drift monitoring, and alerting are not implemented. |
| 27 Load/failure testing | partial | `make benchmark` records synthetic generation and candidate-scoring latency by seed/actor count; the PostgreSQL ledger integration test covers 10K rows. Add 100K/1M storage/search/graph workloads and dependency-failure injection. |
| 28 End-to-end rehearsal | partial | Synthetic analysis traverses much of the backend pipeline. Capture time-to-first-evidence, time-to-candidate, time-to-assessment, and total processing time in one rehearsal artifact. |
| 29 Research package | incomplete | Create data/model cards, experiment registry exports, benchmark plots/tables, and reproducibility instructions. |

The status labels intentionally distinguish usable reference foundations from
production/research-complete deliverables. Attribution results remain
hypotheses and must be analyst-reviewed.
