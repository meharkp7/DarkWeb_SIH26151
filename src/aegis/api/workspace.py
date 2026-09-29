"""Case-workspace read APIs for the investigation UI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.api.case_triage import case_is_overdue
from aegis.api.deps import get_db
from aegis.db.audit import AuditService
from aegis.db.models import (
    AssessmentRecord,
    AuditLogRecord,
    CaseNoteRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    HypothesisRecord,
    RelationshipRecord,
)
from aegis.schemas.evidence import CaseNote, CaseNoteCreate

router = APIRouter(prefix="/api/v1/cases", tags=["workspace"])


def _case_or_404(db: Session, case_id: UUID) -> CaseRecord:
    case = db.get(CaseRecord, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def _note_schema(record: CaseNoteRecord) -> CaseNote:
    return CaseNote(
        note_id=record.note_id,
        case_id=record.case_id,
        author_id=record.author_id,
        body=record.body,
        created_at=record.created_at,
    )


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
    activity = db.scalars(
        select(AuditLogRecord)
        .where(AuditLogRecord.case_id == case_id)
        .order_by(AuditLogRecord.seq.desc())
        .limit(40)
    ).all()
    return {
        "case": {
            "case_id": str(case.case_id),
            "name": case.name,
            "description": case.description,
            "status": case.status,
            "priority": case.priority,
            "severity": case.severity,
            "tags": list(case.tags or []),
            "assigned_to": str(case.assigned_to) if case.assigned_to else None,
            "sla_due_at": case.sla_due_at.isoformat() if case.sla_due_at else None,
            "closed_at": case.closed_at.isoformat() if case.closed_at else None,
            "closure_reason": case.closure_reason,
            "sla_overdue": case_is_overdue(case),
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
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
                "signals": row.signals_json,
                "explanations": row.explanations,
                "limitations": row.limitations,
                "supporting_evidence_ids": [str(value) for value in row.supporting_evidence_ids],
                "contradictory_evidence_ids": [
                    str(value) for value in row.contradictory_evidence_ids
                ],
            }
            for row in assessments
        ],
        "activity": [
            {
                "seq": row.seq,
                "occurred_at": row.occurred_at.isoformat(),
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "payload": row.payload_json,
            }
            for row in activity
        ],
    }


@router.get("/{case_id}/hypotheses")
def hypotheses(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> list[dict[str, object]]:
    """Case-scoped hypotheses.

    Reads the canonical ``hypotheses`` table, which carries a ``case_id``
    foreign key. The legacy ``attribution_hypotheses`` table has no
    ``case_id`` column at all, so querying it here returned every
    hypothesis in the database to every case's workspace regardless of the
    path parameter — a cross-case disclosure.
    """
    _case_or_404(db, case_id)
    rows = db.execute(
        select(
            HypothesisRecord,
            AssessmentRecord.calibrated_confidence,
            AssessmentRecord.raw_score,
        )
        .outerjoin(
            AssessmentRecord,
            AssessmentRecord.hypothesis_id == HypothesisRecord.hypothesis_id,
        )
        .where(HypothesisRecord.case_id == case_id)
        .order_by(
            HypothesisRecord.created_at.desc(),
            AssessmentRecord.created_at.desc(),
        )
    ).all()

    seen: set[UUID] = set()
    result: list[dict[str, object]] = []
    for hypothesis, calibrated, raw in rows:
        # A hypothesis may carry several assessments (one per model run);
        # surface the hypothesis once, keeping the most recent run.
        if hypothesis.hypothesis_id in seen:
            continue
        seen.add(hypothesis.hypothesis_id)
        result.append(
            {
                "hypothesis_id": str(hypothesis.hypothesis_id),
                "kind": hypothesis.kind,
                "status": hypothesis.status,
                "subject_entity_id": str(hypothesis.subject_entity_id),
                "object_entity_id": str(hypothesis.object_entity_id),
                "missing_evidence": list(hypothesis.missing_evidence or []),
                "analyst_disposition": hypothesis.analyst_disposition,
                "calibrated_confidence": calibrated,
                "raw_score": raw,
                "created_at": (
                    hypothesis.created_at.isoformat() if hypothesis.created_at else None
                ),
                "updated_at": (
                    hypothesis.updated_at.isoformat() if hypothesis.updated_at else None
                ),
            }
        )
    return result


@router.get("/{case_id}/notes", response_model=list[CaseNote])
def list_case_notes(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[CaseNote]:
    """Investigative notes, newest first.

    Analyst-authored working commentary, distinct from the immutable
    ``audit_logs`` trail surfaced by ``GET /{case_id}/activity``.
    """
    _case_or_404(db, case_id)
    rows = db.scalars(
        select(CaseNoteRecord)
        .where(CaseNoteRecord.case_id == case_id)
        .order_by(CaseNoteRecord.created_at.desc(), CaseNoteRecord.note_id.desc())
        .limit(limit)
    ).all()
    return [_note_schema(row) for row in rows]


@router.post(
    "/{case_id}/notes",
    response_model=CaseNote,
    status_code=status.HTTP_201_CREATED,
)
def create_case_note(
    case_id: UUID,
    payload: CaseNoteCreate,
    db: Annotated[Session, Depends(get_db)],
) -> CaseNote:
    _case_or_404(db, case_id)
    record = CaseNoteRecord(
        case_id=case_id,
        author_id=payload.author_id,
        body=payload.body.strip(),
    )
    db.add(record)
    db.flush()
    AuditService(db).record(
        "case.note_added",
        case_id=case_id,
        entity_type="case_note",
        entity_id=str(record.note_id),
        payload={"note_id": str(record.note_id), "characters": len(record.body)},
    )
    db.commit()
    db.refresh(record)
    return _note_schema(record)


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
