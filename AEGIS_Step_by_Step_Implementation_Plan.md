# AEGIS --- Step-by-Step Implementation Plan

**System:** AEGIS --- Attribution & Evidence Graph Intelligence System\
**Problem Statement:** SIH 26151\
**Execution rule:** Build the evidence and evaluation foundation before
advanced AI or UI.

------------------------------------------------------------------------

# 0. Build Order

``` text
00 scope/safety
01 repository/CI
02 schemas/ontology
03 PostgreSQL/evidence
04 object storage
05 collectors
06 normalization/deduplication
07 entity extraction
08 temporal Neo4j graph
09 entity-resolution baselines
10 OpenSearch/retrieval
11 stylometry
12 behavior
13 infrastructure evidence
14 financial graph
15 timeline/change detection
16 attribution baseline
17 contradiction fusion
18 calibration
19 temporal heterogeneous GNN
20 adversarial persona simulator
21 benchmark/ablation
22 analyst copilot
23 investigation UI
24 reporting/STIX
25 security hardening
26 MLOps/observability
27 load/failure tests
28 end-to-end rehearsal
29 research package
```

Do not reverse this order just to produce a faster-looking demo.

------------------------------------------------------------------------

# 1. Phase 00 --- Scope and Architecture

## Deliverables

``` text
docs/data-source-policy.md
docs/threat-model.md
docs/architecture.md
docs/adr/
```

Create ADRs for:

-   evidence-first architecture
-   polyglot storage
-   temporal graph
-   models-as-hypotheses
-   synthetic-first evaluation

## Exit criteria

-   scope boundaries frozen
-   unauthorized/offensive behavior excluded
-   architecture reviewed
-   threat model approved

------------------------------------------------------------------------

# 2. Phase 01 --- Repository Foundation

Create:

``` text
apps/
services/
packages/
ml/
infra/
tests/
benchmarks/
docs/
scripts/
```

Use:

``` text
Python 3.12+
uv
ruff
mypy
pytest
pre-commit
React + TypeScript + Vite
```

CI must run:

``` text
lint
typecheck
unit tests
schema validation
security checks
build
```

Required commands:

``` bash
make test
make lint
make typecheck
make build
```

------------------------------------------------------------------------

# 3. Phase 02 --- Canonical Schemas

Create Pydantic models:

``` text
Evidence
Entity
Relationship
Source
Case
Hypothesis
AttributionAssessment
TimelineEvent
MigrationAssessment
ModelRun
```

Directory:

``` text
packages/schemas/
```

Rule:

> No service may invent its own evidence schema.

Tests:

-   valid serialization
-   invalid payload rejection
-   backwards-compatible versioning
-   JSON round-trip

------------------------------------------------------------------------

# 4. Phase 03 --- PostgreSQL + Evidence Ledger

Tables:

``` text
users
roles
cases
sources
evidence
entities
relationships
assessments
hypotheses
model_runs
audit_logs
collection_jobs
```

Every evidence record must include:

``` text
evidence_id
sha256
source_id
collected_at
collector_version
```

Create indexes for:

-   case_id
-   source_id
-   entity_id
-   observed_at
-   collected_at
-   hash

## Test

Generate 10,000 synthetic evidence records and verify uniqueness,
indexing, rollback and audit creation.

------------------------------------------------------------------------

# 5. Phase 04 --- Object Storage

Use S3-compatible storage.

Path:

``` text
evidence/{year}/{month}/{case}/{evidence_id}/
```

Store:

``` text
raw
normalized
metadata.json
```

Tests:

-   upload
-   checksum
-   retrieval
-   corrupted artifact
-   authorization
-   object-name injection

------------------------------------------------------------------------

# 6. Phase 05 --- Collector Framework

Create interface:

``` python
class Collector:
    async def discover(self, scope): ...
    async def collect(self, candidate): ...
    async def normalize(self, artifact): ...
```

First collectors must be synthetic:

``` text
SyntheticForumCollector
SyntheticMarketplaceCollector
SyntheticSurfaceCollector
```

Generate deterministic fixtures with known ground truth.

Target first dataset:

``` text
100 actors
1,000 posts
500+ known relationships
```

