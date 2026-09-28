"""Ingestion bridge: the only place where collector output meets the ledger.

This is what keeps collectors decoupled from persistence: the
orchestrator produces :class:`NormalizedArtifact` value objects, and this
module translates them into immutable evidence records.

Idempotency is checked with a *single batched prefetch* (one
``sha256 IN (...)`` query scoped to the ingest source) instead of one
SELECT per observation, so the duplicate check no longer scales with
batch size; rows created later in the same batch are folded back into
the lookup map so within-batch duplicates are still skipped exactly as
they were when every row was re-read from the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from aegis.collection.types import NormalizedArtifact
from aegis.db.models import EvidenceRecord
from aegis.evidence.service import EvidenceService
from aegis.schemas.evidence import EvidenceCreate, SourceType

#: Observation identity: (content digest, observed time) for one source.
ObservationKey = tuple[str, datetime | None]


@dataclass(frozen=True)
class IngestionResult:
    created: int
    skipped_duplicates: int
    evidence_ids: tuple[UUID, ...]


class CollectionIngestor:
    """Idempotent collector-output → evidence-ledger bridge."""

    normalizer_version = "0.1.0"

    def __init__(self, evidence_service: EvidenceService) -> None:
        self.evidence_service = evidence_service

    def ingest(
        self,
        observations: list[NormalizedArtifact] | tuple[NormalizedArtifact, ...],
        *,
        source_id: UUID,
        source_type: SourceType = SourceType.SYNTHETIC,
        case_id: UUID | None = None,
        source_reliability: float = 0.8,
    ) -> IngestionResult:
        created = 0
        skipped = 0
        evidence_ids: list[UUID] = []

        # One prefetch for the whole batch: idempotency is scoped to
        # observation identity (content + source + observed time), so the
        # query is scoped to this source and matched per row in memory.
        # The same bytes seen from a different source or at a later scan
        # are a new observation, not a duplicate. Empty batches skip the
        # prefetch entirely (no query issued).
        seen: dict[ObservationKey, EvidenceRecord] = (
            self.evidence_service.get_observations_batch(
                [observation.raw.sha256 for observation in observations],
                source_id,
            )
            if observations
            else {}
        )

        for observation in observations:
            raw = observation.raw
            key: ObservationKey = (raw.sha256, observation.observed_at)
            if key in seen:
                skipped += 1
                continue

            metadata = dict(observation.metadata)
            metadata.update(
                {
                    "author_hint": observation.author_hint,
                    "platform": observation.platform,
                    "source_url": raw.source_url,
                    "candidate_id": raw.candidate.candidate_id,
                    "observed_text_sha256": sha256(
                        observation.normalized_text.encode("utf-8")
                    ).hexdigest(),
                }
            )

            payload = EvidenceCreate(
                case_id=case_id,
                source_id=source_id,
                source_type=source_type,
                observed_at=observation.observed_at,
                collected_at=raw.collected_at,
                raw_artifact_uri=raw.source_url,
                sha256=raw.sha256,
                collector_name=raw.collector_name,
                collector_version=raw.collector_version,
                normalizer_version=self.normalizer_version,
                source_reliability=source_reliability,
                independence_group=observation.independence_group,
                metadata=metadata,
            )
            record = self.evidence_service.create_evidence(payload, raw.body)
            created += 1
            evidence_ids.append(record.evidence_id)
            # Fold the row just written back into the lookup map: a later
            # observation with the same identity must be skipped, exactly
            # as it was when get_observation re-read the committed row.
            seen[key] = record

        return IngestionResult(
            created=created, skipped_duplicates=skipped, evidence_ids=tuple(evidence_ids)
        )
