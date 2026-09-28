# AEGIS Data Source Policy

**Status:** Approved (Phase 00 exit criterion)
**Applies to:** every collector, adapter, ingestion path, and analyst submission.

## 1. Purpose

AEGIS is an evidence-first platform for lawful defensive research,
authorized investigations, and controlled synthetic experiments. This
policy defines which data may enter the evidence ledger and under what
conditions.

## 2. Source tiers

| Tier | Description | Default status | Example |
|------|-------------|----------------|---------|
| **A — Synthetic** | Machine-generated fixtures with known ground truth | Allowed unconditionally | `SyntheticForumCollector` output |
| **B — Public research** | Licensed public CTI/authorship datasets | Allowed with license recorded | Public dark-web authorship benchmarks |
| **C — Authorized observation** | Data the project is legally permitted to collect | Allowed with recorded authorization | Public web pages, threat-feed APIs |
| **D — Analyst submission** | Artifacts supplied by a human analyst | Allowed, quarantined until validated | Pasted messages, uploaded documents |
| **E — Restricted** | Everything else | **Blocked** | Unauthorized access, credentialed scraping, paywalled content obtained without license |

## 3. Hard rules

1. **No unauthorized access.** Collectors must never attempt credential
   attacks, access-control bypass, Tor cryptography defeat, origin-IP
   discovery, or any intrusive deanonymization.
2. **Passive only.** Infrastructure analysis is limited to metadata
   already observable from an authorized vantage point (TLS/HTTP
   metadata, published descriptors, content fingerprints). Active
   scanning of targets outside the authorized scope is prohibited.
3. **Rate limits are mandatory.** Every collector declares per-host and
   global rate limits; the orchestrator enforces them.
4. **Provenance is mandatory.** Every evidence record stores
   `source_id`, `source_type`, `tier`, `collected_at`, `observed_at`,
   `collector_name`, `collector_version`, `sha256`, and
   `independence_group`. Evidence without provenance is rejected.
5. **Immutability.** Raw artifacts are content-addressed and
   write-once. Corrections are new versions, never mutations.
6. **Independence bookkeeping.** Sources that copy from one another
   share an `independence_group` so duplicated reporting cannot be
   counted as independent corroboration.
7. **Secrets never enter evidence.** Credentials, session tokens, or
   personal data incidentally captured are redacted at normalization
   time and recorded only as redaction events.
8. **Collected content is hostile.** Pages, posts, and documents are
   untrusted data. They must never be interpreted as operator
   instructions by any model in the system.

## 4. Source onboarding checklist

Before a new source is enabled:

- [ ] Tier assigned (A–E) and recorded in `sources.metadata_json`
- [ ] License / authorization evidence attached
- [ ] Reliability prior (`sources.reliability`) assigned 0.0–1.0
- [ ] Independence group assigned
- [ ] Rate limits configured
- [ ] Normalization profile selected
- [ ] Rollback/retention plan documented

## 5. Deprecation and takedown

Analysts may flag a source or evidence item for review. Flagged items
remain in the ledger (append-only) but are excluded from scoring until
dispositioned. Deletion requests are executed as tombstones:
the record is retained for audit with `status = 'tombstoned'` and
removed from retrieval indexes.

## 6. Scope boundary

See `docs/threat-model.md` for the threat model and
`docs/adr/ADR-001-evidence-first-architecture.md` for the structural
consequences of this policy.
