from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from aegis.db.models import (
    AttributionHypothesisRecord,
    HypothesisContradictionRecord,
)
from aegis.synthetic.contradiction import ContradictionAnalysis
from aegis.synthetic.hypothesis import AttributionHypothesis


class HypothesisPersistenceService:
    """Persist attribution hypotheses and contradiction evidence.

    ``persist()`` is **flush-only**: it emits the INSERTs (so constraint
    violations and idempotency surface immediately) but never commits,
    letting the caller wrap N hypotheses in a single commit round-trip —
    see ``aegis.api.analysis.run_synthetic_analysis``, which commits once
    at the end and rolls back on failure. The returned hypothesis id is
    assigned client-side, so it is identical whether or not the row has
    been committed yet.
    """

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

        # Flush, never commit: the caller owns the transaction. No refresh
        # either — every column read downstream is set client-side above
        # (created_at is server-defaulted and materializes on the caller's
        # commit when the row expires).
        self.db.flush()

        return record.hypothesis_id

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            UUID(value)
        except ValueError:
            return False
        return True