Exit criterion:

``` text
synthetic source
 -> collector
 -> evidence
```

works without direct database coupling.

------------------------------------------------------------------------

# 7. Phase 06 --- Normalization and Deduplication

Pipeline:

``` text
raw
 -> canonical encoding
 -> metadata normalization
 -> exact hash
 -> near duplicate
 -> source lineage
 -> observation
```

Implement:

-   SHA-256
-   normalized hash
-   SimHash/MinHash
-   duplicate cluster
-   source lineage

Test:

1.  exact duplicate
2.  HTML-only change
3.  copied content
4.  paraphrased content
5.  independent similar content

Goal: copied content must not be counted as independent evidence.

------------------------------------------------------------------------

# 8. Phase 07 --- Entity Extraction

Start with deterministic extraction:

``` text
handles
PGP fingerprints
wallet identifiers
domains
onion addresses
emails
URLs
```

Then add domain NER.

Each entity stores:

``` text
entity_id
type
surface_form
normalized_form
confidence
evidence_id
span
```

Test exact extraction and false-positive cases.

------------------------------------------------------------------------

# 9. Phase 08 --- Temporal Graph

Create Neo4j schema.

Nodes:

``` text
Actor
Handle
PGP
Wallet
Marketplace
Forum
Infrastructure
Post
Evidence
```

Edges:

``` text
USES_HANDLE
USES_PGP
ASSOCIATED_WITH
POSTED_ON
OBSERVED_AT
SIMILAR_TO
```

Relationship properties:

``` text
first_seen
last_seen
confidence
evidence_ids
```

Required graph queries:

1.  two-hop neighborhood
2.  common identifiers
3.  historical associations
4.  time-filtered neighborhood
5.  evidence path
6.  candidate pair neighborhood similarity

------------------------------------------------------------------------

# 10. Phase 09 --- Entity Resolution Baselines

Build in this exact order.

### Baseline 1

Exact normalized handle.

### Baseline 2

Edit distance.

### Baseline 3

TF-IDF cosine.

### Baseline 4

Logistic regression.

### Baseline 5

XGBoost.

Features:

``` text
handle similarity
character n-gram similarity
text similarity
temporal overlap
shared identifier
marketplace overlap
behavior similarity
graph neighborhood similarity
source reliability
```

Metrics:

``` text
precision
recall
F1
PR-AUC
MRR
Recall@K
```

Do not start GNN training until these baselines are frozen.

------------------------------------------------------------------------

# 11. Phase 10 --- Search and Retrieval

Deploy OpenSearch.

Indexes:

``` text
evidence
posts
documents
entities
reports
```

Features:

-   exact search
-   phrase search
-   time filtering
-   source filtering
-   entity filtering
-   hybrid retrieval

Set an explicit p95 latency target before optimization.

------------------------------------------------------------------------

# 12. Phase 11 --- Stylometry

## Step 1

Character and word n-grams.

## Step 2

Classical stylometric features.

## Step 3

Transformer embeddings.

## Step 4

Pairwise verification model.

## Step 5

Cross-marketplace evaluation.

## Step 6

Adversarial transformations.

Transform:

``` text
punctuation removal
case changes
slang normalization
paraphrase
translation
shortening
noise
```

Required outputs:

``` text
baseline metrics
cross-domain metrics
robustness curve
error analysis
```

Do not report only accuracy.

------------------------------------------------------------------------

# 13. Phase 12 --- Behavioral Profiling

Build:

``` text
BehaviorProfile
```

Features:

``` text
hour-of-day
day-of-week
posting rate
burstiness
inter-arrival distribution
response latency
topic distribution
platform distribution
interaction degree
```

First use statistical similarity.

Only after baseline performance is understood, add sequence models.

------------------------------------------------------------------------

# 14. Phase 13 --- Infrastructure Evidence

Implement passive feature extraction:

``` text
TLS metadata
HTTP metadata
content fingerprints
technology fingerprints
certificate metadata
historical changes
```

Do not implement intrusive origin discovery.

Output:

``` text
candidate correlation
similarity
evidence IDs
time range
source
limitations
```

Test false correlations using unrelated infrastructure.

