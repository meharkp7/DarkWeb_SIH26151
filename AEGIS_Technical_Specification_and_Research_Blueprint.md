# AEGIS --- Technical Specification & Research Blueprint

**Problem Statement:** SIH 26151 --- Dark Web Threat Actor
De-anonymization\
**System:** AEGIS --- Attribution & Evidence Graph Intelligence System\
**Status:** Research architecture + production-oriented technical
specification

## 1. Executive Summary

The problem statement asks for continuous collection of dark-web
threat-actor footprints, infrastructure correlation, cross-marketplace
identity mapping, AI-based stylometric and behavioral analysis, timeline
querying, attribution confidence, provenance, actor profiles, and
CSV/JSON/report export.

AEGIS should therefore be built as an **evidence-centric
cyber-intelligence platform**, not as a crawler plus Neo4j dashboard.

The central design principle is:

> **Observe → preserve → normalize → resolve → correlate → model →
> contradict → calibrate → explain → review → export.**

The system treats attribution as a hypothesis supported or weakened by
evidence. A handle, wallet, PGP key, stylistic similarity,
infrastructure fingerprint, or behavioral similarity is never
automatically treated as proof of real-world identity.

### Proposed research contribution

AEGIS combines five research directions into one auditable framework:

1.  **Temporal multimodal attribution:** text + behavior + graph +
    infrastructure + financial evidence.
2.  **Contradiction-aware evidence fusion:** explicitly model
    supporting, contradictory, and missing evidence.
3.  **Provenance-aware confidence:** source reliability, source lineage,
    evidence independence, temporal fit, and calibration.
4.  **Adversarial persona-migration detection:** evaluate robustness
    when aliases, style, behavior, platforms, and identifiers change.
5.  **Evidence-grounded analyst copilot:** LLMs retrieve and explain
    evidence; they do not invent or independently decide attribution.

The PS explicitly asks for actor profiles, identifiers, hidden-service
infrastructure indicators, persona linkages, attribution confidence,
source/scan metadata, timeline analysis, autonomous collection and
exports. This architecture maps those requirements to explicit services
and measurable acceptance criteria.

------------------------------------------------------------------------

# 2. Scope and Safety Boundary

The platform is intended for lawful defensive research, authorized
investigations, public intelligence, and controlled synthetic
experiments.

### In scope

-   public/authorized source collection
-   passive metadata analysis
-   evidence preservation
-   entity resolution
-   graph analysis
-   stylometry
-   behavioral profiling
-   temporal change detection
-   provenance and auditability
-   hypothesis management
-   defensive reporting

### Explicitly out of scope

-   defeating Tor cryptography
-   unauthorized exploitation
-   credential attacks
-   origin-IP attacks
-   access-control bypass
-   intrusive deanonymization
-   offensive automation

Modern Tor onion services intentionally hide service location/IP and use
cryptographic addressing. Therefore the product must describe
infrastructure findings as **correlations or indicators**, not
guaranteed origin recovery.

------------------------------------------------------------------------

# 3. Formal Problem

Let observations be:

\[ O={o_1,`\ldots`{=tex},o_n} \]

where:

\[ o_i=(x_i,t_i,s_i,c_i,p_i) \]

-   (x_i): observed value/content
-   (t_i): observation time
-   (s_i): source
-   (c_i): collection context
-   (p_i): provenance

Construct a temporal heterogeneous graph:

\[ G_t=(V,E,R,T,X,P) \]

where:

-   (V): typed entities
-   (E): relationships
-   (R): relation types
-   (T): temporal validity
-   (X): features
-   (P): provenance

For candidates (a,b), estimate:

\[ P(H\_{same}(a,b)`\mid `{=tex}E^+,E^-,T,S) \]

where (E\^+) is supporting evidence, (E\^-) is contradictory evidence,
(T) is temporal context, and (S) represents source
reliability/independence.

The output is an **attribution assessment**, not a declaration of
identity.

------------------------------------------------------------------------

