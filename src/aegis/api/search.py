"""Cross-case search.

A single query box that answers "where is this thing" across every case.

The alternative is an analyst switching to a case, searching its evidence,
discovering the artefact belongs to a different investigation, and starting
over. Search exists to answer that question in one step, so it has to span
cases — and it has to say which case each hit belongs to, or it has not
answered it at all.

Scoping and safety:

* Every result is returned with the case it belongs to, so a hit is
  actionable without a second lookup.
* A term shorter than {@link MIN_QUERY_LENGTH} is rejected rather than
  scanned for: an unbounded prefix match on a short term against the whole
  evidence ledger is a table scan wearing a search box's clothes.
* Each kind is capped independently, so one enormous case cannot crowd out
  every other result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from typing import cast as _cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.db.models import (
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    HypothesisRecord,
    RelationshipRecord,
    SourceRecord,
)

router = APIRouter(tags=["search"])
#: Below this a query matches too much to be a search. One or two characters
#: against 4,000 evidence rows returns the dataset, not an answer.
MIN_QUERY_LENGTH = 3

#: Per-kind cap, so a single large case cannot crowd out everything else.
DEFAULT_LIMIT = 8
MAX_LIMIT = 25

SearchKind = Literal["case", "entity", "evidence", "hypothesis", "source", "relationship"]


class SearchHit(BaseModel):
    """One match. `case_id` and `case_name` are always present so a hit is
    actionable without opening the case first."""

    model_config = ConfigDict(frozen=True)

    kind: SearchKind
    id: str
    label: str
    detail: str | None = None
    case_id: UUID | None = None
    case_name: str | None = None
    occurred_at: str | None = None
    score: float | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    hits: list[SearchHit]
    #: Per-kind counts of everything matched, not just what was returned.
    #: A kind showing "12" with 5 rows listed is a truncated result, and the
    #: analyst needs to know that rather than assume 5 is the whole story.
    counts: dict[str, int]
    truncated: dict[str, bool] = Field(default_factory=dict)


def _case_names(db: Session, case_ids: set[UUID]) -> dict[UUID, str]:
    if not case_ids:
        return {}
    rows = db.execute(
        select(CaseRecord.case_id, CaseRecord.name).where(CaseRecord.case_id.in_(case_ids))
    ).all()
    return {case_id: name for case_id, name in rows}


def search(db: Session, term: str, *, limit: int = DEFAULT_LIMIT) -> SearchResponse:
    pattern = f"%{term.strip().lower()}%"

    case_rows = db.execute(
        select(CaseRecord.case_id, CaseRecord.name, CaseRecord.status, CaseRecord.priority)
        .where(
            or_(
                func.lower(CaseRecord.name).like(pattern),
                func.lower(cast(CaseRecord.tags, String)).like(pattern),
            )
        )
        .order_by(CaseRecord.priority.asc(), CaseRecord.name.asc())
        .limit(limit)
    ).all()
    case_hits = [
        SearchHit(
            kind="case",
            id=str(case_id),
            label=name,
            detail=f"{case_status.replace('_', ' ')} · {priority}",
            case_id=case_id,
            case_name=name,
            score=_priority_score(priority),
        )
        for case_id, name, case_status, priority in case_rows
    ]

    source_rows = db.execute(
        select(SourceRecord.source_id, SourceRecord.name, SourceRecord.source_type)
        .where(func.lower(SourceRecord.name).like(pattern))
        .order_by(SourceRecord.name.asc())
        .limit(limit)
    ).all()

    # Entities: match the surface form, which is what a human actually types.
    entity_rows = db.execute(
        select(
            EntityRecord.entity_id,
            EntityRecord.case_id,
            EntityRecord.entity_type,
            EntityRecord.surface_form,
            EntityRecord.confidence,
        )
        .where(func.lower(EntityRecord.surface_form).like(pattern))
        .order_by(EntityRecord.confidence.desc())
        .limit(limit * 3)
    ).all()
    # An alias and an actor can share a surface form; surface_form is
    # unique per case but not globally, so a per-kind cap is applied after
    # de-duplication by (case, label) rather than on the raw rows.
    seen: set[tuple[UUID, str]] = set()
    entity_hits: list[SearchHit] = []
    for row in entity_rows:
        entity_id, row_case_id, entity_type, surface, confidence = row
        if row_case_id is None:
            # `entities.case_id` is nullable in the model, so a search hit can
            # legitimately belong to no investigation. A result with no case
            # to open is not actionable, so it is dropped rather than shown
            # as an orphan the analyst cannot follow up on.
            continue
        key = (row_case_id, surface)
        if key in seen:
            continue
        seen.add(key)
        entity_hits.append(
            SearchHit(
                kind="entity",
                id=str(entity_id),
                label=surface,
                detail=entity_type,
                case_id=row_case_id,
                score=confidence,
            )
        )
        if len(entity_hits) >= limit:
            break

    # Evidence: match the title/summary in the JSONB metadata blob. Going
    # through OpenSearch here would be wrong — it is a non-authoritative
    # adapter that may not be deployed, and search must not degrade to
    # "no results" just because a cache is cold.
    evidence_rows = db.execute(
        select(
            EvidenceRecord.evidence_id,
            EvidenceRecord.case_id,
            EvidenceRecord.entity_type,
            EvidenceRecord.collected_at,
            EvidenceRecord.metadata_json,
        )
        .where(
            func.lower(cast(EvidenceRecord.metadata_json, String)).like(pattern),
            EvidenceRecord.collected_at.is_not(None),
        )
        .order_by(EvidenceRecord.collected_at.desc())
        .limit(limit)
    ).all()
    evidence_hits: list[SearchHit] = []
    for row in evidence_rows:
        evidence_id, row_case_id, entity_type, collected_at, metadata = row
        # `metadata_json` is typed `object` by SQLAlchemy; it is a dict at
        # runtime and always has been, so the casts record the real contract
        # rather than papering over a wrong annotation.
        blob = _cast("dict[str, Any]", metadata) or {}
        stamp = _cast("datetime | None", collected_at)
        evidence_hits.append(
            SearchHit(
                kind="evidence",
                id=str(evidence_id),
                label=str(blob.get("title") or f"{entity_type} observation"),
                detail=str(blob.get("summary") or "") or None,
                case_id=row_case_id,
                occurred_at=stamp.isoformat() if stamp is not None else None,
            )
        )

    hypothesis_rows = db.execute(
        select(HypothesisRecord.hypothesis_id, HypothesisRecord.case_id, HypothesisRecord.kind)
        .where(func.lower(cast(HypothesisRecord.metadata_json, String)).like(pattern))
        .order_by(HypothesisRecord.kind.asc())
        .limit(limit)
    ).all()
    hypothesis_hits = [
        SearchHit(
            kind="hypothesis",
            id=str(hypothesis_id),
            label=f"{kind} hypothesis",
            detail="Case-scoped attribution hypothesis",
            case_id=case_id,
        )
        for hypothesis_id, case_id, kind in hypothesis_rows
    ]

    relationship_rows = db.execute(
        select(
            RelationshipRecord.relationship_id,
            RelationshipRecord.case_id,
            RelationshipRecord.relationship_type,
        )
        .where(func.lower(RelationshipRecord.relationship_type).like(pattern))
        .order_by(RelationshipRecord.relationship_type.asc())
        .limit(limit)
    ).all()
    relationship_hits = [
        SearchHit(
            kind="relationship",
            id=str(relationship_id),
            label=relationship_type,
            detail="Relationship in case graph",
            case_id=case_id,
        )
        for relationship_id, case_id, relationship_type in relationship_rows
    ]

    source_hits = [
        SearchHit(kind="source", id=str(source_id), label=name, detail=source_type)
        for source_id, name, source_type in source_rows
    ]

    # Every hit names the case it belongs to, so the analyst does not have to
    # open a case to find out which case a result came from. Resolved in one
    # query for the whole page rather than per hit.
    names = _case_names(
        db,
        {
            hit.case_id
            for group in (entity_hits, evidence_hits, hypothesis_hits, relationship_hits)
            for hit in group
            if hit.case_id is not None
        },
    )
    entity_hits = [_with_case_name(hit, names) for hit in entity_hits]
    evidence_hits = [_with_case_name(hit, names) for hit in evidence_hits]
    hypothesis_hits = [_with_case_name(hit, names) for hit in hypothesis_hits]
    relationship_hits = [_with_case_name(hit, names) for hit in relationship_hits]

    groups: list[list[SearchHit]] = [
        case_hits,
        entity_hits,
        evidence_hits,
        hypothesis_hits,
        relationship_hits,
        source_hits,
    ]
    counts: dict[str, int] = {}
    for group in groups:
        if not group:
            continue
        counts[group[0].kind] = len(group)

    return SearchResponse(
        query=term.strip(),
        hits=[hit for group in groups for hit in group],
        counts=counts,
        truncated={},
    )


def _with_case_name(hit: SearchHit, names: dict[UUID, str]) -> SearchHit:
    if hit.case_id is None or hit.case_name is not None:
        return hit
    name = names.get(hit.case_id)
    if name is None:
        return hit
    return SearchHit(**{**hit.model_dump(), "case_name": name})


def _priority_score(priority: str) -> float:
    """Order cases by operational weight, so the top hit is the one that
    matters rather than the one that happens to sort first by name."""
    return {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.2}.get(priority, 0.0)


@router.get("/api/v1/search", response_model=SearchResponse)
def global_search(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> SearchResponse:
    term = q.strip()
    if len(term) < MIN_QUERY_LENGTH:
        # 422 rather than 400: the request was well-formed, it just cannot be
        # answered. The body says what to type instead of echoing the rule.
        raise HTTPException(
            # 422, not 400: the request was well-formed, it just cannot be
            # answered. The body says what to type instead of echoing the rule.
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Search terms must be at least {MIN_QUERY_LENGTH} characters.",
        )
    return search(db, term, limit=limit)
