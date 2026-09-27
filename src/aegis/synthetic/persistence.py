from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from aegis.db.models import EvidenceRecord
from aegis.evidence.service import EvidenceService
from aegis.schemas.evidence import EvidenceCreate, SourceCreate, SourceType
from aegis.synthetic.actor import SyntheticActor
from aegis.synthetic.evidence import SyntheticEvidence


class SyntheticPersistenceService:
    """Persist synthetic actors and evidence through the AEGIS evidence layer."""

    def __init__(self, evidence_service: EvidenceService) -> None:
        self.evidence_service = evidence_service

    def create_source(self) -> UUID:
        source = self.evidence_service.create_source(
            SourceCreate(
                source_type=SourceType.SYNTHETIC,
                name="AEGIS Synthetic Generator",
                reliability=1.0,
                metadata={
                    "generator": "SyntheticActorGenerator",
                    "generator_version": "0.1.0",
                },
            )
        )
        return source.source_id

    def persist_evidence(
        self,
        source_id: UUID,
        actors: list[SyntheticActor],
        evidence: list[SyntheticEvidence],
    ) -> list[EvidenceRecord]:
        actor_map = {actor.actor_id: actor for actor in actors}
        records: list[EvidenceRecord] = []

        for item in evidence:
            actor = actor_map[item.actor_id]
            content = self._serialize_evidence(actor, item)
            digest = sha256(content).hexdigest()

            existing = self.evidence_service.get_by_sha256(digest)

            if existing is not None:
                records.append(existing)
                continue

            payload = EvidenceCreate(
                source_id=source_id,
                source_type=SourceType.SYNTHETIC,
                observed_at=item.observed_at,
                collected_at=datetime.now(UTC),
                entity_type=item.evidence_type,
                entity_value_hash=sha256(item.value.encode()).hexdigest(),
                raw_artifact_uri=f"synthetic://evidence/{item.evidence_id}",
                sha256=digest,
                collector_name="SyntheticEvidenceGenerator",
                collector_version="0.1.0",
                normalizer_version="0.1.0",
                extraction_version="0.1.0",
                source_reliability=item.confidence,
                independence_group=item.independence_group,
                metadata={
                    "synthetic": True,
                    "actor_id": actor.actor_id,
                    "actor_alias": actor.alias,
                    "platform": item.platform,
                    "evidence_type": item.evidence_type,
                    "relationship_ready": True,
                },
            )

            records.append(
                self.evidence_service.create_evidence(
                    payload,
                    content,
                )
            )

        return records

    @staticmethod
    def _serialize_evidence(
        actor: SyntheticActor,
        item: SyntheticEvidence,
    ) -> bytes:
        return (
            f"actor_id={actor.actor_id}\n"
            f"actor_alias={actor.alias}\n"
            f"evidence_id={item.evidence_id}\n"
            f"type={item.evidence_type}\n"
            f"value={item.value}\n"
            f"platform={item.platform}\n"
            f"observed_at={item.observed_at.isoformat()}\n"
        ).encode()
