"""Live intelligence APIs for the analyst console.

The websocket is intentionally read-only: it streams derived operational state
from PostgreSQL and never accepts commands from untrusted client content.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import InstrumentedAttribute, Session
from starlette import status

from aegis.api.auth import validate_access_token
from aegis.api.dashboard_analytics import (
    attribution_posture,
    command_posture,
    evidence_velocity,
    investigation_pressure,
    queue_entry,
)
from aegis.api.deps import get_db
from aegis.db.models import (
    AssessmentRecord,
    AuditLogRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    RelationshipRecord,
)
from aegis.schemas.analytics import (
    ActivityEvent,
    CaseQueueEntry,
    DashboardSnapshot,
    PlatformCounts,
)
from aegis.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

_TERMINAL_STATUSES = ("closed", "archived")


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


def _activity(db: Session, case_id: UUID | None = None, limit: int = 24) -> list[ActivityEvent]:
    query = select(AuditLogRecord).order_by(AuditLogRecord.seq.desc()).limit(limit)
    if case_id is not None:
        query = query.where(AuditLogRecord.case_id == case_id)
    rows = db.scalars(query).all()
    names = _case_names(db, {row.case_id for row in rows if row.case_id is not None})
    return [
        ActivityEvent(
            seq=row.seq,
            occurred_at=row.occurred_at,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            case_id=row.case_id,
            payload={
                **(row.payload_json or {}),
                "case_name": names.get(row.case_id) if row.case_id else None,
            },
        )
        for row in rows
    ]


def _case_names(db: Session, case_ids: set[UUID]) -> dict[UUID, str]:
    """Resolve case ids to names once, so an event list can be rendered as
    sentences rather than as a column of UUIDs."""
    if not case_ids:
        return {}
    rows = db.execute(
        select(CaseRecord.case_id, CaseRecord.name).where(CaseRecord.case_id.in_(case_ids))
    ).all()
    return {case_id: name for case_id, name in rows}


def _lead_confidence(db: Session, case_ids: list[UUID]) -> dict[UUID, float]:
    """Highest calibrated confidence per case.

    Ordered in SQL and reduced with ``setdefault`` so the first row per case
    is the best one, rather than whichever row the planner happened to return
    first.
    """
    if not case_ids:
        return {}
    rows = db.execute(
        select(AssessmentRecord.case_id, AssessmentRecord.calibrated_confidence)
        .where(
            AssessmentRecord.case_id.in_(case_ids),
            AssessmentRecord.calibrated_confidence.is_not(None),
        )
        .order_by(
            AssessmentRecord.case_id,
            AssessmentRecord.calibrated_confidence.desc(),
        )
    ).all()
    lead: dict[UUID, float] = {}
    for case_id, confidence in rows:
        if confidence is None:  # excluded in SQL; mypy cannot see that
            continue
        lead.setdefault(case_id, float(confidence))
    return lead


def dashboard_cases(db: Session) -> list[CaseQueueEntry]:
    """Per-case rollup for the investigations register and the priority queue.

    All child counts, the last-activity stamp and the leading attribution
    figure are resolved with grouped aggregates in a constant number of round
    trips. A previous implementation issued five queries *per case* in a Python
    loop — an N+1 that grew linearly with the number of investigations.
    """
    cases = db.scalars(select(CaseRecord).order_by(CaseRecord.created_at.desc())).all()
    if not cases:
        return []
    case_ids = [case.case_id for case in cases]

    def grouped(column: InstrumentedAttribute[UUID | None]) -> dict[UUID, int]:
        """Count rows per case with one grouped query.

        ``case_id`` is nullable on evidence and entities, so a NULL group can
        come back; it is dropped rather than filed under a placeholder key that
        no case row will ever match.
        """
        rows = db.execute(
            select(column, func.count()).where(column.in_(case_ids)).group_by(column)
        ).all()
        return {key: int(total) for key, total in rows if key is not None}

    evidence_counts = grouped(EvidenceRecord.case_id)
    entity_counts = grouped(EntityRecord.case_id)
    relationship_counts = grouped(RelationshipRecord.case_id)
    assessment_counts = grouped(AssessmentRecord.case_id)

    # Newest audit row per case, in one query.
    #
    # A `row_number()` window rather than `DISTINCT ON`: the Postgres-specific
    # form is dialect-bound and its SQLAlchemy spelling differs between
    # versions, while this reads the same everywhere and cannot silently
    # return two rows for one case if the ordering is ever wrong.
    ranked = (
        select(
            AuditLogRecord.case_id.label("case_id"),
            AuditLogRecord.occurred_at.label("occurred_at"),
            func.row_number()
            .over(
                partition_by=AuditLogRecord.case_id,
                order_by=AuditLogRecord.seq.desc(),
            )
            .label("rank"),
        )
        .where(AuditLogRecord.case_id.in_(case_ids))
        .subquery()
    )
    last_activity: dict[UUID, datetime] = {
        cast("UUID", case_id): cast("datetime", occurred_at)
        for case_id, occurred_at in db.execute(
            select(ranked.c.case_id, ranked.c.occurred_at).where(ranked.c.rank == 1)
        ).all()
        if case_id is not None
    }
    # Contradictions per case drive the queue's "why prioritised" list, so they
    # are counted here rather than recomputed per case.
    contradiction_rows = db.execute(
        select(
            AssessmentRecord.case_id,
            func.coalesce(
                func.sum(func.jsonb_array_length(AssessmentRecord.contradictory_evidence_ids)),
                0,
            ),
        )
        .where(
            AssessmentRecord.case_id.in_(case_ids),
            AssessmentRecord.contradictory_evidence_ids != [],
        )
        .group_by(AssessmentRecord.case_id)
    ).all()
    contradiction_counts: dict[UUID, int] = {}
    for case_id, total in contradiction_rows:
        # The grouping key is ``assessments.case_id``, which is NOT NULL, so a
        # NULL key here would mean the query changed rather than a real row.
        key = cast("UUID", case_id)
        contradiction_counts[key] = contradiction_counts.get(key, 0) + int(cast("int", total))

    week_ago = datetime.now(UTC) - timedelta(days=7)
    recent_rows = db.execute(
        select(EvidenceRecord.case_id, func.count())
        .where(EvidenceRecord.case_id.in_(case_ids), EvidenceRecord.collected_at >= week_ago)
        .group_by(EvidenceRecord.case_id)
    ).all()
    recent_evidence = {key: int(total) for key, total in recent_rows if key is not None}

    attribution = _lead_confidence(db, case_ids)
    now = datetime.now(UTC)

    entries: list[CaseQueueEntry] = []
    for case in cases:
        counts = {
            "evidence": evidence_counts.get(case.case_id, 0),
            "entities": entity_counts.get(case.case_id, 0),
            "relationships": relationship_counts.get(case.case_id, 0),
            "assessments": assessment_counts.get(case.case_id, 0),
            "contradictions": contradiction_counts.get(case.case_id, 0),
            "recent_evidence": recent_evidence.get(case.case_id, 0),
        }
        entries.append(
            queue_entry(
                case,
                counts,
                last_activity=last_activity.get(case.case_id),
                attribution=attribution.get(case.case_id),
                now=now,
            )
        )
    return entries


def build_snapshot(db: Session) -> DashboardSnapshot:
    """The whole Command Center as one typed frame.

    This is the single source for both ``GET /dashboard/summary`` and every
    websocket snapshot, so the console renders identically whether or not the
    live socket is up. The REST path and the socket path cannot drift.
    """
    summaries = dashboard_cases(db)
    pressure = investigation_pressure(db)
    critical = int(
        db.scalar(
            select(func.count())
            .select_from(AuditLogRecord)
            .where(AuditLogRecord.action.in_(["alert.critical", "threat.critical"]))
        )
        or 0
    )
    return DashboardSnapshot(
        type="snapshot",
        server_time=datetime.now(UTC),
        counts=_counts(db),
        critical_alerts=critical,
        activity=_activity(db),
        case_summaries=summaries,
        command_posture=command_posture(db, summaries, pressure),
        evidence_velocity=evidence_velocity(db),
        investigation_pressure=pressure,
        attribution_posture=attribution_posture(db),
    )


@router.get("/api/v1/dashboard/summary", response_model=DashboardSnapshot)
def dashboard_summary(db: Annotated[Session, Depends(get_db)]) -> DashboardSnapshot:
    return build_snapshot(db)


@router.get("/api/v1/dashboard/cases", response_model=list[CaseQueueEntry])
def dashboard_cases_route(db: Annotated[Session, Depends(get_db)]) -> list[CaseQueueEntry]:
    return dashboard_cases(db)


@router.get("/api/v1/dashboard/activity", response_model=list[ActivityEvent])
def dashboard_activity(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 40,
) -> list[ActivityEvent]:
    return _activity(db, limit=limit)


@router.get("/api/v1/threat-watch/events", response_model=list[ActivityEvent])
def threat_watch_events(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> list[ActivityEvent]:
    """Operational event stream for Threat Watch (audit-backed, read-only)."""
    return _activity(db, limit=limit)


@router.get("/api/v1/cases/{case_id}/activity", response_model=list[ActivityEvent])
def case_activity(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityEvent]:
    return _activity(db, case_id=case_id, limit=limit)


#: Subprotocol a conforming client offers as ``["aegis", <credential>]``. The
#: credential travels in the handshake — headers are not written to access
#: logs, query strings are — so a token never lands in a log or a history
#: entry.
_LIVE_SUBPROTOCOL = "aegis"

#: How often the audit tail is polled. The socket carries derived state only,
#: so a slow poll is cheaper than a LISTEN/NOTIFY channel every reconnecting
#: browser would have to be tracked against.
_LIVE_POLL_SECONDS = 2.0


def _live_credential(websocket: WebSocket) -> str | None:
    """Resolve the caller's credential from the subprotocol or query string.

    Returns ``None`` when none was offered, which the caller treats exactly
    like an invalid one.
    """
    offered = [
        item.strip()
        for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if item.strip()
    ]
    if len(offered) >= 2 and offered[0] == _LIVE_SUBPROTOCOL:
        return offered[1]
    return websocket.query_params.get("access_token")


@router.websocket("/api/v1/live")
async def live_socket(websocket: WebSocket) -> None:
    """Push derived operational state to the analyst console.

    The socket is read-only. Client frames are drained only so a disconnect is
    observed promptly; their content is never interpreted as a command.
    """
    credential = _live_credential(websocket)
    api_ok = bool(
        settings.enable_api_key_auth
        and settings.api_key
        and credential
        and credential == settings.api_key
    )
    session_ok = bool(credential and validate_access_token(credential) is not None)
    if not api_ok and not session_ok:
        # Close before accept: the handshake is refused, so the browser never
        # observes an open socket that is about to be torn down.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # RFC 6455 §4.1: a server must only select a subprotocol the client offered.
    offered = {
        item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
    }
    await websocket.accept(subprotocol=_LIVE_SUBPROTOCOL if _LIVE_SUBPROTOCOL in offered else None)

    last_seq = -1
    try:
        while True:
            db = next(get_db())
            try:
                latest_seq = int(db.scalar(select(func.max(AuditLogRecord.seq))) or 0)
                if latest_seq != last_seq:
                    await websocket.send_json(build_snapshot(db).model_dump(mode="json"))
                    last_seq = latest_seq
                else:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "server_time": datetime.now(UTC).isoformat(),
                        }
                    )
            except SQLAlchemyError:
                # A transient database fault must not silently kill the feed.
                # Report it as a frame so the client shows the degradation
                # instead of reconnecting in a tight loop.
                logger.exception("Live snapshot failed")
                await websocket.send_json(
                    {
                        "type": "degraded",
                        "server_time": datetime.now(UTC).isoformat(),
                        "detail": "Live snapshot unavailable",
                    }
                )
            finally:
                db.close()

            # Sleep while still reading, so a client that goes away is noticed
            # on the next poll rather than whenever the next write fails.
            try:
                async with asyncio.timeout(_LIVE_POLL_SECONDS):
                    message = await websocket.receive()
            except TimeoutError:
                continue
            if message["type"] == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return
    except (SQLAlchemyError, OSError):
        logger.exception("Live socket terminated")
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
