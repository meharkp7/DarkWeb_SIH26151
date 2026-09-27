# ADR-002 — Polyglot Storage

## Status
Accepted

## Decision
Use PostgreSQL for transactional system state, object storage for raw artifacts, Neo4j for relationship traversal, and OpenSearch for retrieval.

## Rationale
The workloads have materially different access patterns and consistency requirements.