# 4. Requirements Traceability

  --------------------------------------------------------------------------------
  PS requirement                 AEGIS subsystem         Acceptance target
  ------------------------------ ----------------------- -------------------------
  Continuous collection          Collector Orchestrator  scheduled/event-driven
                                                         jobs

  Marketplaces/forums/deep-web   Source adapters         versioned connectors

  Infrastructure                 Infrastructure Evidence passive feature
  misconfiguration/correlation   Engine                  extraction

  Handles/PGP/wallets            Entity Resolution       multi-signal candidates
                                 Engine                  

  Relationship graph             Temporal Knowledge      typed temporal edges
                                 Graph                   

  Stylometry                     Persona Intelligence    cross-source verification

  Behavioral profiling           Behavior Engine         temporal signatures

  Persona migration              Migration Detector      change-point + multimodal
                                                         evidence

  Attribution confidence         Evidence Fusion         calibrated score

  Source reliability             Provenance Engine       source and lineage
                                                         metadata

  Timeline                       Temporal Query Service  interval-aware queries

  GUI                            Investigation Console   graph/evidence/timeline

  Autonomous mode                Scheduler + event bus   continuous processing

  CSV/JSON/reports               Reporting Engine        reproducible exports
  --------------------------------------------------------------------------------

------------------------------------------------------------------------

# 5. High-Level Architecture

``` text
                     Analyst / API Client
                              |
                      API Gateway + Auth
                              |
       +----------------------+----------------------+
       |                      |                      |
 Investigation UI       Query/RAG Service       Case Service
       |                      |                      |
       +----------------------+----------------------+
                              |
                    Intelligence Services
                              |
      +-----------+-----------+-----------+-----------+
      |           |           |           |           |
 Resolution   Stylometry  Behavior   Infrastructure  Migration
      |           |           |           |           |
      +-----------+-----------+-----------+-----------+
                              |
                 Evidence Fusion / Attribution
                              |
                  Temporal Evidence Graph
                              |
       +----------------------+----------------------+
       |                      |                      |
 PostgreSQL                 Neo4j               OpenSearch
 system state             relationships           retrieval
       |                      |                      |
       +----------------------+----------------------+
                              |
                         Object Storage
                              |
                      Evidence Event Bus
                              |
          +-------------------+-------------------+
          |                   |                   |
      Collectors         Normalization       Extraction
          |                   |                   |
          +-------------------+-------------------+
                              |
                       Evidence Ledger
```

------------------------------------------------------------------------

# 6. Architectural Principles

1.  **Evidence-first:** raw observations remain available; normalized
    facts never replace them.
2.  **Append-only intelligence:** new observations create new versions
    rather than silently rewriting history.
3.  **Temporal by default:** relationships carry first/last seen and
    validity where available.
4.  **Provenance by default:** every derived fact references source
    evidence.
5.  **Models produce hypotheses:** model outputs are reviewable
    assessments.
6.  **Correlation ≠ identity:** UI wording must distinguish association,
    similarity, and confirmed analyst findings.
7.  **Independent evidence matters:** copied sources must not count as
    independent confirmations.
8.  **Reproducibility:** evidence IDs, model versions, feature versions,
    thresholds and queries are recorded.
9.  **Human-in-the-loop:** final case disposition remains an analyst
    action.
10. **Untrusted content:** collected pages/documents/messages can
    contain prompt injection and must never be interpreted as system
    instructions.

------------------------------------------------------------------------

# 7. Canonical Domain Model

## 7.1 Entity types

### Identity

-   ActorHypothesis
-   Handle
-   Alias
-   PGPKey
-   EmailIdentifier
-   ContactIdentifier

### Infrastructure

-   OnionService
-   Domain
-   IPObservation
-   Certificate
-   HostingEntity
-   TechnologyFingerprint
-   ServiceFingerprint

### Financial

-   WalletAddress
-   Transaction
-   AddressCluster
-   PaymentIdentifier

### Content

-   Post
-   Listing
-   Message
-   Document
-   Image
-   CodeArtifact

### Platform

-   Marketplace
-   Forum
-   Channel
-   Source
-   CollectionJob

### Analytical

-   BehavioralProfile
-   StylometricProfile
-   EvidenceItem
-   Hypothesis
-   AttributionAssessment
-   TimelineEvent
-   ChangePoint
-   MigrationAssessment

## 7.2 Relationship types

``` text
OBSERVED_AT
USES_HANDLE
USES_PGP
ASSOCIATED_WITH_WALLET
POSTED_ON
MENTIONS
REPLIES_TO
SIMILAR_TO
MIGRATED_TO
USES_INFRASTRUCTURE
CERTIFICATE_ASSOCIATED_WITH
INFRASTRUCTURE_SIMILAR_TO
CO_OCCURS_WITH
SUPPORTS
CONTRADICTS
DERIVED_FROM
OBSERVED_BY
VALID_DURING
```

