"""Persona linkage API — linking a candidate handle to a known actor.

The surface exists because stylometry and behavioural profiling could already be
computed (:mod:`aegis.stylometry`, :mod:`aegis.behavior`) and nothing could act on
them. It has one rule above all others:

    **the model's score and an analyst's decision are different things, and this
    API never lets one stand in for the other.**

A proposal's score is computed here, from the supplied samples, by
:mod:`aegis.api.persona_scoring` — a caller cannot supply one
(``PersonaLinkageProposal`` forbids extra fields, so a body carrying ``score`` is
a 422 rather than a silently-ignored key). A status is only ever written by
:func:`adjudicate_linkage`, which requires the deciding analyst and a rationale,
and which appends to the audit trail. ``proposed`` rows are hypotheses;
``confirmed`` is the only status a consumer may present as a finding, which is
why :class:`~aegis.schemas.personas.PersonaLinkage.analyst_recorded` exists.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.api.persona_scoring import (
    MethodNotScorable,
    SampleTooShort,
    score_sample,
)
from aegis.db.audit import AuditService
from aegis.db.models import (
    ActorRecord,
    CaseRecord,
    PersonaLinkageRecord,
    UserRecord,
)
from aegis.schemas.personas import (
    PERSONA_LINKAGE_METHODS,
    PERSONA_LINKAGE_STATUSES,
    AdjudicationRequest,
    AdjudicationResponse,
    PersonaExport,
    PersonaLinkage,
    PersonaLinkageDetail,
    PersonaLinkageProposal,
    PersonaLinkageSummary,
)

router = APIRouter(prefix="/api/v1/personas", tags=["personas"])

#: The line a score is measured against when it is compared with an analyst's
#: ruling. Returned in the summary so the UI can label the comparison instead of
#: implying a threshold, and matching the score band the console already draws.
SCORE_THRESHOLD = 0.75


# --------------------------------------------------------------------------
# Row resolution
# --------------------------------------------------------------------------


def _handles(db: Session, actor_ids: set[UUID]) -> dict[UUID, str]:
    if not actor_ids:
        return {}
    return {
        row.actor_id: row.handle
        for row in db.scalars(select(ActorRecord).where(ActorRecord.actor_id.in_(actor_ids))).all()
    }


def _case_names(db: Session, case_ids: set[UUID]) -> dict[UUID, str]:
    if not case_ids:
        return {}
    return {
        row.case_id: row.name
        for row in db.scalars(select(CaseRecord).where(CaseRecord.case_id.in_(case_ids))).all()
    }


def _user_names(db: Session, user_ids: set[UUID]) -> dict[UUID, str]:
    if not user_ids:
        return {}
    return {
        row.user_id: row.display_name
        for row in db.scalars(select(UserRecord).where(UserRecord.user_id.in_(user_ids))).all()
    }


def _row_schema(
    record: PersonaLinkageRecord,
    *,
    handles: dict[UUID, str],
    cases: dict[UUID, str],
    users: dict[UUID, str],
) -> PersonaLinkage:
    return PersonaLinkage(
        linkage_id=record.linkage_id,
        actor_id=record.actor_id,
        actor_handle=handles.get(record.actor_id, "unknown actor"),
        candidate_handle=record.candidate_handle,
        method=record.method,
        score=record.score,
        status=record.status,
        aligned_features=list(record.aligned_features or []),
        apart_features=list(record.apart_features or []),
        contested_features=list(record.contested_features or []),
        limitations=list(record.limitations or []),
        case_id=record.case_id,
        case_name=(cases.get(record.case_id) if record.case_id else None),
        adjudicated_by=record.adjudicated_by,
        adjudicated_by_name=(
            users.get(record.adjudicated_by) if record.adjudicated_by else None
        ),
        adjudicated_at=record.adjudicated_at,
        rationale=record.rationale,
        created_at=record.created_at,
        metadata=dict(record.metadata_json or {}),
        # True only once a human ruled. This is the flag the register uses to
        # stop calling a score a finding, so it is derived from the presence of
        # an adjudicator rather than from the status string alone.
        analyst_recorded=record.adjudicated_by is not None
        and record.adjudicated_at is not None,
    )


def _schema_many(
    db: Session, records: Sequence[PersonaLinkageRecord]
) -> list[PersonaLinkage]:
    handles = _handles(db, {row.actor_id for row in records})
    cases = _case_names(db, {row.case_id for row in records if row.case_id is not None})
    users = _user_names(
        db, {row.adjudicated_by for row in records if row.adjudicated_by is not None}
    )
    return [
        _row_schema(row, handles=handles, cases=cases, users=users) for row in records
    ]


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------


def _filtered(
    db: Session,
    *,
    status_filter: str | None,
    method: str | None,
    actor_id: UUID | None,
    min_score: float | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> list[PersonaLinkageRecord]:
    """The linkage register under *filters*, newest proposal first.

    ``since``/``until`` bound ``created_at`` — when the proposal was raised —
    rather than ``adjudicated_at``. A proposal raised in March and ruled on in
    June belongs to the March timeline, and an analyst filtering a window wants
    to know what was being proposed then.
    """
    query = select(PersonaLinkageRecord)
    if status_filter is not None:
        query = query.where(PersonaLinkageRecord.status == status_filter)
    if method is not None:
        query = query.where(PersonaLinkageRecord.method == method)
    if actor_id is not None:
        query = query.where(PersonaLinkageRecord.actor_id == actor_id)
    if min_score is not None:
        query = query.where(PersonaLinkageRecord.score >= min_score)
    if since is not None:
        query = query.where(PersonaLinkageRecord.created_at >= since)
    if until is not None:
        query = query.where(PersonaLinkageRecord.created_at <= until)
    return list(
        db.scalars(
            query.order_by(
                PersonaLinkageRecord.created_at.desc(), PersonaLinkageRecord.linkage_id.desc()
            ).limit(limit)
        ).all()
    )


def _summarize(records: Sequence[PersonaLinkageRecord]) -> PersonaLinkageSummary:
    """Counts, and the model's observed error rate as analysts saw it.

    ``confirmed_low_score`` and ``rejected_high_score`` are the two numbers worth
    reading on this surface. A linkage the scorer ranked at or above
    :data:`SCORE_THRESHOLD` that an analyst threw out is a false positive the
    platform actually produced; one the scorer ranked below that line that an
    analyst accepted is a false negative. Both are counted from the rows, never
    from anything the scorer reports about itself.
    """
    by_status = {name: 0 for name in PERSONA_LINKAGE_STATUSES}
    by_method = {name: 0 for name in PERSONA_LINKAGE_METHODS}
    confirmed_low = 0
    rejected_high = 0
    for row in records:
        by_status[row.status] = by_status.get(row.status, 0) + 1
        by_method[row.method] = by_method.get(row.method, 0) + 1
        if row.status == "confirmed" and row.score < SCORE_THRESHOLD:
            confirmed_low += 1
        if row.status == "rejected" and row.score >= SCORE_THRESHOLD:
            rejected_high += 1

    confirmed = by_status.get("confirmed", 0)
    rejected = by_status.get("rejected", 0)
    return PersonaLinkageSummary(
        total=len(records),
        by_status=by_status,
        by_method=by_method,
        proposed=by_status.get("proposed", 0),
        confirmed=confirmed,
        rejected=rejected,
        adjudicated=confirmed + rejected,
        confirmed_total=confirmed,
        rejected_total=rejected,
        confirmed_low_score=confirmed_low,
        rejected_high_score=rejected_high,
        score_threshold=SCORE_THRESHOLD,
        gap=(
            None
            if confirmed + rejected > 0
            else "No linkage in this view has been adjudicated yet, so there is no "
            "observed error rate to report. A scorer that has never been overruled "
            "has not been tested."
        ),
    )


class _Filters:
    """The filter set, resolved once and reusable by the list and export."""

    def __init__(
        self,
        status_filter: str | None,
        method: str | None,
        actor_id: UUID | None,
        min_score: float | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> None:
        self.status = status_filter
        self.method = method
        self.actor_id = actor_id
        self.min_score = min_score
        self.since = since
        self.until = until
        self.limit = limit

    def described(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "method": self.method,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "min_score": self.min_score,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "limit": self.limit,
        }

    def query(self, db: Session) -> list[PersonaLinkageRecord]:
        return _filtered(
            db,
            status_filter=self.status,
            method=self.method,
            actor_id=self.actor_id,
            min_score=self.min_score,
            since=self.since,
            until=self.until,
            limit=self.limit,
        )


def _filters(
    # `status` is the column name; the parameter is `status_filter` so it does
    # not shadow the imported `fastapi.status` module, which the handlers need.
    # The alias keeps the wire name the caller expects.
    status_filter: Annotated[
        str | None, Query(alias="status", pattern="^(proposed|confirmed|rejected)$")
    ] = None,
    method: Annotated[
        str | None, Query(pattern="^(stylometry|behavioural|infrastructure|attribution|manual)$")
    ] = None,
    actor_id: UUID | None = None,
    min_score: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> _Filters:
    return _Filters(status_filter, method, actor_id, min_score, since, until, limit)


# --------------------------------------------------------------------------
# Read routes
# --------------------------------------------------------------------------


@router.get("/linkages", response_model=list[PersonaLinkage])
def list_linkages(
    db: Annotated[Session, Depends(get_db)],
    filters: Annotated[_Filters, Depends(_filters)],
) -> list[PersonaLinkage]:
    """The linkage register, with the three feature lists and the limitations.

    A row is returned even when nothing has been adjudicated, and its ``status``
    says so. Filtering happens here rather than in the browser: the row count a
    filter returns is part of what an analyst is reading.
    """
    return _schema_many(db, filters.query(db))


@router.get("/linkages/summary", response_model=PersonaLinkageSummary)
def linkage_summary(
    db: Annotated[Session, Depends(get_db)],
    filters: Annotated[_Filters, Depends(_filters)],
) -> PersonaLinkageSummary:
    """Counts by status and method, plus the model's observed error rate.

    Computed over the same filter set the register is showing, so the two can
    never disagree about how many rows are on screen.
    """
    return _summarize(filters.query(db))


@router.get("/linkages/{linkage_id}", response_model=PersonaLinkageDetail)
def linkage_detail(
    linkage_id: UUID, db: Annotated[Session, Depends(get_db)]
) -> PersonaLinkageDetail:
    """One linkage, with the per-feature agreement behind the three-way split."""
    record = db.get(PersonaLinkageRecord, linkage_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Persona linkage not found")
    base = _schema_many(db, [record])[0]
    metadata = record.metadata_json or {}
    agreement = metadata.get("feature_agreement")
    scorer = metadata.get("scorer")
    return PersonaLinkageDetail(
        **base.model_dump(),
        feature_agreement=(
            {str(name): float(value) for name, value in agreement.items()}
            if isinstance(agreement, dict)
            else {}
        ),
        scorer=str(scorer) if isinstance(scorer, str) else None,
    )


# --------------------------------------------------------------------------
# Write routes
# --------------------------------------------------------------------------


@router.post(
    "/linkages",
    response_model=PersonaLinkageDetail,
    status_code=status.HTTP_201_CREATED,
)
def propose_linkage(
    payload: PersonaLinkageProposal, db: Annotated[Session, Depends(get_db)]
) -> PersonaLinkageDetail:
    """Score two samples and record the result as a *proposal*.

    The score is computed here from the samples, by the platform's own
    stylometry or behaviour functions. There is no request field for it: a body
    carrying ``score`` is rejected outright, because storing a caller's number in
    the column the platform reads as its own output is the one way this table
    could come to mean something it does not.

    A sample too short to analyse is refused with the count and the threshold
    rather than scored, because a number derived from a dozen words would sit in
    that column looking identical to a well-measured one.
    """
    actor = db.get(ActorRecord, payload.actor_id)
    if actor is None:
        raise HTTPException(status_code=404, detail="Actor not found")
    if payload.case_id is not None and db.get(CaseRecord, payload.case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")

    duplicate = db.scalar(
        select(PersonaLinkageRecord).where(
            PersonaLinkageRecord.actor_id == payload.actor_id,
            PersonaLinkageRecord.candidate_handle == payload.candidate_handle,
            PersonaLinkageRecord.method == payload.method,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A {payload.method} linkage between this actor and "
                f"'{payload.candidate_handle}' already exists (linkage "
                f"{duplicate.linkage_id}, status {duplicate.status}). Adjudicate that row "
                "rather than proposing a second one for the same pair and method."
            ),
        )

    try:
        result = score_sample(
            payload.method,
            actor_sample=payload.actor_sample,
            candidate_sample=payload.candidate_sample,
            actor_events=payload.actor_events,
            candidate_events=payload.candidate_events,
        )
    except SampleTooShort as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except MethodNotScorable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    record = PersonaLinkageRecord(
        actor_id=payload.actor_id,
        candidate_handle=payload.candidate_handle,
        method=payload.method,
        score=result.score,
        # Always `proposed`. A score is not a decision, and this endpoint cannot
        # make one: `adjudicate_linkage` is the only writer of the other two.
        status="proposed",
        aligned_features=list(result.aligned),
        apart_features=list(result.apart),
        contested_features=list(result.contested),
        limitations=list(result.limitations),
        case_id=payload.case_id,
        metadata_json={
            "synthetic": False,
            **result.metadata,
        },
    )
    db.add(record)
    db.flush()
    AuditService(db).record(
        "persona.linkage_proposed",
        case_id=payload.case_id,
        entity_type="persona_linkage",
        entity_id=str(record.linkage_id),
        payload={
            "actor_id": str(payload.actor_id),
            "candidate_handle": payload.candidate_handle,
            "method": payload.method,
            "score": result.score,
            "scorer": result.scorer,
            "aligned": len(result.aligned),
            "apart": len(result.apart),
            "contested": len(result.contested),
        },
    )
    db.commit()
    db.refresh(record)
    return linkage_detail(record.linkage_id, db)


@router.post("/linkages/{linkage_id}/adjudicate", response_model=AdjudicationResponse)
def adjudicate_linkage(
    linkage_id: UUID,
    payload: AdjudicationRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdjudicationResponse:
    """Record an analyst's ruling on a proposed linkage.

    The boundary between an estimate and a finding, so it is an explicit,
    attributed and audited act. Three things are required and none of them are
    optional: the deciding analyst (``analyst_id``), a rationale, and the audit
    entry below. The ``ck_persona_linkage_adjudicated`` CHECK constraint
    enforces who and when at the database level; the rationale is enforced here
    because a decision with no stated reason is indistinguishable from a model
    output, which is the distinction this table exists to keep.

    The ruling **replaces** rather than accumulates. An analyst who reverses a
    decision overwrites it, so a row can never read as confirmed and rejected at
    once, and the history lives in the audit trail where it can be replayed.
    """
    record = db.get(PersonaLinkageRecord, linkage_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Persona linkage not found")

    rationale = payload.rationale.strip()
    if rationale == "":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "A rationale is required to adjudicate a linkage. A ruling with no stated "
                "reason is indistinguishable from a model output."
            ),
        )
    analyst = db.get(UserRecord, payload.analyst_id)
    if analyst is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="adjudicated_by must name an existing analyst account.",
        )

    previous_status = record.status
    previous_rationale = record.rationale
    previous_adjudicator = (
        _user_names(db, {record.adjudicated_by}).get(record.adjudicated_by)
        if record.adjudicated_by
        else None
    )

    record.status = payload.status
    record.adjudicated_by = analyst.user_id
    record.adjudicated_at = datetime.now(UTC)
    record.rationale = rationale
    # `score` is deliberately untouched: the model's output and the analyst's
    # decision are separate columns, and an adjudication never rewrites the
    # number the summary's error rate is computed from.

    entry = AuditService(db).record(
        "persona.linkage_adjudicated",
        case_id=record.case_id,
        entity_type="persona_linkage",
        entity_id=str(record.linkage_id),
        actor_id=analyst.user_id,
        payload={
            "from_status": previous_status,
            "to_status": payload.status,
            "analyst": analyst.display_name,
            "rationale": rationale,
            "method": record.method,
            # Recorded so a later reader can see what the model said at the
            # moment a human overruled or endorsed it.
            "score_at_decision": record.score,
            "candidate_handle": record.candidate_handle,
            "actor_id": str(record.actor_id),
        },
    )
    db.commit()
    db.refresh(record)
    return AdjudicationResponse(
        linkage=_schema_many(db, [record])[0],
        previous_status=previous_status,
        previous_rationale=previous_rationale,
        previous_adjudicator=previous_adjudicator,
        audit_seq=entry.seq,
    )


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


_CSV_COLUMNS: tuple[str, ...] = (
    "linkage_id",
    "actor_handle",
    "candidate_handle",
    "method",
    "score",
    "status",
    "aligned_features",
    "apart_features",
    "contested_features",
    "limitations",
    "case_name",
    "adjudicated_by",
    "adjudicated_at",
    "rationale",
    "created_at",
)


def _csv_value(row: PersonaLinkage, column: str) -> str:
    value = getattr(row, column)
    if isinstance(value, list):
        return "; ".join(value)
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@router.get("/export")
def export_linkages(
    db: Annotated[Session, Depends(get_db)],
    filters: Annotated[_Filters, Depends(_filters)],
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "csv",
) -> Response:
    """The register as CSV or JSON, under the same filters the list uses.

    The JSON payload carries the summary alongside the rows. A register exported
    without it would invite the reader to assume the model was right about every
    linkage in the file.
    """
    records = filters.query(db)
    rows = _schema_many(db, records)
    if format == "json":
        payload = PersonaExport(
            generated_at=datetime.now(UTC),
            filters=filters.described(),
            summary=_summarize(records),
            linkages=rows,
        )
        return Response(
            json.dumps(payload.model_dump(mode="json"), indent=2), media_type="application/json"
        )

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for row in rows:
        writer.writerow([_csv_value(row, column) for column in _CSV_COLUMNS])
    return Response(buffer.getvalue(), media_type="text/csv")


__all__ = ["SCORE_THRESHOLD", "router"]