------------------------------------------------------------------------

# 15. Phase 14 --- Financial Graph

Implement:

``` text
Wallet
Transaction
Counterparty
AddressCluster
```

Features:

``` text
degree
frequency
temporal burstiness
counterparty overlap
co-occurrence
cluster membership
```

Start with synthetic transaction graphs.

Only later add permitted public blockchain observations.

------------------------------------------------------------------------

# 16. Phase 15 --- Timeline and Change Detection

Create:

``` text
TimelineEvent
ChangePoint
MigrationCandidate
```

Start with:

``` text
CUSUM
distribution distance
ruptures/change-point algorithms
```

Detect:

-   handle changes
-   activity shifts
-   marketplace transitions
-   identifier rotations
-   infrastructure changes

------------------------------------------------------------------------

# 17. Phase 16 --- Attribution Baseline

Use transparent formula:

\[ S=`\sigma`{=tex}( w_hS_h+w_pS_p+w_wS_w+w_tS_t+w_bS_b+w_iS_i ) \]

Implement:

``` text
logistic regression
XGBoost
```

Return:

``` json
{
  "raw_score": 0.84,
  "evidence_ids": [],
  "model_version": "baseline-0.1"
}
```

Do not call this a probability until calibration is complete.

------------------------------------------------------------------------

# 18. Phase 17 --- Contradiction-Aware Fusion

For each pair store:

``` text
supporting evidence
contradictory evidence
unknown/missing evidence
```

Transparent baseline:

\[ w_i=r_iq_if_id_i \]

\[ S=`\sigma`{=tex}(`\alpha `{=tex}S^+-`\beta `{=tex}S^-) \]

where:

``` text
r = reliability
q = quality
f = temporal fit
d = independence discount
```

Build a test where ten copied sources are compared with ten independent
sources.

Expected result:

> copied evidence must not create equivalent confidence.

------------------------------------------------------------------------

# 19. Phase 18 --- Calibration

Methods:

-   Platt scaling
-   isotonic regression
-   temperature scaling

Metrics:

``` text
Brier
ECE
reliability diagram
calibration by evidence count
calibration by modality
```

Store:

``` text
raw_score
calibrated_confidence
calibration_version
```

------------------------------------------------------------------------

# 20. Phase 19 --- Temporal Heterogeneous GNN

Only now implement the research model.

Start:

``` text
R-GCN
```

Then:

``` text
HGT
```

Then add temporal encoding.

Graph nodes:

``` text
Actor
Handle
PGP
Wallet
Post
Marketplace
Infrastructure
BehaviorProfile
Evidence
```

Input:

``` text
node features
relation type
time
evidence features
```

Output:

``` text
P(candidate pair represents same activity/actor hypothesis)
```

Required comparison:

``` text
XGBoost
R-GCN
HGT
Temporal HGT
Temporal HGT + contradiction
```

------------------------------------------------------------------------

# 21. Phase 20 --- Adversarial Persona Simulator

Create synthetic actors with controllable transformations.

### L1

Alias change.

### L2

Alias + vocabulary.

### L3

Alias + behavior.

### L4

Alias + behavior + marketplace.

### L5

Multimodal adversarial migration.

Measure:

``` text
precision
recall
F1
false association rate
detection latency
performance degradation
```

Plot:

``` text
attack severity vs attribution performance
```

This should become a major paper figure.

------------------------------------------------------------------------

# 22. Phase 21 --- Benchmark + Ablation

Use:

### Actor-disjoint split

No same actor across train/test.

### Temporal split

Train on earlier time; test later.

### Platform-disjoint split

Where feasible, hold out platform/source families.

### Migration split

Test persona migration separately.

Ablations:

``` text
text only
behavior only
graph only
text + behavior
text + graph
text + behavior + graph
all modalities
all + contradiction
all + temporal
all + temporal + contradiction + provenance
```

Report both average performance and failure cases.

------------------------------------------------------------------------

# 23. Phase 22 --- Analyst Copilot

Tools:

``` text
search_evidence
query_graph
get_actor
get_timeline
get_assessment
compare_hypotheses
generate_report
```

Flow:

