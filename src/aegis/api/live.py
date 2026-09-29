"""Live intelligence APIs for the analyst console.

The websocket is intentionally read-only: it streams derived operational state
from PostgreSQL and never accepts commands from untrusted client content.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from aegis.api.case_triage import case_is_overdue
from aegis.api.deps import get_db
from aegis.db.models import (
    AssessmentRecord,
    AuditLogRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    RelationshipRecord,
)

router = APIRouter(tags=["live"])


def _counts(db: Session) -> dict[str, int]:
    def count(model: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)

    return {
        "cases": count(CaseRecord),
        "evidence": count(EvidenceRecord),
        "entities": count(EntityRecord),
        "relationships": count(RelationshipRecord),
        "assessments": count(AssessmentRecord),
    }


def _activity(db: Session, case_id: UUID | None = None, limit: int = 24) -> list[dict[str, object]]:
    query = select(AuditLogRecord).order_by(AuditLogRecord.seq.desc()).limit(limit)
    if case_id is not None:
        query = (
            select(AuditLogRecord)
            .where(AuditLogRecord.case_id == case_id)
            .order_by(AuditLogRecord.seq.desc())
            .limit(limit)
        )
    rows = db.scalars(query).all()
    return [
        {
            "seq": row.seq,
            "occurred_at": row.occurred_at.isoformat(),
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "case_id": str(row.case_id) if row.case_id else None,
            "payload": row.payload_json,
        }
        for row in rows
    ]


def _snapshot(db: Session) -> dict[str, object]:
    counts = _counts(db)
    critical = (
        db.scalar(
            select(func.count())
            .select_from(AuditLogRecord)
            .where(AuditLogRecord.action.in_(["alert.critical", "threat.critical"]))
        )
        or 0
    )
    return {
        "type": "snapshot",
        "server_time": datetime.now(UTC).isoformat(),
        "counts": counts,
        "critical_alerts": int(critical),
        "activity": _activity(db),
        "case_summaries": dashboard_cases(db),
    }


@router.get("/api/v1/dashboard/summary")
def dashboard_summary(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    return _snapshot(db)


@router.get("/api/v1/dashboard/cases")
def dashboard_cases(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, object]]:
    """Per-case rollup for the case list.

    All four child counts and the last-activity stamp are resolved with
    grouped aggregate queries in a constant number of round trips. The
    previous implementation issued five queries *per case* in a Python loop
    (an N+1 that grew linearly with the number of investigations), which the
    case-triage work made worse by adding more per-case fields.
    """
    cases = db.scalars(select(CaseRecord).order_by(CaseRecord.created_at.desc())).all()
    if not cases:
        return []

    case_ids = [case.case_id for case in cases]

    def grouped(column: InstrumentedAttribute[Any]) -> dict[UUID, int]:
        rows = db.execute(
            select(column, func.count()).where(column.in_(case_ids)).group_by(column)
        ).all()
        return {cast(UUID, key): int(cast(Any, total)) for key, total in rows}

    evidence_counts = grouped(EvidenceRecord.case_id)
    entity_counts = grouped(EntityRecord.case_id)
    relationship_counts = grouped(RelationshipRecord.case_id)
    assessment_counts = grouped(AssessmentRecord.case_id)

    # DISTINCT ON keeps the highest-seq audit row per case.
    last_activity = {
        cast(UUID, case_id): occurred_at
        for case_id, occurred_at in db.execute(
            select(AuditLogRecord.case_id, AuditLogRecord.occurred_at)
            .where(AuditLogRecord.case_id.in_(case_ids))
            .distinct(AuditLogRecord.case_id)
            .order_by(AuditLogRecord.case_id, AuditLogRecord.seq.desc())
        ).all()
    }

    now = datetime.now(UTC)
    result: list[dict[str, object]] = []
    for case in cases:
        result.append(
            {
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
                "sla_overdue": case_is_overdue(case, now=now),
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "updated_at": case.updated_at.isoformat() if case.updated_at else None,
                "counts": {
                    "evidence": evidence_counts.get(case.case_id, 0),
                    "entities": entity_counts.get(case.case_id, 0),
                    "relationships": relationship_counts.get(case.case_id, 0),
                    "assessments": assessment_counts.get(case.case_id, 0),
                },
                "last_activity": (
                    last_activity[case.case_id].isoformat()
                    if case.case_id in last_activity
                    else None
                ),
            }
        )
    return result


@router.get("/api/v1/dashboard/activity")
def dashboard_activity(
    db: Annotated[Session, Depends(get_db)], limit: int = 40
) -> list[dict[str, object]]:
    return _activity(db, limit=max(1, min(limit, 100)))


@router.get("/api/v1/cases/{case_id}/activity")
def case_activity(
    case_id: UUID, db: Annotated[Session, Depends(get_db)], limit: int = 50
) -> list[dict[str, object]]:
    return _activity(db, case_id=case_id, limit=max(1, min(limit, 100)))


@router.websocket("/api/v1/live")
async def live_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    last_seq = -1
    try:
        while True:
            db = next(get_db())
            try:
                latest_seq = int(db.scalar(select(func.max(AuditLogRecord.seq))) or 0)
                if latest_seq != last_seq:
                    await websocket.send_json(_snapshot(db))
                    last_seq = latest_seq
                else:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "server_time": datetime.now(UTC).isoformat(),
                        }
                    )
            finally:
                db.close()
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
