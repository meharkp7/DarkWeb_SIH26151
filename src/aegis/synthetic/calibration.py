from dataclasses import dataclass

from aegis.synthetic.candidate_links import CandidateLink
from aegis.synthetic.evidence import SyntheticEvidence


@dataclass(frozen=True)
class EvidenceContribution:
    independence_group: str
    raw_score: float
    effective_score: float
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CalibratedLink:
    link_id: str
    raw_score: float
    calibrated_score: float
    contributions: tuple[EvidenceContribution, ...]


class ConfidenceCalibrator:
    """Calibrate candidate-link confidence while limiting redundant evidence."""

    def calibrate(
        self,
        candidate: CandidateLink,
        evidence: list[SyntheticEvidence],
    ) -> CalibratedLink:
        actor_ids = {
            candidate.source_actor_id,
            candidate.target_actor_id,
        }

        relevant = [item for item in evidence if item.actor_id in actor_ids]

        grouped: dict[str, list[SyntheticEvidence]] = {}

        for item in relevant:
            grouped.setdefault(item.independence_group, []).append(item)

        contributions: list[EvidenceContribution] = []

        for group, items in sorted(grouped.items()):
            raw_score = sum(item.confidence for item in items) / len(items)

            # Multiple observations from the same independence group
            # contribute diminishing evidence rather than full additive weight.
            effective_score = raw_score

            contributions.append(
                EvidenceContribution(
                    independence_group=group,
                    raw_score=round(raw_score, 3),
                    effective_score=round(effective_score, 3),
                    evidence_ids=tuple(sorted(item.evidence_id for item in items)),
                )
            )

        calibrated_score = self._calibrate(
            candidate.score,
            contributions,
        )

        return CalibratedLink(
            link_id=candidate.link_id,
            raw_score=round(candidate.score, 3),
            calibrated_score=calibrated_score,
            contributions=tuple(contributions),
        )

    @staticmethod
    def _calibrate(
        candidate_score: float,
        contributions: list[EvidenceContribution],
    ) -> float:
        if not contributions:
            return 0.0

        if candidate_score <= 0.0:
            return 0.0

        independent_scores = [contribution.effective_score for contribution in contributions]

        evidence_support = sum(independent_scores) / len(independent_scores)

        return round(
            (candidate_score * 0.6) + (evidence_support * 0.4),
            3,
        )
