from dataclasses import dataclass

from aegis.synthetic.calibration import CalibratedLink
from aegis.synthetic.contradiction import ContradictionAnalysis
from aegis.synthetic.evidence import SyntheticEvidence


@dataclass(frozen=True)
class HypothesisEvidence:
    evidence_id: str
    evidence_type: str
    independence_group: str
    confidence: float
    role: str


@dataclass(frozen=True)
class AttributionHypothesis:
    hypothesis_id: str
    source_actor_id: str
    target_actor_id: str
    raw_score: float
    support_score: float
    contradiction_score: float
    final_score: float
    status: str
    evidence: tuple[HypothesisEvidence, ...]
    explanations: tuple[str, ...]


class AttributionHypothesisBuilder:
    """Build auditable attribution hypotheses."""

    def build(
        self,
        calibrated_link: CalibratedLink,
        contradiction: ContradictionAnalysis,
        evidence: list[SyntheticEvidence],
    ) -> AttributionHypothesis:
        relevant_ids = {
            evidence_id
            for contribution in calibrated_link.contributions
            for evidence_id in contribution.evidence_ids
        }

        evidence_by_id = {item.evidence_id: item for item in evidence}

        hypothesis_evidence: list[HypothesisEvidence] = []

        for evidence_id in sorted(relevant_ids):
            item = evidence_by_id[evidence_id]

            hypothesis_evidence.append(
                HypothesisEvidence(
                    evidence_id=item.evidence_id,
                    evidence_type=item.evidence_type,
                    independence_group=item.independence_group,
                    confidence=item.confidence,
                    role="supporting",
                )
            )

        for contradiction_item in contradiction.contradictions:
            if contradiction_item.evidence_id in evidence_by_id:
                evidence_item = evidence_by_id[contradiction_item.evidence_id]

                hypothesis_evidence.append(
                    HypothesisEvidence(
                        evidence_id=contradiction_item.evidence_id,
                        evidence_type=evidence_item.evidence_type,
                        independence_group=evidence_item.independence_group,
                        confidence=evidence_item.confidence,
                        role="contradicting",
                    )
                )

        support_score = calibrated_link.calibrated_score
        contradiction_score = contradiction.contradiction_score

        final_score = self._combine_scores(
            support_score,
            contradiction_score,
        )

        actor_ids = sorted({item.actor_id for item in evidence if item.evidence_id in relevant_ids})

        if len(actor_ids) != 2:
            raise ValueError("Hypothesis requires evidence from exactly two actors")

        explanations = tuple(
            [
                f"support_score={support_score:.3f}",
                f"contradiction_score={contradiction_score:.3f}",
                f"final_score={final_score:.3f}",
            ]
        )

        return AttributionHypothesis(
            hypothesis_id=f"hypothesis:{calibrated_link.link_id}",
            source_actor_id=actor_ids[0],
            target_actor_id=actor_ids[1],
            raw_score=calibrated_link.raw_score,
            support_score=support_score,
            contradiction_score=contradiction_score,
            final_score=final_score,
            status="candidate",
            evidence=tuple(hypothesis_evidence),
            explanations=explanations,
        )

    @staticmethod
    def _combine_scores(
        support_score: float,
        contradiction_score: float,
    ) -> float:
        return round(
            max(
                0.0,
                min(
                    1.0,
                    support_score * (1.0 - contradiction_score),
                ),
            ),
            3,
        )
