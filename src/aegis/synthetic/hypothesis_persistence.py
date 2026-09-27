from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from aegis.db.models import (
    AttributionHypothesisRecord,
    HypothesisContradictionRecord,
)
from aegis.synthetic.contradiction import ContradictionAnalysis
from aegis.synthetic.hypothesis import AttributionHypothesis


class HypothesisPersistenceService:
    """Persist attribution hypotheses and contradiction evidence."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def persist(
        self,
        hypothesis: AttributionHypothesis,
        contradiction: ContradictionAnalysis,
    ) -> UUID:
        record = AttributionHypothesisRecord(
            hypothesis_id=UUID(hypothesis.hypothesis_id.removeprefix("hypothesis:"))
            if self._is_uuid(hypothesis.hypothesis_id.removeprefix("hypothesis:"))
            else uuid4(),
            source_actor_id=hypothesis.source_actor_id,
            target_actor_id=hypothesis.target_actor_id,
            raw_score=hypothesis.raw_score,
            support_score=hypothesis.support_score,
            contradiction_score=hypothesis.contradiction_score,
            final_score=hypothesis.final_score,
            status=hypothesis.status,
            evidence_json=[
                {
                    "evidence_id": item.evidence_id,
                    "evidence_type": item.evidence_type,
                    "independence_group": item.independence_group,
                    "confidence": item.confidence,
                    "role": item.role,
                }
                for item in hypothesis.evidence
            ],
            explanations_json=list(hypothesis.explanations),
        )

        self.db.add(record)

        for item in contradiction.contradictions:
            self.db.add(
                HypothesisContradictionRecord(
                    hypothesis_id=record.hypothesis_id,
                    evidence_id=item.evidence_id,
                    contradiction_type=item.contradiction_type,
                    severity=item.severity,
                    explanation=item.explanation,
                )
            )

        self.db.commit()
        self.db.refresh(record)

        return record.hypothesis_id

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            UUID(value)
        except ValueError:
            return False
        return True
