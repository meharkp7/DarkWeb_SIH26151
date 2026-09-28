# Phase 16 onward status

This audit tracks the implementation against the AEGIS build plan. The stack is
synthetic-first and analyst-reviewable; production deployment still requires
organization-specific authentication, distributed infrastructure controls,
authorized data integrations and calibration on authorized labeled data.

| Phase | Status | Evidence |
| --- | --- | --- |
| 16 Attribution baseline | complete | Transparent, logistic-regression and XGBoost baselines with evidence/model metadata. |
| 17 Contradiction fusion | complete | Supporting/contradictory/unknown evidence, temporal/reliability/quality and independence discounts. |
| 18 Calibration | complete | Platt, isotonic and temperature calibration plus Brier/ECE and reliability bins. |
| 19 Temporal heterogeneous GNN | complete reference implementation | Point-in-time graph adapter, PyTorch Temporal-HGT, deterministic training and pair head. |
| 20 Adversarial persona simulator | complete reference implementation | Deterministic L1–L5 migration ladder and degradation primitives. |
| 21 Benchmark + ablation | complete reference package | Actor-disjoint cohorts, migration evaluation, benchmark runner and reproducibility metadata. |
| 22 Analyst Copilot | complete reference workflow | Intent routing, evidence isolation, prompt-injection indicators, citation validation, backend search adapter and API orchestration. |
| 23 Investigation UI | complete reference UI | Case list/workspace, evidence, actor, timeline, graph, attribution, hypotheses, sources and report screens; durable workspace/report APIs now wired. |
| 24 Reporting + STIX | complete reference exports | JSON, CSV, STIX 2.1 and PDF case-scoped exports with case/query/evidence/model/dataset provenance. |
| 25 Security hardening | complete baseline controls | Secret/dependency scan, payload limits, rate limiting, security headers, optional API-key gate and security-focused tests. DAST/container scanning remain deployment checks. |
| 26 MLOps + observability | complete baseline | Counters, latency averages, histograms, gauges, ML drift helpers, metrics endpoint and optional OpenTelemetry span helper. |
| 27 Load/failure testing | complete synthetic harness | 10K/100K/1M bounded synthetic scale profile and explicit dependency-failure matrix. Production throughput still requires environment-specific load runs. |
| 28 End-to-end rehearsal | complete synthetic rehearsal | Seeded evidence → graph → candidate generation → contradiction-aware assessment → calibrated/report exports with timing metrics. |
| 29 Research package | complete reference package | Data/model cards, reproduction instructions, research protocol, ablation template, experiment table and plotting checklist. |

## Remaining deployment work

The repository no longer depends on a missing AEGIS application layer for the
Phase 22–29 reference workflow. The remaining work is deployment-specific:

- provision and authenticate PostgreSQL/OpenSearch/Neo4j/object storage;
- install optional `report` and `telemetry` extras;
- configure API-key or organization SSO/RBAC at the gateway;
- run 100K/1M load profiles against the intended infrastructure;
- perform DAST/container scans in the target deployment;
- calibrate and validate models on authorized labeled data;
- connect only authorized collection adapters and retain source authorization metadata.

Attribution outputs remain hypotheses for analyst review; synthetic benchmark
results must not be presented as field-performance estimates.