------------------------------------------------------------------------

# 8. Evidence Model

Canonical evidence object:

``` json
{
  "evidence_id": "OBS-000001",
  "case_id": "CASE-2026-0001",
  "source_id": "SRC-0001",
  "source_type": "forum",
  "collected_at": "2026-09-28T00:00:00Z",
  "observed_at": "2026-09-27T20:13:00Z",
  "entity_type": "handle",
  "entity_value_hash": "...",
  "context_hash": "...",
  "raw_artifact_uri": "s3://evidence/...",
  "sha256": "...",
  "collector_version": "0.3.0",
  "normalizer_version": "0.2.1",
  "extraction_version": "0.4.0",
  "source_reliability": 0.82,
  "independence_group": "SRCROOT-17"
}
```

Required fields:

-   immutable evidence ID
-   source
-   observation time
-   collection time
-   raw artifact reference
-   hash
-   collector/version
-   provenance
-   reliability metadata
-   source-lineage group

------------------------------------------------------------------------

# 9. Evidence Integrity

## 9.1 Hashing

Every artifact receives SHA-256.

## 9.2 Merkle batching

``` text
OBS1 ─┐
OBS2 ─┼─> Merkle tree ─> root
OBS3 ─┤
OBS4 ─┘
```

A root may be anchored to an authorized tamper-evident ledger. Sensitive
raw evidence must not be placed on a public blockchain.

## 9.3 Chain of custody

``` text
Collected
  -> Stored
  -> Parsed
  -> Enriched
  -> Linked
  -> Assessed
  -> Exported
```

Every transition is audited.

------------------------------------------------------------------------

# 10. Storage Architecture

### PostgreSQL

System of record for cases, evidence metadata, users, permissions, model
runs, jobs and audit logs.

### Neo4j

Typed relationship graph and investigation traversal.

### OpenSearch

Full-text, metadata and hybrid retrieval.

### Object storage

Raw and normalized artifacts, reports and evidence packages.

### Redis

Caching, rate limiting and transient job state.

### Kafka/Redpanda

Event backbone between collectors and intelligence services.

This polyglot architecture prevents the common mistake of forcing graph,
document, transactional and object workloads into one database.

------------------------------------------------------------------------

# 11. Collection Layer

Every collector implements:

``` python
class Collector(Protocol):
    name: str
    version: str

    async def discover(self, scope) -> list[Candidate]: ...

    async def collect(self, candidate) -> RawArtifact: ...

    async def normalize(self, artifact) -> ObservationBatch: ...
```

Start with synthetic and authorized collectors before any external
collection.

Collector classes:

-   marketplace adapter
-   forum adapter
-   public web adapter
-   threat-feed adapter
-   analyst-submitted artifact adapter
-   synthetic benchmark adapter

Collection jobs:

``` text
DISCOVER
COLLECT
DIFF
REPROCESS
REASSESS
REVALIDATE
```

------------------------------------------------------------------------

# 12. Normalization and Deduplication

Pipeline:

``` text
raw artifact
 -> canonical encoding
 -> metadata normalization
 -> exact hash
 -> near-duplicate detection
 -> source lineage
 -> observation
```

Use:

-   SHA-256
-   normalized-content hash
-   SimHash/MinHash
-   duplicate cluster
-   source ancestry

The independence model is critical: ten copied pages should not create
ten independent confirmations.

------------------------------------------------------------------------

# 13. Entity Extraction

Hybrid pipeline:

``` text
Rules/regex
     +
Domain NER
     +
Transformer NER
     +
Ontology validation
```

Each extracted entity stores:

``` text
entity_id
entity_type
surface_form
normalized_form
confidence
evidence_id
span
```

Evidence spans are retained so an analyst can inspect exactly why an
entity was extracted.

------------------------------------------------------------------------

# 14. Entity Resolution

Candidate generation should use blocking to avoid (O(n\^2)) comparisons.

Blocking signals:

-   normalized handle
-   edit distance
-   character n-grams
-   public identifier
-   PGP fingerprint
-   wallet co-occurrence
-   temporal overlap
-   marketplace transition
-   embedding retrieval

