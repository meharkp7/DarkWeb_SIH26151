"""Durable persistence for canonical attribution assessments."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.db.audit import AuditService
from aegis.db.models import AssessmentRecord
from aegis.schemas.hypothesis import AttributionAssessment


class AttributionAssessmentPersistenceService:
    """Persist attribution assessments using the existing ``assessments`` table.

    ``persist`` is flush-only so callers control transaction boundaries.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def to_record(assessment: AttributionAssessment) -> AssessmentRecord:
        return AssessmentRecord(
            assessment_id=assessment.assessment_id,
            hypothesis_id=assessment.hypothesis_id,
            case_id=assessment.case_id,
            model_id=assessment.model_id,
            model_version=assessment.model_version,
            raw_score=assessment.raw_score,
            calibrated_confidence=assessment.calibrated_confidence,
            calibration_version=assessment.calibration_version,
            signals_json=dict(assessment.signals),
            supporting_evidence_ids=list(assessment.supporting_evidence_ids),
            contradictory_evidence_ids=list(assessment.contradictory_evidence_ids),
            explanations=list(assessment.explanations),
            limitations=list(assessment.limitations),
        )

    def persist(self, assessment: AttributionAssessment) -> UUID:
        record = self.to_record(assessment)
        self.db.add(record)
        self.db.flush()
        AuditService(self.db).record(
            "attribution.assessment.created",
            case_id=assessment.case_id,
            entity_type="assessment",
            entity_id=str(assessment.assessment_id),
            payload={
                "hypothesis_id": str(assessment.hypothesis_id),
                "model_id": assessment.model_id,
                "model_version": assessment.model_version,
                "raw_score": assessment.raw_score,
                "calibrated_confidence": assessment.calibrated_confidence,
                "supporting_evidence_count": len(assessment.supporting_evidence_ids),
                "contradictory_evidence_count": len(assessment.contradictory_evidence_ids),
            },
        )
        return assessment.assessment_id

    def get(self, assessment_id: UUID) -> AssessmentRecord | None:
        return self.db.get(AssessmentRecord, assessment_id)

    def list_for_hypothesis(self, hypothesis_id: UUID) -> Sequence[AssessmentRecord]:
        return self.db.scalars(
            select(AssessmentRecord)
            .where(AssessmentRecord.hypothesis_id == hypothesis_id)
            .order_by(AssessmentRecord.created_at.asc())
        ).all()
