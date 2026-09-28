# AEGIS Architecture

**Status:** Reviewed (Phase 00 exit criterion)
**Governing ADRs:** `docs/adr/ADR-001` … `ADR-005`.

## 1. Design principle

```
Evidence → Provenance → Graph → Baselines → Multimodal features
        → Temporal modeling → Contradiction fusion → GNN
        → Adversarial benchmark → LLM → UI → Production hardening
```

Never: `LLM → guess → graph → dashboard`.

The system is a provenance-aware, temporal, multimodal intelligence
platform for discovering, evaluating, and explaining *potential*
relationships among evolving threat personas. Models produce
hypotheses; analysts make findings.

## 2. Logical architecture

```
                    Analyst / API Client
                             │
                     API Gateway + Auth (RBAC, rate limit, audit)
                             │
      ┌──────────────────────┼──────────────────────┐
      │                      │                      │
 Investigation UI      Query/RAG Service        Case Service
      │                      │                      │
      └──────────────────────┼──────────────────────┘
                             │
                   Intelligence Services
                             │
  ┌──────────┬───────────┬───┴───────┬──────────────┐
  │ Resolution│ Stylometry│ Behavior  │Infrastructure│ Migration
  └──────────┴───────────┴───────────┴──────────────┘
                             │
                Evidence Fusion / Attribution
                             │
                 Temporal Evidence Graph
                             │
      ┌──────────────────────┼──────────────────────┐
      │                      │                      │
  PostgreSQL               Neo4j                OpenSearch
  (system of record)   (relationships)         (retrieval)
      │                      │                      │
      └──────────────────────┼──────────────────────┘
                             │
                        Object Storage
                             │
                      Evidence Event Bus
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
    Collectors          Normalization         Extraction
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                       Evidence Ledger
```

## 3. Repository layout

The implementation lives under `src/aegis` (src-layout) and maps to the
blueprint's service decomposition:

| Blueprint area | Package | Responsibility |
|----------------|---------|----------------|
| Evidence ledger | `aegis.evidence` | Hashing, artifact store, evidence service, integrity |
| Schemas | `aegis.schemas` | Canonical Pydantic contracts (no service invents its own) |
| Ontology | `aegis.ontology` | Entity/relationship type registry and validation |
| Collection | `aegis.collection` | Collector protocol, orchestration, synthetic collectors |
| Normalization | `aegis.normalization` | Canonical encoding, hashes, near-dup, lineage |
| Extraction | `aegis.extraction` | Deterministic + NER entity extraction with spans |
| Temporal graph | `aegis.graph` | Temporal heterogeneous graph + required queries |
| Resolution | `aegis.resolution` | Blocking, pair features, baseline scorers |
| Retrieval | `aegis.search` | Index definitions + hybrid retrieval |
| Stylometry | `aegis.stylometry` | n-grams, classical features, verification, robustness |
| Behavior | `aegis.behavior` | Temporal/behavioral profile features |
| Infrastructure | `aegis.infrastructure` | Passive fingerprint correlation |
| Financial | `aegis.financial` | Wallet/transaction/cluster evidence |
| Temporal analysis | `aegis.timeline` | Timeline events, change points, migration candidates |
| Attribution | `aegis.attribution` | Baseline scoring, contradiction fusion, calibration |
| GNN | `aegis.ml.graph` | R-GCN / HGT / temporal encoders |
| Persona sim | `aegis.adversarial` | L1–L5 persona migration simulator |
| Copilot | `aegis.copilot` | Tool planning, evidence pack, citation validation |
| Reporting | `aegis.reporting` | Report assembly, CSV/JSON/PDF/STIX exports |
| API | `aegis.api` | HTTP surface, auth, rate limiting, audit |
| Evaluation | `aegis.evaluation` | Metrics, scenarios, benchmark runner, ablations |

## 4. Data flow (one observation)

1. **Collector** `discover()` → candidate; `collect()` → raw bytes.
2. **Artifact store** content-addresses raw bytes (SHA-256), stores
   under `evidence/{year}/{month}/{case}/{evidence_id}/`.
3. **Evidence service** appends an immutable ledger row with provenance
   and audit event (same transaction).
4. **Normalization** computes canonical encoding, normalized hash,
   SimHash/MinHash, duplicate cluster, source lineage → observation.
5. **Extraction** emits typed entities with spans referencing the
   evidence ID.
6. **Graph writer** upserts nodes and temporally-bounded edges carrying
   `first_seen`, `last_seen`, `confidence`, `evidence_ids`.
7. **Resolution** generates candidates by blocking, scores pair
   features with frozen baselines.
8. **Multimodal services** (stylometry/behavior/infrastructure/
   financial) contribute per-pair scores.
9. **Fusion** computes `S = σ(α·S⁺ − β·S⁻)` with
   `w_i = r_i·q_i·f_i·d_i`.
10. **Calibration** maps `raw_score → calibrated_confidence` with a
    versioned calibrator.
11. **Assessment** persisted with evidence IDs, model versions, and
    explanations; contradictions listed explicitly.
12. **Analyst** reviews, dispositions the hypothesis; **report**
    exports with full provenance.

## 5. Storage responsibilities

| Store | Owns | Never owns |
|-------|------|-----------|
| PostgreSQL | cases, evidence metadata, entities, assessments, users, jobs, audit, model runs | raw blobs, full-text search |
| Neo4j (graph) | typed temporal relationships, traversal | evidence blobs, authoritative metadata |
| OpenSearch | retrieval indexes | system of record |
| Object storage | raw/normalized artifacts, exports | metadata authority |
| Redis | cache, rate limits, transient job state | durable state |
| Event bus | pipeline hand-offs | source of truth |

All access goes through interfaces (`aegis.storage`, `aegis.search`,
`aegis.graph`) with production adapters and in-process adapters used in
tests, so the system runs in a single process for CI and in polyglot
mode for deployment (`ADR-002`).

## 6. Cross-cutting concerns

- **Versioning:** collector / normalizer / extractor / model /
  calibration / dataset versions are recorded on every derived record.
- **Audit:** append-only, hash-chained, written in the same
  transaction as the mutation.
- **Observability:** OpenTelemetry traces across
  `API → retrieval → graph → model → report`; Prometheus-format
  metrics for app, pipeline, and ML telemetry.
- **Security:** see `docs/threat-model.md`.
- **Degradation:** each external store sits behind a client with
  timeouts, retries with jitter, and circuit breaking; failure yields
  explicit degraded responses, never silent evidence loss.

## 7. Deployment topologies

1. **CI / laptop:** single process, local artifact store, in-memory
   graph/search adapters, SQLite-free (Postgres only when available;
   integration tests skip otherwise).
2. **Compose:** Postgres + Neo4j + OpenSearch + Redis + Redpanda +
   object store, `apps/api`, `apps/worker`, `apps/scheduler`.
3. **Production:** same services horizontally scaled; collectors run
   in isolated sandboxes with egress allow-lists.
