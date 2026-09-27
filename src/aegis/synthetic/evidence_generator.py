import hashlib
import random
from datetime import UTC, datetime, timedelta

from aegis.synthetic.actor import SyntheticActor
from aegis.synthetic.evidence import (
    SyntheticEvidence,
    SyntheticRelationship,
)


class SyntheticEvidenceGenerator:
    """Generate deterministic evidence and relationships for synthetic actors."""

    _EVIDENCE_TYPES = (
        "handle",
        "writing_style",
        "timezone",
        "wallet",
    )

    def __init__(self, seed: int = 26151) -> None:
        self.seed = seed

    def generate(
        self,
        actors: list[SyntheticActor],
    ) -> tuple[list[SyntheticEvidence], list[SyntheticRelationship]]:
        rng = random.Random(self.seed)
        evidence: list[SyntheticEvidence] = []

        base_time = datetime(2026, 1, 1, tzinfo=UTC)

        for actor in actors:
            for index, identity in enumerate(actor.identities):
                evidence.append(
                    SyntheticEvidence(
                        evidence_id=self._id(f"{actor.actor_id}:evidence:{index}"),
                        actor_id=actor.actor_id,
                        evidence_type="handle",
                        value=identity.handle,
                        confidence=round(rng.uniform(0.70, 0.98), 3),
                        observed_at=base_time + timedelta(days=rng.randint(0, 30)),
                        platform=identity.platform,
                        independence_group=f"platform:{identity.platform}",
                    )
                )

            for index, evidence_type in enumerate(
                self._EVIDENCE_TYPES[1:],
            ):
                evidence.append(
                    SyntheticEvidence(
                        evidence_id=self._id(f"{actor.actor_id}:indicator:{index}"),
                        actor_id=actor.actor_id,
                        evidence_type=evidence_type,
                        value=actor.indicators[index],
                        confidence=round(rng.uniform(0.55, 0.90), 3),
                        observed_at=base_time + timedelta(days=rng.randint(0, 30)),
                        platform="synthetic",
                        independence_group=f"indicator:{evidence_type}",
                    )
                )

        relationships = self._build_relationships(evidence)

        return evidence, relationships

    def _build_relationships(
        self,
        evidence: list[SyntheticEvidence],
    ) -> list[SyntheticRelationship]:
        relationships: list[SyntheticRelationship] = []

        by_actor: dict[str, list[SyntheticEvidence]] = {}

        for item in evidence:
            by_actor.setdefault(item.actor_id, []).append(item)

        for actor_items in by_actor.values():
            for left, right in zip(
                actor_items,
                actor_items[1:],
                strict=False,
            ):
                relationships.append(
                    SyntheticRelationship(
                        relationship_id=self._id(f"{left.evidence_id}:{right.evidence_id}"),
                        source_evidence_id=left.evidence_id,
                        target_evidence_id=right.evidence_id,
                        relationship_type="cross_platform_identity",
                        confidence=round(
                            min(left.confidence, right.confidence),
                            3,
                        ),
                    )
                )

        return relationships

    @staticmethod
    def _id(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:24]
