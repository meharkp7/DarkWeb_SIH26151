# ADR-001 — Evidence-First Architecture

## Status
Accepted

## Decision
Raw observations are immutable evidence objects. Derived entities, relationships, model outputs and analyst assessments reference evidence rather than replacing it.

## Rationale
Attribution requires provenance, reproducibility, contradiction analysis and auditability. A graph containing only inferred relationships cannot satisfy those requirements.

## Consequence
Every downstream service must preserve `evidence_id` references. No service may create an unattributed relationship.