Pair feature vector:

\[ x\_{ab}=\[ S_h,S_p,S_w,S_s,S_b,S_i,S_t,S_g,S_r\] \]

where:

-   (S_h): handle similarity
-   (S_p): PGP
-   (S_w): wallet
-   (S_s): stylometry
-   (S_b): behavior
-   (S_i): infrastructure
-   (S_t): temporal consistency
-   (S_g): graph similarity
-   (S_r): source/provenance

Baselines:

1.  rules
2.  TF-IDF/cosine
3.  logistic regression
4.  XGBoost

Advanced model:

5.  temporal heterogeneous GNN

------------------------------------------------------------------------

# 15. Stylometry

## Classical features

-   character n-grams
-   word n-grams
-   function words
-   sentence length
-   word length
-   punctuation
-   capitalization
-   spelling/typing patterns
-   vocabulary richness
-   POS distributions
-   lexical diversity

## Neural representation

Use a domain-appropriate transformer encoder, but do not make semantic
embeddings the only signal.

## Cross-domain evaluation

Test:

-   same marketplace
-   different marketplace
-   topic shift
-   short text
-   long text
-   time-separated text

## Robustness

Transform samples by:

``` text
punctuation removal
case normalization
slang normalization
paraphrase
translation
shortening
noise
```

Define representation stability:

\[ Stability = 1-`\mathbb{E}`{=tex}\_{T}\[d(f(x),f(T(x)))\] \]

This creates a measurable adversarial-stylometry research axis.

------------------------------------------------------------------------

# 16. Behavioral Fingerprinting

For a time window (W_t):

\[ B_t=\[ activity_hour, posting_rate, response_latency,
topic_distribution, marketplace_distribution, language_distribution,
interaction_degree\] \]

Features:

-   activity histograms
-   inter-arrival distribution
-   burstiness
-   posting cadence
-   response delay
-   category preference
-   platform transitions
-   neighborhood structure

Start with statistical features before sequence transformers.

------------------------------------------------------------------------

# 17. Infrastructure Evidence Engine

The PS calls for server-status exposure, certificates, default banners,
descriptor inconsistencies and clearnet correlation.

Implement a passive evidence engine containing:

``` text
TLS metadata
HTTP metadata
content fingerprints
technology fingerprints
certificate relationships
historical fingerprints
```

Output:

``` text
infrastructure similarity
evidence IDs
time window
source reliability
limitations
```

Important: a correlation must not be displayed as "origin identified"
unless independently established through authorized evidence.

------------------------------------------------------------------------

# 18. Financial Intelligence

Represent:

``` text
Wallet
 -> Transaction
 -> Counterparty
 -> AddressCluster
 -> Public reference
```

Features:

-   first/last seen
-   transaction frequency
-   degree
-   temporal bursts
-   counterparty overlap
-   cluster membership
-   public co-occurrence

Financial evidence remains one modality; wallet association alone is
insufficient for identity attribution.

------------------------------------------------------------------------

# 19. Temporal Knowledge Graph

Relationship:

\[ e=(u,r,v,t\_{start},t\_{end},confidence,provenance) \]

Example:

``` json
{
  "subject": "HANDLE-123",
  "relation": "USES_PGP",
  "object": "PGP-456",
  "valid_from": "2026-03-01",
  "valid_until": "2026-06-30",
  "first_seen": "2026-03-01",
  "last_seen": "2026-06-29",
  "confidence": 0.98,
  "evidence": ["OBS-21", "OBS-88"]
}
```

Queries must support historical state, not only current state.

------------------------------------------------------------------------

# 20. Persona Migration

Migration hypothesis:

``` text
old identity
 -> change point/activity discontinuity
 -> new identity
 -> cross-modal similarity
 -> candidate migration
```

Signals:

-   alias transition
-   stylometric similarity
-   behavioral continuity
-   PGP continuity
-   wallet relationship
-   infrastructure continuity
-   graph-neighborhood similarity
-   temporal consistency

Output:

``` text
old_entity
new_entity
change_window
supporting_evidence
contradictory_evidence
confidence
```

------------------------------------------------------------------------

# 21. Contradiction-Aware Evidence Fusion

For candidate linkage (H), separate:

-   supporting evidence (E\^+)
-   contradictory evidence (E\^-)
-   missing/unknown evidence (E\^?)