``` text
question
 -> intent
 -> structured query
 -> graph/search retrieval
 -> evidence pack
 -> LLM synthesis
 -> citation validation
 -> answer
```

Security test:

Insert malicious instructions inside collected text.

Expected behavior:

> The model treats the text as evidence, never as system instructions.

------------------------------------------------------------------------

# 24. Phase 23 --- Investigation UI

Build screens in this order:

1.  case list
2.  case workspace
3.  evidence explorer
4.  actor profile
5.  timeline
6.  graph
7.  attribution assessment
8.  hypothesis comparison
9.  source reliability
10. report builder

Actor page should show:

``` text
aliases
identifiers
confidence
evidence matrix
timeline
graph
stylometry
behavior
infrastructure
financial indicators
contradictions
model explanation
audit trail
```

------------------------------------------------------------------------

# 25. Phase 24 --- Reporting + STIX

Report sections:

``` text
Executive Summary
Actor Profile
Identifiers
Timeline
Infrastructure
Behavior
Financial Indicators
Evidence Matrix
Contradictions
Attribution Assessment
Limitations
Source Registry
```

Exports:

``` text
CSV
JSON
PDF
STIX 2.1
```

Every report stores:

``` text
case ID
generation time
query
evidence IDs
model versions
dataset versions
```

------------------------------------------------------------------------

# 26. Phase 25 --- Security Hardening

Run:

``` text
dependency scan
SAST
DAST
secret scan
container scan
```

Test:

-   broken access control
-   SSRF
-   injection
-   path traversal
-   oversized payloads
-   rate-limit bypass
-   evidence access
-   export leakage
-   audit bypass

Treat every external artifact as hostile input.

------------------------------------------------------------------------

# 27. Phase 26 --- MLOps + Observability

Application metrics:

``` text
request latency
error rate
throughput
```

Pipeline metrics:

``` text
collector success
collection latency
normalization failures
extraction confidence
graph update latency
```

ML metrics:

``` text
score drift
feature drift
calibration drift
false-association reports
```

Use OpenTelemetry to trace:

``` text
API
 -> retrieval
 -> graph
 -> model
 -> report
```

------------------------------------------------------------------------

# 28. Phase 27 --- Load and Failure Testing

Test data sizes:

``` text
10K evidence
100K
1M
```

Measure:

``` text
ingestion throughput
graph insertion
search
graph traversal
inference
storage
```

Failure injection:

``` text
Neo4j unavailable
Postgres unavailable
OpenSearch unavailable
collector timeout
LLM timeout
object storage failure
event-bus backlog
```

Expected behavior:

-   graceful degradation
-   retry where appropriate
-   no silent evidence loss
-   clear operational alerts

------------------------------------------------------------------------

# 29. Phase 28 --- End-to-End Rehearsal

Execute one complete synthetic investigation:

``` text
seed handle
 -> collect
 -> normalize
 -> extract
 -> graph
 -> candidate generation
 -> stylometry
 -> behavior
 -> infrastructure
 -> financial
 -> temporal analysis
 -> fusion
 -> calibration
 -> analyst review
 -> report
```

Measure:

``` text
time-to-first-evidence
time-to-candidate
time-to-assessment
total processing time
```

------------------------------------------------------------------------

# 30. Phase 29 --- Research Package

Prepare:

``` text
problem
related work
threat model
method
evidence model
graph model
fusion model
adversarial benchmark
experiments
ablations
limitations
```

Artifacts:

``` text
data card
model card
experiment registry
benchmark scripts
plots
tables
reproduction instructions
```

------------------------------------------------------------------------

# 31. Exact Repository Build

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

# 32. Sprint Plan

## Sprint 1 --- Foundation

Days 1--7:

``` text
repo
CI
schemas
Postgres
evidence
object storage
synthetic collector
```

Deliverable:

``` text
synthetic source -> immutable evidence
```

## Sprint 2 --- Graph

Days 8--14:

``` text
normalization
dedup
entity extraction
Neo4j
OpenSearch
resolution baseline
```

Deliverable:

``` text
seed -> candidates -> evidence -> graph -> timeline
```

## Sprint 3 --- Multimodal Intelligence

Days 15--21:

