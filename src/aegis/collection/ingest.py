"""Ingestion bridge: the only place where collector output meets the ledger.

This is what keeps collectors decoupled from persistence: the
orchestrator produces :class:`NormalizedArtifact` value objects, and this
module translates them into immutable evidence records.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from aegis.collection.types import NormalizedArtifact
from aegis.evidence.service import EvidenceService
from aegis.schemas.evidence import EvidenceCreate, SourceType


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

        for observation in observations:
            raw = observation.raw
            # Idempotency is scoped to observation identity (content +
            # source + observed time): the same bytes seen from a
            # different source or at a later scan are a new observation,
            # not a duplicate.
            if (
                self.evidence_service.get_observation(
                    raw.sha256, source_id, observation.observed_at
                )
                is not None
            ):
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

        return IngestionResult(
            created=created, skipped_duplicates=skipped, evidence_ids=tuple(evidence_ids)
        )
