# AEGIS — Attribution & Evidence Graph Intelligence System

[![CI](https://github.com/meharkp7/DarkWeb_SIH26151/actions/workflows/ci.yml/badge.svg)](https://github.com/meharkp7/DarkWeb_SIH26151/actions/workflows/ci.yml)

Evidence-centric foundation for lawful defensive threat-intelligence research, controlled synthetic experiments, and authorized investigations.

**Scope: synthetic-only.** AEGIS generates and evaluates against controlled synthetic data; it does not collect from or operate against live targets.

## Status

**Phases 00–18 are implemented; phases 19–29 are reference or partial foundations.**
The current completion matrix, including explicit operational and research gaps, is in
[`docs/phase-16-onward-status.md`](docs/phase-16-onward-status.md). The investigation UI
now includes durable case creation and retrieval; its remaining screens progressively use
the available evidence and analysis APIs.

What exists today:

- **Evidence ledger** — Postgres rows with provenance, derivation links, RBAC records, and a hash-chained audit log
- **Canonical schemas & ontology** — versioned Pydantic contracts and the entity/relationship type registry
- **Artifacts** — content-addressed local object store with SHA-256 integrity verification
- **Collection** — collector protocol, orchestration, deterministic synthetic corpus
- **Normalization & extraction** — canonical encoding, near-duplicate/lineage tracking, deterministic entity extraction + domain NER
- **Temporal graph** — in-process store with the six required queries; parameterized Neo4j Cypher adapter
- **Entities, hypotheses, assessments, model registry** — analysis records with versioning and provenance
- **Entity-resolution baselines** — five baselines over nine frozen candidate-pair features
- **Search & retrieval** — in-process BM25 + hybrid engine with an explicit p95 latency budget; lazy OpenSearch adapter
- **Multimodal services** — stylometry, behavioral profiling, infrastructure fingerprint correlation, financial (wallet/transaction/cluster) graph
- **Scenario pipeline & evaluation** — deterministic benchmark scenarios and metrics
- **Timeline & change detection** — timeline events, change points, migration candidates
- **FastAPI service** — evidence, provenance, and synthetic-analysis endpoints

## Architecture in one paragraph

**PostgreSQL is the system of record**; its schema comes *only* from alembic migrations
(`alembic/versions`) — run `make migrate`, never ad-hoc DDL. **Neo4j (relationships),
OpenSearch (retrieval), and S3-compatible object storage are non-authoritative adapters**
imported lazily behind optional extras; the in-process implementations in `aegis.graph`,
`aegis.search`, and `aegis.storage` are what tests and CI use. Models produce hypotheses;
analysts make findings. Details: `docs/architecture.md` and the ADRs in `docs/adr/`.

## Setup

```bash
cp .env.example .env
uv sync --extra dev
make infra-up        # docker compose: Postgres 17 only
make migrate         # alembic upgrade head
uv run uvicorn aegis.api.app:app --reload --host 127.0.0.1 --port 8000
```

If `uv` is not installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then restart the terminal and run the setup commands above.

### Optional dependency extras

`opensearch-py` and `boto3` are optional; their adapters lazy-import them, so the base
install and the test suite never need them:

```bash
uv sync --extra dev --extra search --extra s3
```

| Extra | Provides | Used by |
|-------|----------|---------|
| `search` | `opensearch-py` | `aegis.search.opensearch.OpenSearchAdapter` |
| `s3` | `boto3` | `aegis.storage.s3.S3ObjectStore` |

## Quality gates

```bash
make lint             # ruff check + ruff format --check (src tests scripts)
make typecheck        # mypy --strict over src
make schema-check     # canonical schema + ontology validation
make security-scan    # dependency + secret scan, security-focused tests
make test             # full pytest run
```

Raw equivalents:

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
PYTHONPATH=src uv run pytest -q
```

## Running the tests

- **Unit tests** — no services required:

  ```bash
  make test
  ```

- **Integration tests** — require PostgreSQL 17 (marked `integration`):

  ```bash
  make infra-up           # docker compose up -d (Postgres 17 only)
  make migrate            # apply alembic migrations
  make test-integration   # AEGIS_REQUIRE_DB=1 pytest -m integration
  ```

Without a reachable database, integration tests skip; with `AEGIS_REQUIRE_DB=1` (which CI
sets) a missing database fails loudly instead of disappearing. `docker-compose.yml`
provisions Postgres only — Neo4j/OpenSearch are optional deployment adapters, not test
dependencies.

## CI

The `CI` workflow runs on pushes to `main` and on pull requests:

| Job | What it does |
|-----|--------------|
| Lint | `ruff check` + `ruff format --check` over `src tests scripts` |
| Typecheck | `mypy src` (strict) |
| Unit + integration tests | alembic migrations, then pytest against a **Postgres 17 service** with `AEGIS_REQUIRE_DB=1` |
| Schema validation | canonical schema/ontology validation + alembic history check |
| Security checks | dependency scan, secret scan, security-focused tests |
| Build | `uv build` + wheel import check |
| Frontend build | npm lint/typecheck/build — auto-skips while `apps/frontend/package.json` is absent |

## API

- `GET /health`
- `GET /health/db`
- `POST /api/v1/sources`
- `POST /api/v1/evidence`
- `GET /api/v1/evidence/{evidence_id}`
- `GET /api/v1/evidence/{evidence_id}/provenance`
- `POST /api/v1/analysis/synthetic`

Swagger UI: `http://127.0.0.1:8000/docs`

## Documentation

- `docs/architecture.md` — logical architecture, storage responsibilities, deployment topologies
- `docs/adr/` — architecture decision records (evidence-first, polyglot storage, temporal graph, models-as-hypotheses, synthetic-first evaluation)
- `docs/threat-model.md`, `docs/data-source-policy.md`
- `AEGIS_Step_by_Step_Implementation_Plan.md` — the phase plan this status tracks
