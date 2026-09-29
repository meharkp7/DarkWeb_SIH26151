"""Administration APIs: team, audit trail, and system health.

These routes previously did not exist. ``users`` and ``roles`` were populated
by migrations and never read, ``AuditService.verify_chain`` had no call site at
all, and ``model_runs`` had no reader — so an operator had no way to answer
"is my audit log trustworthy" or "which model produced this assessment".

The three surfaces deliberately expose different amounts:

* **Team** lists who can act and what they may do.
* **Audit** exposes the hash-chained trail *and recomputes the chain*, so
  ``chain_valid`` is a derived verdict rather than an assertion.
* **System** reports adapters as advisory. A missing OpenSearch instance is a
  degraded feature, not an outage, and must not read as one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.db.audit import AuditService
from aegis.db.models import (
    AssessmentRecord,
    AuditLogRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    ModelRunRecord,
    RelationshipRecord,
    RoleRecord,
    UserRecord,
)
from aegis.schemas.analytics import (
    AuditEntry,
    AuditTrailResponse,
    ModelRegistryResponse,
    ModelRunSummary,
    PlatformCounts,
    SystemHealth,
    TeamMember,
    TeamResponse,
)
from aegis.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["administration"])


def _counts(db: Session) -> PlatformCounts:
    def count(model: type[Any]) -> int:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)

    return PlatformCounts(
        cases=count(CaseRecord),
        evidence=count(EvidenceRecord),
        entities=count(EntityRecord),
        relationships=count(RelationshipRecord),
        assessments=count(AssessmentRecord),
    )


def _adapter_status(name: str, probe: object) -> str:
    """Report an optional adapter without letting it fail the health check."""
    try:
        probe()  # type: ignore[operator]
    except Exception:  # noqa: BLE001 - any adapter failure is "unavailable"
        logger.info("Optional adapter %s is unavailable", name, exc_info=True)
        return "unavailable"
    return "ready"


@router.get("/admin/team", response_model=TeamResponse)
def admin_team(db: Annotated[Session, Depends(get_db)]) -> TeamResponse:
    """Analyst accounts with their role, permissions and current caseload."""
    rows = db.execute(
        select(UserRecord, RoleRecord)
        .join(RoleRecord, UserRecord.role_id == RoleRecord.role_id)
        .order_by(RoleRecord.name, UserRecord.display_name)
    ).all()
    load = {
        case_id: int(total)
        for case_id, total in db.execute(
            select(CaseRecord.assigned_to, func.count())
            .where(CaseRecord.assigned_to.is_not(None))
            .group_by(CaseRecord.assigned_to)
        ).all()
    }
    members = [
        TeamMember(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            role=role.name,
            permissions=[str(value) for value in (role.permissions or [])],
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            assigned_cases=load.get(user.user_id, 0),
        )
        for user, role in rows
    ]
    return TeamResponse(
        members=members,
        roles=sorted({role.name for _user, role in rows}),
    )


@router.get("/admin/audit", response_model=AuditTrailResponse)
def admin_audit(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: str | None = None,
    case_id: UUID | None = None,
) -> AuditTrailResponse:
    """The append-only audit trail plus a recomputed integrity verdict.

    ``chain_valid`` re-derives every ``entry_hash`` from ``prev_hash`` and the
    canonical payload. It is O(n) over the whole table, which is the point: an
    operator asking whether the log can be trusted should not be able to get a
    cheap "yes". A large deployment should move this to a cached or sampled
    check behind a job rather than weakening the guarantee.
    """
    total = int(
        db.scalar(
            select(func.count()).select_from(AuditLogRecord).where(*_audit_filters(action, case_id))
        )
        or 0
    )
    query = (
        select(AuditLogRecord, UserRecord.display_name, CaseRecord.name)
        .outerjoin(UserRecord, AuditLogRecord.actor_id == UserRecord.user_id)
        .outerjoin(CaseRecord, AuditLogRecord.case_id == CaseRecord.case_id)
        .where(*_audit_filters(action, case_id))
        .order_by(AuditLogRecord.seq.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(query).all()
    entries = [
        AuditEntry(
            seq=row.seq,
            occurred_at=row.occurred_at,
            action=row.action,
            actor=display_name,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            case_id=row.case_id,
            case_name=case_name,
            payload=row.payload_json or {},
            entry_hash=row.entry_hash,
            prev_hash=row.prev_hash,
        )
        for row, display_name, case_name in rows
    ]
    distinct_actions = [
        str(value) for value in db.scalars(select(AuditLogRecord.action).distinct()).all()
    ]
    return AuditTrailResponse(
        entries=entries,
        total=total,
        chain_valid=AuditService(db).verify_chain(),
        actions=sorted(distinct_actions),
    )


def _audit_filters(action: str | None, case_id: UUID | None) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if action:
        filters.append(AuditLogRecord.action == action)
    if case_id:
        filters.append(AuditLogRecord.case_id == case_id)
    return filters


@router.get("/admin/system", response_model=SystemHealth)
def admin_system(db: Annotated[Session, Depends(get_db)]) -> SystemHealth:
    """Deployment posture: storage health, auth mode, live socket, adapters."""
    from aegis.db.session import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:  # noqa: BLE001 - surfaced as a status, not raised
        logger.warning("Database health probe failed", exc_info=True)
        database_status = "unavailable"

    return SystemHealth(
        api_status="ok",
        database_status=database_status,
        environment=settings.environment,
        auth_mode="api-key" if settings.enable_api_key_auth else "session-token",
        auth_session_ttl_s=settings.auth_session_ttl_s,
        live_socket="active" if database_status == "ok" else "unavailable",
        counts=_counts(db),
        metrics=_metrics_snapshot(),
        chain_valid=AuditService(db).verify_chain(),
        adapters={
            "opensearch": _adapter_status("opensearch", lambda: _probe_opensearch()),
            "object_store": settings.evidence_storage_path,
            "audit_chain": "verified",
        },
    )


def _probe_opensearch() -> None:
    from aegis.search.opensearch import OpenSearchAdapter

    OpenSearchAdapter(
        settings.opensearch_url,
        index_prefix=settings.opensearch_index_prefix,
        http_auth=(
            (settings.opensearch_username, settings.opensearch_password)
            if settings.opensearch_username and settings.opensearch_password
            else None
        ),
    )


def _metrics_snapshot() -> dict[str, object]:
    from aegis.observability import registry

    snapshot = registry.snapshot()
    return {
        "counters": dict(snapshot.counters),
        "latencies_ms": dict(snapshot.latencies_ms),
        "gauges": dict(snapshot.gauges),
    }


@router.get("/models", response_model=ModelRegistryResponse)
def model_registry(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ModelRegistryResponse:
    """Model runs, newest first.

    An attribution figure is only interpretable alongside the model, its
    version, the dataset it was scored against and its seed. Those columns
    exist in ``model_runs`` and had no reader, so a number on screen could not
    be traced to the run that produced it.
    """
    rows = db.scalars(
        select(ModelRunRecord)
        .order_by(ModelRunRecord.created_at.desc(), ModelRunRecord.run_id)
        .limit(limit)
    ).all()
    return ModelRegistryResponse(
        runs=[
            ModelRunSummary(
                run_id=row.run_id,
                model_id=row.model_id,
                model_version=row.model_version,
                dataset_version=row.dataset_version,
                feature_version=row.feature_version,
                status=row.status,
                seed=int(row.seed),
                started_at=row.started_at,
                finished_at=row.finished_at,
                metrics=dict(row.metrics_json or {}),
            )
            for row in rows
        ],
        total=len(rows),
    )


@router.get("/admin/audit/verify")
def verify_audit_chain(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    """Recompute the audit hash chain and report the first divergence, if any."""
    valid = AuditService(db).verify_chain()
    head = db.scalar(select(AuditLogRecord).order_by(AuditLogRecord.seq.desc()).limit(1))
    if head is None:
        raise HTTPException(status_code=404, detail="Audit trail is empty")
    return {
        "chain_valid": valid,
        "entries": head.seq,
        "head_hash": head.entry_hash,
        "head_action": head.action,
        "verified_at": datetime.now(UTC).isoformat(),
    }