Evidence weight:

\[ w_i=r_i q_i f_i d_i \]

where:

-   (r_i): source reliability
-   (q_i): evidence quality
-   (f_i): temporal/freshness fit
-   (d_i): independence discount

Transparent baseline:

\[
S=`\sigma`{=tex}(`\alpha`{=tex}`\sum`{=tex}*{E\^+}w_i-`\beta`{=tex}`\sum`{=tex}*{E\^-}w_j)
\]

The final production model can be learned and calibrated, but this
interpretable baseline is required for scientific comparison.

------------------------------------------------------------------------

# 22. Evidence Independence

Build a source-lineage graph:

``` text
source A
   |
copied to B
   |
copied to C
```

A/B/C should not be treated as three independent confirmations.

Store:

``` text
source_lineage
duplicate_cluster
independence_group
collection_family
```

Evaluate the system explicitly under:

1.  independent corroboration
2.  duplicated corroboration
3.  conflicting corroboration

------------------------------------------------------------------------

# 23. Attribution Model Stack

Required model progression:

``` text
Rule baseline
     ↓
Logistic/XGBoost
     ↓
Text encoder
     ↓
Graph encoder
     ↓
HGT
     ↓
Temporal HGT
     ↓
Temporal HGT + contradiction
     ↓
Calibrated final fusion
```

Never introduce the final neural model without retaining interpretable
baselines.

------------------------------------------------------------------------

# 24. Temporal Heterogeneous Graph Model

Graph:

\[ G_t=(V,E,R,T) \]

Pipeline:

``` text
typed node features
      ↓
relation-aware message passing
      ↓
temporal encoding
      ↓
cross-modal attention
      ↓
candidate-pair representation
      ↓
attribution decoder
```

Compare:

-   XGBoost
-   R-GCN
-   HGT
-   temporal HGT
-   temporal HGT + contradiction

Use actor-disjoint and temporal splits to prevent leakage.

------------------------------------------------------------------------

# 25. Confidence Calibration

Separate raw score from calibrated confidence.

Methods:

-   Platt scaling
-   isotonic regression
-   temperature scaling

Evaluate:

-   Brier score
-   ECE
-   reliability diagrams
-   calibration by modality
-   calibration by evidence count

The UI must never present an uncalibrated model score as if it were a
probability.

------------------------------------------------------------------------

# 26. Adversarial Persona Simulator

Create controlled synthetic actors.

Levels:

-   L1 alias change
-   L2 alias + vocabulary shift
-   L3 alias + behavior shift
-   L4 migration + behavior + marketplace change
-   L5 multimodal adversarial migration

Measure:

-   precision
-   recall
-   F1
-   false association rate
-   detection latency
-   degradation vs attack severity

This benchmark is a central research contribution because it gives a
controlled way to test whether attribution survives intentional persona
changes.

------------------------------------------------------------------------

# 27. Hypothesis Management

A case should support multiple hypotheses:

``` text
H1: same actor
H2: collaborator
H3: impersonation
H4: unrelated
```

Each hypothesis stores:

-   supporting evidence
-   contradictory evidence
-   missing evidence
-   model assessments
-   analyst disposition
-   timestamps

This reduces premature closure.

------------------------------------------------------------------------

# 28. Analyst Copilot

LLM responsibilities:

-   natural-language query planning
-   evidence summarization
-   timeline narration
-   report drafting
-   hypothesis comparison

LLM must not:

-   invent evidence
-   treat similarity as proof
-   override provenance
-   silently add unsupported relationships

Architecture:

``` text
question
 -> intent parser
 -> graph query + search
 -> evidence pack
 -> provenance filter
 -> LLM synthesis
 -> citation validator
 -> answer
```

Collected content is untrusted data and must be isolated from system
instructions.

------------------------------------------------------------------------

# 29. STIX Interoperability

Implement a STIX 2.1 export adapter.

Possible mappings:

``` text
ActorHypothesis -> Threat Actor / Identity
Infrastructure -> Infrastructure
Observation -> Observed Data
Indicator -> Indicator
Relationship -> Relationship
Observation occurrence -> Sighting
```

Keep the internal AEGIS model richer than the interoperability schema
where required.

------------------------------------------------------------------------

# 30. API Contract

