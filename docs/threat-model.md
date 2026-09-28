# AEGIS Threat Model

**Status:** Approved (Phase 00 exit criterion)
**Methodology:** STRIDE + asset-driven analysis, per
`AEGIS_Technical_Specification_and_Research_Blueprint.md` §32.

## 1. Assets

| Asset | Sensitivity | Impact of compromise |
|-------|-------------|----------------------|
| Raw evidence artifacts | High | Case exposure, source exposure, poisoning |
| Evidence metadata / ledger | High | Attribution integrity loss |
| Analyst credentials & sessions | High | Unauthorized evidence access, audit bypass |
| Audit log | Critical | Loss of non-repudiation |
| Model artifacts & calibration | High | Silent confidence manipulation |
| Ground-truth datasets | High | Benchmark leakage, invalid research claims |
| Export bundles | High | Data exfiltration beyond case scope |

## 2. Trust boundaries

```
[Untrusted collected content] --(1)-- [Normalization/Extraction]
[External API client]         --(2)-- [API Gateway + Auth]
[LLM provider]                --(3)-- [Copilot synthesis]
[Collector sandbox]           --(4)-- [Ingestion pipeline]
[Shared analyst workspace]    --(5)-- [Case-scoped authorization]
```

## 3. Threats and controls

### T1 — Evidence poisoning
*STRIDE: Tampering.* An adversary feeds fabricated observations into a
collector to steer attribution.
**Controls:** provenance on every record; reliability priors per
source; analyst review before any hypothesis is dispositioned;
`ModelRun` outputs are hypotheses, never facts; anomaly checks on
per-source ingestion rate.

### T2 — Copied-source confidence inflation
*STRIDE: Tampering / Repudiation.* Ten copies of one report masquerade
as ten independent confirmations.
**Controls:** `independence_group`, duplicate clusters (SimHash/MinHash),
independence discount `d_i` in fusion weight `w_i = r_i q_i f_i d_i`.
Enforced by test: `tests/test_fusion_independence.py`.

### T3 — Prompt injection through collected content
*STRIDE: Elevation of Privilege.* Collected text contains instructions
("ignore previous instructions…") aimed at the copilot or any LLM step.
**Controls:** collected content is fenced as data, never system
instructions; citation validator rejects any answer containing claims
not present in the retrieved evidence pack; injection canaries in the
benchmark corpus; see `services/copilot/`.

### T4 — Model poisoning / score manipulation
*STRIDE: Tampering.* Drift or adversarial data shifts raw scores.
**Controls:** versioned models (`ModelRuns`), calibration versioning,
drift monitoring (score/feature/calibration), shadow→canary→production
promotion, retain interpretable baselines for comparison.

### T5 — Unauthorized evidence access
*STRIDE: Information Disclosure.* Analyst reads another case's evidence.
**Controls:** RBAC + case-scoped permissions enforced in the service
layer (not just the route layer); exports filtered by the same
authorization context; see `tests/test_security_authorization.py`.

### T6 — Analyst credential compromise
*STRIDE: Elevation of Privilege.* Stolen session/API token.
**Controls:** MFA (TOTP), short-lived sessions, per-token scopes,
immutable audit logging of every privileged action, rate limiting.

### T7 — Data exfiltration
*STRIDE: Information Disclosure.* Bulk export or SSRF-based fetch.
**Controls:** strict outbound allow-list for collectors (SSRF guard),
export logging with row counts, per-user export quotas.

### T8 — Malicious or buggy collector
*STRIDE: Tampering / Elevation of Privilege.* A collector returns
oversized payloads or crafted object names.
**Controls:** collector sandboxing, payload size limits, object-name
sanitization (no `..`, no absolute paths, no control characters),
schema validation at ingestion, timeouts with retry classification.

### T9 — Compromised infrastructure
*STRIDE: Repudiation.* Store or DB tampering.
**Controls:** SHA-256 of every artifact, verification on read,
Merkle batching for tamper evidence, encryption at rest, immutable
audit trail, backup/restore drills.

### T10 — Query injection
*STRIDE: Elevation of Privilege.* Cypher/SQL/OSQuery injection through
the API or copilot tools.
**Controls:** parameterized SQL (SQLAlchemy), allow-listed Cypher
templates with bound parameters, validated structured query DSL for
the copilot (no free-form query strings from the LLM).

### T11 — Audit bypass
*STRIDE: Repudiation.* Actions performed without audit records.
**Controls:** audit writes are part of the same transaction as the
action; audit table is append-only with hash chaining; tests assert
audit creation on every mutating endpoint.

## 4. Out of scope

- Defeating Tor cryptography
- Origin-IP discovery / intrusive deanonymization
- Offensive automation, credential attacks, access-control bypass
- Denial-of-service against third parties

Infrastructure findings are reported as **correlations/indicators**,
never as guaranteed origin recovery (see `ADR-003`).

## 5. Residual risk

| Risk | Severity | Mitigation path |
|------|----------|-----------------|
| Ground-truth leakage between train/test | High | Leakage-controlled splits (`ml/datasets`) |
| Reliability priors are subjective | Medium | Documented provenance + analyst override + audit |
| LLM hallucination in copilot | Medium | Evidence-pack-only synthesis + citation validator |
| Single-node deployment assumptions | Medium | Polyglot stores behind interfaces (`ADR-002`) |