``` text
stylometry
behavior
infrastructure schema
financial graph
```

Deliverable:

``` text
multimodal candidate profile
```

## Sprint 4 --- Attribution

Days 22--28:

``` text
baseline attribution
contradictions
independence
calibration
change detection
migration candidates
```

Deliverable:

``` text
evidence-aware attribution assessment
```

## Sprint 5 --- Research Model

Days 29--35:

``` text
R-GCN
HGT
temporal encoding
pair decoder
ablations
```

Deliverable:

``` text
temporal heterogeneous attribution model
```

## Sprint 6 --- Adversarial Research

Days 36--42:

``` text
persona simulator
L1-L5
robustness
benchmark freeze
```

Deliverable:

``` text
persona migration benchmark
```

## Sprint 7 --- Analyst Product

Days 43--50:

``` text
LLM planner
retrieval tools
citation validator
case workspace
actor page
graph/timeline UI
```

Deliverable:

``` text
analyst workstation
```

## Sprint 8 --- Production

Days 51--57:

``` text
STIX
exports
RBAC
audit
observability
security
```

Deliverable:

``` text
production candidate
```

------------------------------------------------------------------------

# 33. Minimum Serious MVP

If time becomes constrained, retain:

``` text
synthetic collection
evidence ledger
entity extraction
temporal graph
entity resolution
stylometry
behavior
baseline attribution
evidence matrix
timeline
investigation UI
```

Do not sacrifice:

-   provenance
-   evaluation
-   contradictions
-   temporal reasoning

to add cosmetic features.

------------------------------------------------------------------------

# 34. End-to-End Demo Script

1.  Analyst enters seed handle.
2.  AEGIS retrieves observations.
3.  Entities are extracted.
4.  Graph expands.
5.  Candidate associations are generated.
6.  Stylometry and behavior are compared.
7.  Timeline reveals a possible migration.
8.  Infrastructure/financial signals add independent context.
9.  Fusion engine calculates calibrated assessment.
10. Contradictory evidence is shown.
11. Analyst opens the evidence matrix.
12. Copilot explains only retrieved evidence.
13. Analyst compares hypotheses.
14. Report is exported with provenance.

------------------------------------------------------------------------

# 35. Required Experiment Registry

Each experiment receives:

``` text
experiment_id
dataset_version
feature_version
model_version
seed
hyperparameters
metrics
git_commit
artifact paths
```

Never rely on screenshots of terminal output as experiment records.

------------------------------------------------------------------------

# 36. Required Reproduction Commands

The final project should support:

``` bash
make bootstrap
make data-generate
make data-validate
make train-baselines
make train-graph
make evaluate
make benchmark
make report
make up
make down
```

A clean environment should reproduce the primary experiment.

------------------------------------------------------------------------

# 37. Definition of Done --- Research

Research core is complete only when:

-   baselines exist
-   final model exists
-   actor-disjoint evaluation exists
-   temporal evaluation exists
-   adversarial benchmark exists
-   contradiction model is tested
-   calibration is reported
-   ablations are complete
-   failure cases are analyzed
-   reproduction package exists

------------------------------------------------------------------------

# 38. Definition of Done --- Product

Product is complete only when:

-   analyst can create a case
-   analyst can seed an entity
-   evidence is searchable
-   graph is explorable
-   timeline is queryable
-   candidates are assessed
-   evidence matrix is visible
-   contradictions are visible
-   reports are reproducible
-   exports are supported
-   permissions are enforced
-   actions are audited
-   failures are observable

------------------------------------------------------------------------

# 39. Final Implementation Rule

The project should evolve in this order:

``` text
Evidence
  ↓
Provenance
  ↓
Graph
  ↓
Baselines
  ↓
Multimodal features
  ↓
Temporal modeling
  ↓
Contradiction fusion
  ↓
GNN
  ↓
Adversarial benchmark
  ↓
LLM
  ↓
UI
  ↓
Production hardening
```

Do not build:

``` text
LLM -> guess -> graph -> dashboard
```

Build:

``` text
Evidence -> model -> assessment -> explanation -> analyst
```

That ordering is the core engineering discipline of AEGIS.
