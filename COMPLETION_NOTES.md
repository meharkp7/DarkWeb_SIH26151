# AEGIS completion pass

This bundle completes the remaining Phase 22–29 reference-layer work on top of the existing AEGIS stack.

## Added / completed

- Durable case workspace APIs for evidence, entities, relationships and assessments.
- Case-scoped report builder with JSON, CSV, STIX 2.1 and PDF exports.
- Optional API-key gateway control via `AEGIS_ENABLE_API_KEY_AUTH`.
- Metrics histograms, gauges, ML drift helpers and optional OpenTelemetry span helper.
- Synthetic 10K/100K/1M scale harness and dependency-failure matrix.
- Research protocol, experiment table and plotting/table checklist.
- Existing React investigation UI wired to durable workspace and report APIs.
- OpenSearch 2.19.1 local service, explicit index mappings and refresh-on-write behavior.

## Local install

```bash
uv lock
uv sync --extra dev --extra search --extra report --extra telemetry
cd apps/frontend && npm install && cd ../..
```

## Local validation

```bash
make infra-up
make migrate

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 uv run pytest

uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
cd apps/frontend && npm run lint && npm run typecheck && npm run build && cd ../..

make benchmark
make scale-test
make failure-matrix
make rehearsal
```

## Operational boundary

The implementation remains synthetic-first. PostgreSQL is authoritative; OpenSearch,
Neo4j and object storage are adapters. Live collection, organization SSO/RBAC,
distributed rate limiting, DAST/container scanning and model calibration on authorized
labeled data are deployment-specific steps and must not be represented as completed by
synthetic tests.
