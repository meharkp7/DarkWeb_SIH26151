"""Explainable candidate-link generation between synthetic actors.

The engine groups evidence by actor once, builds one index per actor,
and then compares index *pairs* — so every per-actor structure (handles,
type -> evidence map) is computed ``O(actors)`` times instead of being
rebuilt inside the ``O(actors^2)`` comparison loop.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

from aegis.synthetic.evidence import SyntheticEvidence

#: Feature weights of the final score (kept frozen here so every call
#: site — including tests — reads one constant instead of rebuilding it).
FEATURE_WEIGHTS: dict[str, float] = {
    "handle_overlap": 0.15,
    "indicator_similarity": 0.85,
}

#: Relative weight of each comparable indicator type inside the
#: ``indicator_similarity`` feature.
INDICATOR_WEIGHTS: dict[str, float] = {
    "writing_style": 0.20,
    "timezone": 0.20,
    "wallet": 0.60,
}


@dataclass(frozen=True)
class LinkFeature:
    name: str
    score: float
    explanation: str


@dataclass(frozen=True)
class CandidateLink:
    link_id: str
    source_actor_id: str
    target_actor_id: str
    score: float
    features: tuple[LinkFeature, ...]


@dataclass(frozen=True)
class ActorIndex:
    """Per-actor lookup structures built once and reused for every pair.

    Rebuilding these inside the comparison loop made ``generate()`` do
    ``O(pairs x evidence)`` work; they only depend on the actor's own
    evidence, so they are computed once per actor (``O(actors)``).
    """

    handles: frozenset[str]
    #: evidence type -> its (last-seen) item, excluding ``handle`` entries
    by_type: Mapping[str, SyntheticEvidence]


class CandidateLinkEngine:
    """Generate explainable candidate links between synthetic actors."""

    def generate(
        self,
        evidence: list[SyntheticEvidence],
        min_score: float = 0.30,
    ) -> list[CandidateLink]:
        by_actor: dict[str, list[SyntheticEvidence]] = {}

        for item in evidence:
            by_actor.setdefault(item.actor_id, []).append(item)

        # one index per actor, hoisted OUT of the pair loop below
        indexes = {actor_id: self.index(items) for actor_id, items in by_actor.items()}
        actor_ids = sorted(by_actor)
        candidates: list[CandidateLink] = []

        for source_id, target_id in combinations(actor_ids, 2):
            features = self._compare(
                indexes[source_id],
                indexes[target_id],
            )

            score = self._aggregate(features)

            if score < min_score:
                continue

            candidates.append(
                CandidateLink(
                    link_id=self._link_id(source_id, target_id),
                    source_actor_id=source_id,
                    target_actor_id=target_id,
                    score=score,
                    features=tuple(features),
                )
            )

        return candidates

    @staticmethod
    def index(items: list[SyntheticEvidence]) -> ActorIndex:
        """Build one actor's comparison index (handles + type -> evidence)."""
        return ActorIndex(
            handles=frozenset(
                item.value.lower() for item in items if item.evidence_type == "handle"
            ),
            by_type={item.evidence_type: item for item in items if item.evidence_type != "handle"},
        )

    @staticmethod
    def _compare(
        source: ActorIndex,
        target: ActorIndex,
    ) -> list[LinkFeature]:
        features: list[LinkFeature] = []

        handle_overlap = bool(source.handles & target.handles)

        features.append(
            LinkFeature(
                name="handle_overlap",
                score=1.0 if handle_overlap else 0.0,
                explanation=(
                    "At least one normalized handle is shared."
                    if handle_overlap
                    else "No normalized handle is shared."
                ),
            )
        )

        comparable_types = sorted(set(source.by_type) & set(target.by_type))

        weighted_matches = 0.0
        total_weight = 0.0
        matches = 0
        for evidence_type in comparable_types:
            weight = INDICATOR_WEIGHTS.get(evidence_type, 0.0)
            if weight <= 0.0:
                continue

            source_item = source.by_type[evidence_type]
            target_item = target.by_type[evidence_type]

            total_weight += weight

            if source_item.value == target_item.value:
                matches += 1
                confidence_quality = min(
                    source_item.confidence,
                    target_item.confidence,
                )
                weighted_matches += weight * confidence_quality

        indicator_score = weighted_matches / total_weight if total_weight else 0.0
        comparable = len(comparable_types)

        features.append(
            LinkFeature(
                name="indicator_similarity",
                score=indicator_score,
                explanation=(f"{matches} of {comparable} comparable indicators match."),
            )
        )

        return features

    @staticmethod
    def _aggregate(features: list[LinkFeature]) -> float:
        if not features:
            return 0.0

        weighted_score = sum(
            feature.score * FEATURE_WEIGHTS.get(feature.name, 0.0) for feature in features
        )

        return round(weighted_score, 3)

    @staticmethod
    def _link_id(source_id: str, target_id: str) -> str:
        value = f"{source_id}:{target_id}"
        return hashlib.sha256(value.encode()).hexdigest()[:24]
