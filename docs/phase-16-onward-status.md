# Phase 16 onward status

This is an implementation audit against the build plan, updated after the
Phase 19–21 reference implementation.

| Phase | Status | Evidence / remaining work |
| --- | --- | --- |
| 16 Attribution baseline | complete | Transparent, logistic-regression, and XGBoost baselines are in `aegis.attribution.baseline`; raw scores retain model/evidence metadata. |
| 17 Contradiction fusion | complete | Supporting, contradictory, and unknown evidence are separated, with temporal/reliability/quality and independence discounts. Tests distinguish copied from independent sources. |
| 18 Calibration | complete | Platt, isotonic, and temperature calibration plus Brier and ECE are implemented. Add reliability-diagram artifact generation and metric slices by modality/evidence count before a research release. |
| 19 Temporal heterogeneous GNN | reference complete | Typed temporal graph, deterministic R-GCN, HGT, temporal HGT, and contradiction-aware temporal HGT are available under `aegis.gnn`. They are explainable NumPy inference reference models, not yet a gradient-trained production model. |
| 20 Adversarial persona simulator | foundation complete | Deterministic L1–L5 alias/vocabulary/behaviour/platform/multimodal migrations are in `aegis.synthetic.persona_simulator`. Connect it to the benchmark runner to calculate detection latency and degradation plots. |
| 21 Benchmark and ablation | foundation complete | Actor-disjoint splitting and the L1–L5 ladder are present. Implement temporal/platform-disjoint splits, run all specified modality ablations, and persist comparison tables. |
| 22 Analyst copilot | incomplete | Secure domain types are present, but retrieval-tool implementations, synthesis, citation validation, and prompt-injection tests are still required. |
| 23 Investigation UI | partial | The React case, evidence, actor, graph, timeline, attribution, hypothesis, and report pages build successfully. API wiring and user-flow testing remain. |
| 24 Reporting + STIX | incomplete | UI scaffolding exists; reproducible CSV/JSON/PDF/STIX exports and report provenance have not been verified. |
| 25 Security hardening | partial | A security scan script and focused tests exist. Complete DAST/container scanning and operational rate-limit/access-control exercises. |
| 26 MLOps + observability | incomplete | Experiment registry scaffolding exists; metrics, traces, drift monitoring, and alerting are not implemented. |
| 27 Load/failure testing | partial | Ledger and collector integration tests exist. Add 10K/100K/1M workloads and dependency-failure injection. |
| 28 End-to-end rehearsal | partial | Synthetic analysis traverses much of the backend pipeline. Capture the prescribed timing metrics and generate a final report artifact. |
| 29 Research package | incomplete | Create data/model cards, experiment registry exports, benchmark plots/tables, and reproducibility instructions. |

The status labels intentionally distinguish usable reference foundations from
production/research-complete deliverables. Attribution results remain
hypotheses and must be analyst-reviewed.
