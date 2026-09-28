"""Case-workspace read APIs for the investigation UI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.db.models import (
    AssessmentRecord,
    AttributionHypothesisRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    RelationshipRecord,
)

router = APIRouter(prefix="/api/v1/cases", tags=["workspace"])


def _case_or_404(db: Session, case_id: UUID) -> CaseRecord:
    case = db.get(CaseRecord, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/{case_id}/workspace")
def workspace(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    case = _case_or_404(db, case_id)
    evidence = db.scalars(select(EvidenceRecord).where(EvidenceRecord.case_id == case_id)).all()
    entities = db.scalars(select(EntityRecord).where(EntityRecord.case_id == case_id)).all()
    relationships = db.scalars(
        select(RelationshipRecord).where(RelationshipRecord.case_id == case_id)
    ).all()
    assessments = db.scalars(
        select(AssessmentRecord).where(AssessmentRecord.case_id == case_id)
    ).all()
    return {
        "case": {
            "case_id": str(case.case_id),
            "name": case.name,
            "description": case.description,
            "status": case.status,
        },
        "counts": {
            "evidence": len(evidence),
            "entities": len(entities),
            "relationships": len(relationships),
            "assessments": len(assessments),
        },
        "evidence": [
            {
                "evidence_id": str(row.evidence_id),
                "source_id": str(row.source_id),
                "source_type": row.source_type,
                "collected_at": row.collected_at.isoformat(),
                "reliability": row.source_reliability,
                "sha256": row.sha256,
            }
            for row in sorted(evidence, key=lambda item: item.collected_at)
        ],
        "entities": [
            {
                "entity_id": str(row.entity_id),
                "type": row.entity_type,
                "surface_form": row.surface_form,
                "normalized_form": row.normalized_form,
                "confidence": row.confidence,
            }
            for row in entities
        ],
        "relationships": [
            {
                "relationship_id": str(row.relationship_id),
                "subject_entity_id": str(row.subject_entity_id),
                "object_entity_id": str(row.object_entity_id),
                "type": row.relationship_type,
                "confidence": row.confidence,
                "first_seen": row.first_seen.isoformat(),
                "last_seen": row.last_seen.isoformat(),
                "evidence_ids": [str(value) for value in row.evidence_ids],
            }
            for row in relationships
        ],
        "assessments": [
            {
                "assessment_id": str(row.assessment_id),
                "hypothesis_id": str(row.hypothesis_id),
                "model_id": row.model_id,
                "model_version": row.model_version,
                "raw_score": row.raw_score,
                "calibrated_confidence": row.calibrated_confidence,
                "supporting_evidence_ids": [str(value) for value in row.supporting_evidence_ids],
                "contradictory_evidence_ids": [
                    str(value) for value in row.contradictory_evidence_ids
                ],
            }
            for row in assessments
        ],
    }


@router.get("/{case_id}/hypotheses")
def hypotheses(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> list[dict[str, object]]:
    _case_or_404(db, case_id)
    rows = db.scalars(
        select(AttributionHypothesisRecord).order_by(AttributionHypothesisRecord.created_at.desc())
    ).all()
    return [
        {
            "hypothesis_id": str(row.hypothesis_id),
            "source_actor_id": row.source_actor_id,
            "target_actor_id": row.target_actor_id,
            "raw_score": row.raw_score,
            "support_score": row.support_score,
            "contradiction_score": row.contradiction_score,
            "final_score": row.final_score,
            "status": row.status,
            "evidence": row.evidence_json,
            "explanations": row.explanations_json,
        }
        for row in rows
    ]


@router.get("/{case_id}/evidence")
def case_evidence(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[dict[str, object]]:
    _case_or_404(db, case_id)
    rows = db.scalars(
        select(EvidenceRecord)
        .where(EvidenceRecord.case_id == case_id)
        .order_by(EvidenceRecord.collected_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "evidence_id": str(row.evidence_id),
            "source_id": str(row.source_id),
            "source_type": row.source_type,
            "observed_at": row.observed_at.isoformat() if row.observed_at else None,
            "collected_at": row.collected_at.isoformat(),
            "entity_type": row.entity_type,
            "reliability": row.source_reliability,
            "independence_group": row.independence_group,
            "sha256": row.sha256,
            "metadata": row.metadata_json,
        }
        for row in rows
    ]