``` text
POST /api/v1/cases
GET  /api/v1/cases/{id}

POST /api/v1/evidence
GET  /api/v1/evidence/{id}
GET  /api/v1/evidence/{id}/provenance

GET /api/v1/actors/{id}
GET /api/v1/actors/{id}/timeline
GET /api/v1/actors/{id}/graph

POST /api/v1/attribution/candidates
GET /api/v1/attribution/{id}

POST /api/v1/search
POST /api/v1/query/natural-language

POST /api/v1/reports
GET /api/v1/reports/{id}
```

All endpoints require authentication and case-scoped authorization where
applicable.

------------------------------------------------------------------------

# 31. Frontend Information Architecture

Main navigation:

``` text
Overview
Investigations
Actors
Evidence
Graph
Timeline
Alerts
Sources
Models
Reports
Administration
```

Actor page:

``` text
identity summary
aliases
identifiers
assessment
evidence matrix
timeline
relationship graph
stylometry
behavior
infrastructure
financial indicators
contradictions
model explanation
audit history
```

The graph must be filterable by:

-   entity type
-   relationship type
-   time window
-   evidence threshold
-   source class

------------------------------------------------------------------------

# 32. Security Architecture

Implement:

-   MFA
-   RBAC
-   case-scoped permissions
-   TLS
-   encryption at rest
-   secret management
-   strict outbound policy
-   SSRF protection
-   query validation
-   rate limiting
-   immutable audit logging
-   export logging

Threat model:

1.  evidence poisoning
2.  copied-source confidence inflation
3.  prompt injection
4.  model poisoning
5.  unauthorized evidence access
6.  analyst credential compromise
7.  data exfiltration
8.  malicious collector
9.  compromised infrastructure

------------------------------------------------------------------------

# 33. MLOps

Every model run records:

``` text
model_id
model_version
dataset_version
feature_version
git_commit
hyperparameters
metrics
calibration
timestamp
```

Pipeline:

``` text
data validation
 -> feature generation
 -> train
 -> evaluate
 -> calibrate
 -> register
 -> shadow
 -> canary
 -> production
```

------------------------------------------------------------------------

# 34. Dataset Strategy

Use three tiers.

### Tier A --- Public research datasets

Use appropriate public dark-web authorship/CTI benchmarks where
licensing permits. VeriDark is a useful reference for dark-web
authorship verification/identification.

### Tier B --- Synthetic controlled environment

Generate actors, personas, platforms and ground-truth relationships.

### Tier C --- Authorized/public observations

Use only data that the project is legally permitted to collect.

------------------------------------------------------------------------

# 35. Ground-Truth Generator

Generate:

``` text
N actors
M personas/actor
K platforms
T time windows
```

Control:

-   alias reuse
-   writing similarity
-   behavioral similarity
-   wallet association
-   infrastructure association
-   migration timing
-   noise
-   contradictions

Keep ground truth outside model inputs.

------------------------------------------------------------------------

# 36. Evaluation

## Entity resolution

-   precision
-   recall
-   F1
-   B-cubed F1
-   cluster purity
-   MRR
-   Recall@K

## Attribution

-   PR-AUC
-   ROC-AUC
-   Brier score
-   ECE
-   false association rate

## Stylometry

-   cross-marketplace verification
-   time-shift robustness
-   short-text robustness
-   transformation robustness

## Migration

-   detection precision
-   recall
-   latency
-   severity/performance curve

## Retrieval

-   Recall@K
-   MRR
-   nDCG

## System

-   ingestion throughput
-   p95 query latency
-   graph traversal latency
-   inference latency
-   storage growth
-   recovery time

------------------------------------------------------------------------

# 37. Leakage-Controlled Splits

Required:

1.  actor-disjoint split
2.  temporal split
3.  platform-disjoint split where feasible
4.  migration split

Never allow duplicated/copy-pasted content across train/test.

------------------------------------------------------------------------

# 38. Ablation Matrix

Run:

``` text
A1 text only
A2 behavior only
A3 graph only
A4 text + behavior
A5 text + graph
A6 text + behavior + graph
A7 all modalities
A8 all + contradiction
A9 all + temporal
A10 all + temporal + contradiction + provenance
```

This is required to demonstrate which innovations actually contribute.

------------------------------------------------------------------------

# 39. Research Questions

**RQ1:** Does multimodal evidence improve cross-platform entity
resolution over text-only matching?

