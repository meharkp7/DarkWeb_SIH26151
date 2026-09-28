# AEGIS Research Package

## Problem
AEGIS studies evidence-centric attribution of synthetic threat-actor identities across heterogeneous temporal signals while preserving provenance and contradiction visibility.

## Threat model
External artifacts are untrusted inputs. The system does not defeat Tor cryptography, exploit hosts, bypass access controls, attack credentials, or guarantee origin recovery. Attribution outputs are hypotheses for analyst review.

## Method
1. Canonical evidence ledger with immutable provenance.
2. Normalization, entity extraction and temporal graph construction.
3. Entity-resolution baselines and multimodal signals: stylometry, behavior, infrastructure and financial indicators.
4. Contradiction-aware fusion and calibration.
5. Temporal heterogeneous graph learning and adversarial persona migration evaluation.
6. Evidence-grounded analyst Copilot with citation validation and report provenance.

## Experimental protocol
Use actor-disjoint, temporal, platform-disjoint and migration-disjoint cohorts. Report precision, recall, F1, calibration error, Brier score, latency and degradation under L1–L5 migration scenarios. Never mix synthetic benchmark results with claims about live-world performance.

## Ablations
Run with each major modality removed in turn, then compare the full fusion model against Phase 16 transparent and XGBoost baselines. Persist seed, dataset version, feature version, model version and git commit for every run.

## Limitations
Synthetic distributions do not establish field validity. External-source collection, production authentication, distributed rate limiting and operational alerting require deployment-specific controls and authorized data.
