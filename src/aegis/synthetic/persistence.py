"""Persist synthetic actors and evidence through the AEGIS evidence layer.

Two batching decisions live here (review findings):

* **One digest prefetch** — every item's content digest is collected
  first and resolved with a single ``sha256 IN (...)`` query
  (:meth:`EvidenceService.get_by_sha256_batch`) instead of one
  ``get_by_sha256`` SELECT per row. Rows created later in the same call
  are folded back into the lookup map, so a digest that repeats inside
  one batch still reuses the first record exactly as a per-row lookup
  would have.
* **No internal commit** — source and evidence inserts are flush-only. The
  analysis workflow owns the final commit, so a failed hypothesis write cannot
  leave a partially persisted evidence batch behind.
"""

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
            ),
            commit=False,
        )
        return source.source_id

    def persist_evidence(
        self,
        source_id: UUID,
        actors: list[SyntheticActor],
        evidence: list[SyntheticEvidence],
    ) -> list[EvidenceRecord]:
        """Insert (or content-reuse) every item without committing.

        Reuse is content-level: an item whose digest already exists in the
        ledger resolves to the earliest existing observation instead of a
        new row. On any failure the caller owns rollback (the analysis
        route rolls the session back).
        """
        actor_map = {actor.actor_id: actor for actor in actors}

        # Serialize once, up front: the digests drive the single prefetch.
        prepared: list[tuple[SyntheticEvidence, bytes, str]] = []
        for item in evidence:
            content = self._serialize_evidence(actor_map[item.actor_id], item)
            prepared.append((item, content, sha256(content).hexdigest()))

        reused_by_digest: dict[str, EvidenceRecord] = self.evidence_service.get_by_sha256_batch(
            [digest for _, _, digest in prepared]
        )

        records: list[EvidenceRecord] = []
        for item, content, digest in prepared:
            actor = actor_map[item.actor_id]
            existing = reused_by_digest.get(digest)

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

            record = self.evidence_service.create_evidence(
                payload,
                content,
                commit=False,
            )
            records.append(record)
            # Fold the row just flushed back into the map so a digest that
            # repeats later in this batch reuses it (get_by_sha256 would
            # have seen the committed row).
            reused_by_digest[digest] = record

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
