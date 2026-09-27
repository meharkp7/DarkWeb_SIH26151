from dataclasses import dataclass

from aegis.synthetic.candidate_links import CandidateLink
from aegis.synthetic.evidence import SyntheticEvidence


@dataclass(frozen=True)
class Contradiction:
    evidence_id: str
    contradiction_type: str
    severity: float
    explanation: str


@dataclass(frozen=True)
class ContradictionAnalysis:
    link_id: str
    contradictions: tuple[Contradiction, ...]
    contradiction_score: float


class ContradictionDetector:
    """Detect evidence that conflicts with a candidate actor linkage."""

    def analyze(
        self,
        candidate: CandidateLink,
        evidence: list[SyntheticEvidence],
    ) -> ContradictionAnalysis:
        source = [item for item in evidence if item.actor_id == candidate.source_actor_id]
        target = [item for item in evidence if item.actor_id == candidate.target_actor_id]

        contradictions: list[Contradiction] = []

        self._check_timezone(source, target, contradictions)
        self._check_language(source, target, contradictions)

        total = sum(item.severity for item in contradictions)

        return ContradictionAnalysis(
            link_id=candidate.link_id,
            contradictions=tuple(contradictions),
            contradiction_score=round(
                min(total, 1.0),
                3,
            ),
        )

    @staticmethod
    def _check_timezone(
        source: list[SyntheticEvidence],
        target: list[SyntheticEvidence],
        contradictions: list[Contradiction],
    ) -> None:
        source_values = {item.value for item in source if item.evidence_type == "timezone"}
        target_values = {item.value for item in target if item.evidence_type == "timezone"}

        if source_values and target_values and source_values.isdisjoint(target_values):
            item = next(item for item in target if item.evidence_type == "timezone")

            contradictions.append(
                Contradiction(
                    evidence_id=item.evidence_id,
                    contradiction_type="timezone_conflict",
                    severity=0.35,
                    explanation=(
                        "Observed timezone evidence is inconsistent between the candidate actors."
                    ),
                )
            )

    @staticmethod
    def _check_language(
        source: list[SyntheticEvidence],
        target: list[SyntheticEvidence],
        contradictions: list[Contradiction],
    ) -> None:
        source_languages = {item.value for item in source if item.evidence_type == "writing_style"}
        target_languages = {item.value for item in target if item.evidence_type == "writing_style"}

        if source_languages and target_languages and source_languages.isdisjoint(target_languages):
            item = next(item for item in target if item.evidence_type == "writing_style")

            contradictions.append(
                Contradiction(
                    evidence_id=item.evidence_id,
                    contradiction_type="writing_style_conflict",
                    severity=0.25,
                    explanation=(
                        "Observed writing-style indicators are "
                        "inconsistent between the candidate actors."
                    ),
                )
            )