**RQ2:** Does temporal modeling reduce false associations caused by
coincidental similarity?

**RQ3:** Does contradiction-aware fusion improve confidence calibration?

**RQ4:** How robust is attribution under adversarial persona migration?

**RQ5:** Does provenance/independence weighting reduce confidence
inflation?

**RQ6:** Can graph-based candidate generation reduce pairwise search
cost without reducing recall?

**RQ7:** Can evidence-grounded LLM reporting reduce unsupported
analytical claims?

------------------------------------------------------------------------

# 40. Research Hypotheses

-   **H1:** multimodal attribution improves cross-platform verification.
-   **H2:** temporal constraints reduce false-positive associations.
-   **H3:** contradiction-aware fusion improves calibration.
-   **H4:** source-independence weighting reduces overconfidence from
    duplicated evidence.
-   **H5:** adversarial simulation exposes measurable failure modes and
    enables robustness improvements.

------------------------------------------------------------------------

# 41. Novelty Matrix

  -----------------------------------------------------------------------
  Existing direction      Baseline capability     AEGIS research
                                                  extension
  ----------------------- ----------------------- -----------------------
  Dark-web stylometry     authorship similarity   multimodal + temporal +
                                                  adversarial robustness

  CTI knowledge graphs    entity/relationship     evidence-native
                          graph                   attribution graph

  GNN CTI attribution     relational learning     temporal heterogeneous
                                                  actor graph

  Provenance-aware RAG    source-aware retrieval  provenance-native
                                                  investigation workflow

  OSINT platforms         collection              continuous evidence
                                                  lifecycle

  Blockchain analysis     transaction correlation financial evidence as
                                                  one modality

  Rule systems            transparent association calibrated
                                                  contradiction-aware
                                                  fusion
  -----------------------------------------------------------------------

The novelty claim should be conservative: **the contribution is the
integration and evaluation of temporal multimodal, contradiction-aware,
provenance-native actor association under adversarial persona
migration**, not the invention of every individual component.

------------------------------------------------------------------------

# 42. Production Readiness Criteria

Do not call the system production-grade until:

-   evidence is versioned and hash-addressed
-   graph edges have provenance
-   copied evidence is discounted
-   confidence is calibrated
-   models are versioned
-   analyst actions are audited
-   LLM outputs are evidence-grounded
-   exports are reproducible
-   collectors are isolated/rate-limited
-   security controls are tested
-   observability exists
-   failures degrade safely

------------------------------------------------------------------------

# 43. Recommended Repository

``` text
aegis/
├── apps/
│   ├── api/
│   ├── worker/
│   ├── scheduler/
│   └── frontend/
├── services/
│   ├── collection/
│   ├── normalization/
│   ├── extraction/
│   ├── resolution/
│   ├── stylometry/
│   ├── behavior/
│   ├── infrastructure/
│   ├── attribution/
│   ├── migration/
│   ├── provenance/
│   ├── reporting/
│   └── copilot/
├── ml/
│   ├── datasets/
│   ├── features/
│   ├── baselines/
│   ├── graph/
│   ├── temporal/
│   ├── fusion/
│   ├── calibration/
│   └── evaluation/
├── packages/
│   ├── schemas/
│   ├── ontology/
│   ├── graph/
│   ├── evidence/
│   └── common/
├── infra/
│   ├── docker/
│   ├── postgres/
│   ├── neo4j/
│   ├── opensearch/
│   └── observability/
├── benchmarks/
├── tests/
├── docs/
└── scripts/
```

------------------------------------------------------------------------

# 44. Final System Definition

The system is best defined as:

> **A provenance-aware temporal multimodal intelligence platform for
> discovering, evaluating and explaining potential relationships among
> evolving threat personas.**

The evidence graph is the center of the architecture. The AI models
enrich and rank hypotheses. The analyst remains the final reviewer.

------------------------------------------------------------------------

# 45. Research/Standards Baseline

Use these as the initial literature/standards anchors:

-   OASIS STIX 2.1
-   Tor Project onion-service specifications
-   VeriDark dark-web authorship benchmark
-   recent CTI heterogeneous knowledge-graph research
-   provenance-aware CTI/RAG research
-   recent GNN-based threat attribution research

The literature review must explicitly identify overlap and avoid
claiming that ordinary knowledge graphs, stylometry, GNNs, or RAG are
individually novel.
