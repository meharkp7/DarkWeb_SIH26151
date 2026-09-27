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
    """Detect internally conflicting observations for candidate actors."""

    def analyze(
        self,
        candidate: CandidateLink,
        evidence: list[SyntheticEvidence],
    ) -> ContradictionAnalysis:
        source = [item for item in evidence if item.actor_id == candidate.source_actor_id]
        target = [item for item in evidence if item.actor_id == candidate.target_actor_id]

        contradictions: list[Contradiction] = []

        self._check_internal_conflicts(source, contradictions)
        self._check_internal_conflicts(target, contradictions)

        total = sum(item.severity for item in contradictions)

        return ContradictionAnalysis(
            link_id=candidate.link_id,
            contradictions=tuple(contradictions),
            contradiction_score=round(min(total, 1.0), 3),
        )

    @staticmethod
    def _check_internal_conflicts(
        items: list[SyntheticEvidence],
        contradictions: list[Contradiction],
    ) -> None:
        for evidence_type in ("timezone", "writing_style", "wallet"):
            typed_items = [item for item in items if item.evidence_type == evidence_type]

            values = {item.value for item in typed_items}

            if len(values) <= 1:
                continue

            item = typed_items[-1]

            contradictions.append(
                Contradiction(
                    evidence_id=item.evidence_id,
                    contradiction_type=f"{evidence_type}_internal_conflict",
                    severity=0.45,
                    explanation=(
                        f"Multiple conflicting {evidence_type} observations "
                        "were recorded for the same actor."
                    ),
                )
            )
