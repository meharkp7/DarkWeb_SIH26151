from dataclasses import dataclass
from itertools import combinations

from aegis.synthetic.evidence import SyntheticEvidence


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

        actor_ids = sorted(by_actor)
        candidates: list[CandidateLink] = []

        for source_id, target_id in combinations(actor_ids, 2):
            features = self._compare(
                by_actor[source_id],
                by_actor[target_id],
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
    def _compare(
        source: list[SyntheticEvidence],
        target: list[SyntheticEvidence],
    ) -> list[LinkFeature]:
        features: list[LinkFeature] = []

        source_handles = {item.value.lower() for item in source if item.evidence_type == "handle"}
        target_handles = {item.value.lower() for item in target if item.evidence_type == "handle"}

        handle_overlap = bool(source_handles & target_handles)

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

        source_indicators = {
            item.evidence_type: item.value for item in source if item.evidence_type != "handle"
        }
        target_indicators = {
            item.evidence_type: item.value for item in target if item.evidence_type != "handle"
        }

        matches = sum(
            source_indicators.get(key) == value for key, value in target_indicators.items()
        )
        comparable = len(set(source_indicators) & set(target_indicators))
        indicator_score = matches / comparable if comparable else 0.0

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

        weights = {
            "handle_overlap": 0.15,
            "indicator_similarity": 0.85,
        }

        weighted_score = sum(feature.score * weights.get(feature.name, 0.0) for feature in features)

        return round(weighted_score, 3)

    @staticmethod
    def _link_id(source_id: str, target_id: str) -> str:
        import hashlib

        value = f"{source_id}:{target_id}"
        return hashlib.sha256(value.encode()).hexdigest()[:24]
