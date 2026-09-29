"""Actor-to-actor links: the trust graph the problem statement names.

The second core capability is "mapping threat actors across multiple
marketplaces into a single relationship graph of handles, PGP keys, wallets
and **trust links**". Identifiers and marketplace presence hang off an actor;
the relations *between* actors had nowhere to live.

The graph endpoint is the point. `/actors/graph` returns a whole registry
graph in one request with per-node degree, identifier kinds and platform
count already resolved, because a relationship explorer that issues a query
per node is unusable on a registry of any size and cannot answer "who does
this actor deal with, and in what capacity" without it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.db.audit import AuditService
from aegis.db.models import (
    ActorIdentifierRecord,
    ActorLinkRecord,
    ActorMarketplaceRecord,
    ActorRecord,
    SourceRecord,
)
from aegis.schemas.actor_links import (
    DIRECTED_KINDS,
    ActorGraphEdge,
    ActorGraphNode,
    ActorGraphResponse,
    ActorLink,
    ActorLinkCreate,
    ActorLinkDecision,
)

router = APIRouter(prefix="/api/v1/actors", tags=["actors"])

def _link_schema(
    row: ActorLinkRecord,
    subject: ActorRecord,
    obj: ActorRecord,
    source_name: str | None,
) -> ActorLink:
    """One stored link, with both ends and the source resolved.

    A graph edge that shows two opaque ids is not a relationship; naming the
    two actors is most of what makes it readable.
    """
    return ActorLink(
        link_id=row.link_id,
        kind=row.kind,
        subject_actor_id=row.subject_actor_id,
        subject_handle=subject.handle,
        subject_category=subject.category,
        object_actor_id=row.object_actor_id,
        object_handle=obj.handle,
        object_category=obj.category,
        basis=row.basis,
        limitations=list(row.limitations or []),
        confidence=row.confidence,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        source_id=row.source_id,
        source_name=source_name,
        case_id=row.case_id,
        evidence_ids=list(row.evidence_ids),
        analyst_recorded=row.analyst_recorded,
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
    )


def _resolve_ends(
    db: Session, rows: list[ActorLinkRecord]
) -> list[ActorLink]:
    if not rows:
        return []
    actor_ids = {row.subject_actor_id for row in rows} | {row.object_actor_id for row in rows}
    actors = {
        actor.actor_id: actor
        for actor in db.scalars(
            select(ActorRecord).where(ActorRecord.actor_id.in_(actor_ids))
        ).all()
    }
    source_ids = {row.source_id for row in rows if row.source_id is not None}
    names = (
        {
            source_id: name
            for source_id, name in db.execute(
                select(SourceRecord.source_id, SourceRecord.name).where(
                    SourceRecord.source_id.in_(source_ids)
                )
            ).all()
        }
        if source_ids
        else {}
    )
    out: list[ActorLink] = []
    for row in rows:
        subject = actors.get(row.subject_actor_id)
        obj = actors.get(row.object_actor_id)
        # A link whose endpoint is missing cannot be rendered, and cannot be
        # acted on. The foreign key makes this unreachable in practice; the
        # guard is so a future data change degrades the list rather than
        # raising halfway through building a response.
        if subject is None or obj is None:
            continue
        out.append(
            _link_schema(row, subject, obj, names.get(row.source_id) if row.source_id else None)
        )
    return out


@router.get("/links", response_model=list[ActorLink])
def actor_links(
    db: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[UUID | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    recorded: Annotated[bool | None, Query()] = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[ActorLink]:
    """Links between actors, newest activity first.

    `actor_id` matches **either** end. Trust is directed, but "everything
    this actor is connected to" is not a directed question, and forcing the
    analyst to run it twice with different meanings is how half a graph gets
    read.
    """
    query = select(ActorLinkRecord)
    if actor_id is not None:
        query = query.where(
            or_(
                ActorLinkRecord.subject_actor_id == actor_id,
                ActorLinkRecord.object_actor_id == actor_id,
            )
        )
    if kind:
        query = query.where(ActorLinkRecord.kind == kind)
    if recorded is not None:
        query = query.where(ActorLinkRecord.analyst_recorded.is_(recorded))
    if min_confidence is not None:
        query = query.where(ActorLinkRecord.confidence >= min_confidence)
    rows = list(
        db.scalars(
            query.order_by(
                ActorLinkRecord.last_seen.desc().nullslast(),
                ActorLinkRecord.first_seen.desc().nullslast(),
            ).limit(limit)
        ).all()
    )
    return _resolve_ends(db, rows)


@router.get("/graph", response_model=ActorGraphResponse)
def actor_graph(
    db: Annotated[Session, Depends(get_db)],
    kinds: Annotated[list[str] | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    recorded_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=400)] = 120,
) -> ActorGraphResponse:
    """The registry relationship graph, assembled server-side.

    Node degree, identifier kinds and platform count are resolved here rather
    than in the browser, so the explorer is one request and a node can always
    describe itself.

    `limit` bounds the nodes, and the response says how many were dropped. A
    silently truncated graph looks like a complete one.
    """
    node_query = select(ActorRecord).order_by(ActorRecord.last_seen.desc().nullslast())
    if category:
        node_query = node_query.where(ActorRecord.category == category)
    actors = list(db.scalars(node_query.limit(limit)).all())
    dropped = max(
        0,
        int(
            db.scalar(
                select(func.count())
                .select_from(ActorRecord)
                .where(*( [ActorRecord.category == category] if category else [] ))
            )
            or 0
        )
        - len(actors),
    )
    if not actors:
        return ActorGraphResponse(
            nodes=[], edges=[], dropped_nodes=dropped, kinds={}, independence_groups=0
        )

    actor_ids = [actor.actor_id for actor in actors]
    kept = set(actor_ids)

    link_query = select(ActorLinkRecord).where(
        ActorLinkRecord.subject_actor_id.in_(actor_ids),
        ActorLinkRecord.object_actor_id.in_(actor_ids),
    )
    if kinds:
        link_query = link_query.where(ActorLinkRecord.kind.in_(kinds))
    if recorded_only:
        link_query = link_query.where(ActorLinkRecord.analyst_recorded.is_(True))
    links = list(
        db.scalars(
            link_query.order_by(ActorLinkRecord.last_seen.desc().nullslast()).limit(limit * 3)
        ).all()
    )

    degree: dict[UUID, int] = {}
    kind_counts: dict[str, int] = {}
    directed: dict[str, bool] = {}
    for link in links:
        degree[link.subject_actor_id] = degree.get(link.subject_actor_id, 0) + 1
        degree[link.object_actor_id] = degree.get(link.object_actor_id, 0) + 1
        kind_counts[link.kind] = kind_counts.get(link.kind, 0) + 1
        directed[link.kind] = link.kind in DIRECTED_KINDS

    identifier_rows = db.execute(
        select(ActorIdentifierRecord.actor_id, ActorIdentifierRecord.kind).where(
            ActorIdentifierRecord.actor_id.in_(actor_ids)
        )
    ).all()
    kinds_by_actor: dict[UUID, set[str]] = {}
    for actor_id, kind in identifier_rows:
        kinds_by_actor.setdefault(actor_id, set()).add(kind)

    platform_rows = db.execute(
        select(ActorMarketplaceRecord.actor_id, func.count()).where(
            ActorMarketplaceRecord.actor_id.in_(actor_ids)
        ).group_by(ActorMarketplaceRecord.actor_id)
    ).all()
    platforms = {actor_id: int(total) for actor_id, total in platform_rows}

    independence: set[str] = set()
    source_rows = db.execute(
        select(ActorIdentifierRecord.independence_group).where(
            ActorIdentifierRecord.actor_id.in_(actor_ids),
            ActorIdentifierRecord.independence_group.is_not(None),
        )
    ).all()
    for (group,) in source_rows:
        if group:
            independence.add(str(group))

    resolved = _resolve_ends(db, links)
    edges: list[ActorGraphEdge] = [
        ActorGraphEdge(
            link_id=link.link_id,
            kind=link.kind,
            directed=directed.get(link.kind, False),
            subject_actor_id=link.subject_actor_id,
            object_actor_id=link.object_actor_id,
            subject_handle=link.subject_handle,
            object_handle=link.object_handle,
            confidence=link.confidence,
            basis=link.basis,
            analyst_recorded=link.analyst_recorded,
        )
        for link in resolved
        if link.subject_actor_id in kept and link.object_actor_id in kept
    ]

    return ActorGraphResponse(
        nodes=[
            ActorGraphNode(
                actor_id=actor.actor_id,
                handle=actor.handle,
                category=actor.category,
                status=actor.status,
                confidence=actor.confidence,
                degree=degree.get(actor.actor_id, 0),
                identifier_kinds=sorted(kinds_by_actor.get(actor.actor_id, set())),
                platforms=platforms.get(actor.actor_id, 0),
                last_seen=actor.last_seen,
            )
            for actor in actors
        ],
        edges=edges,
        dropped_nodes=dropped,
        kinds=kind_counts,
        independence_groups=len(independence),
    )


@router.get("/links/summary")
def links_summary(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Counts by kind, plus how many links an analyst has ruled on.

    `unrecorded` is the number worth leading with: a graph of model
    proposals is a hypothesis, not a map.
    """
    rows = db.execute(
        select(ActorLinkRecord.kind, func.count()).group_by(ActorLinkRecord.kind)
    ).all()
    by_kind = {kind: int(total) for kind, total in rows}
    recorded = int(
        db.scalar(
            select(func.count())
            .select_from(ActorLinkRecord)
            .where(ActorLinkRecord.analyst_recorded.is_(True))
        )
        or 0
    )
    total = sum(by_kind.values())
    without_basis = int(
        db.scalar(
            select(func.count())
            .select_from(ActorLinkRecord)
            .where(ActorLinkRecord.basis.is_(None))
        )
        or 0
    )
    return {
        "total": total,
        "recorded": recorded,
        "unrecorded": total - recorded,
        "by_kind": by_kind,
        "directed_kinds": sorted(DIRECTED_KINDS),
        "without_basis": without_basis,
    }


@router.post("/links", response_model=ActorLink, status_code=status.HTTP_201_CREATED)
def create_link(
    payload: ActorLinkCreate,
    db: Annotated[Session, Depends(get_db)],
) -> ActorLink:
    """Record a link between two actors.

    A caller-supplied confidence is accepted but the link is stored as a
    *proposal*: `analyst_recorded` stays false until someone rules on it.
    Silently recording an unreviewed link as a finding is the one outcome
    this endpoint must not produce.
    """
    if payload.subject_actor_id == payload.object_actor_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A link must connect two distinct actors.",
        )
    for actor_id in (payload.subject_actor_id, payload.object_actor_id):
        if db.get(ActorRecord, actor_id) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Both actors must exist in the registry.",
            )
    existing = db.scalar(
        select(ActorLinkRecord).where(
            ActorLinkRecord.subject_actor_id == payload.subject_actor_id,
            ActorLinkRecord.object_actor_id == payload.object_actor_id,
            ActorLinkRecord.kind == payload.kind,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That link already exists between these actors.",
        )

    record = ActorLinkRecord(
        subject_actor_id=payload.subject_actor_id,
        object_actor_id=payload.object_actor_id,
        kind=payload.kind,
        basis=payload.basis,
        limitations=list(payload.limitations),
        confidence=payload.confidence,
        first_seen=payload.first_seen or datetime.now(UTC),
        last_seen=payload.last_seen or datetime.now(UTC),
        source_id=payload.source_id,
        case_id=payload.case_id,
        evidence_ids=payload.evidence_ids,
        analyst_recorded=False,
    )
    db.add(record)
    db.flush()
    AuditService(db).record(
        "actor.link_proposed",
        case_id=payload.case_id,
        entity_type="actor_link",
        entity_id=str(record.link_id),
        payload={
            "kind": payload.kind,
            "subject": str(payload.subject_actor_id),
            "object": str(payload.object_actor_id),
        },
    )
    db.commit()
    db.refresh(record)
    return _resolve_ends(db, [record])[0]


@router.post("/links/{link_id}/decide", response_model=ActorLink)
def decide_link(
    link_id: UUID,
    payload: ActorLinkDecision,
    db: Annotated[Session, Depends(get_db)],
) -> ActorLink:
    """An analyst rules on a proposed link.

    The basis is **required**: a decision with no stated reason is
    indistinguishable from a model output, which is the distinction
    `analyst_recorded` exists to preserve. Re-deciding replaces the prior
    ruling rather than accumulating, so an analyst can reverse themselves
    and the audit trail keeps the history.
    """
    record = db.get(ActorLinkRecord, link_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Link not found")
    record.analyst_recorded = True
    record.recorded_by = payload.actor_id
    record.recorded_at = datetime.now(UTC)
    record.basis = payload.basis.strip()
    record.confidence = payload.confidence
    if payload.limitations:
        record.limitations = list(payload.limitations)

    AuditService(db).record(
        "actor.link_recorded",
        case_id=record.case_id,
        entity_type="actor_link",
        entity_id=str(record.link_id),
        actor_id=payload.actor_id,
        payload={"kind": record.kind, "basis": record.basis},
    )
    db.commit()
    db.refresh(record)
    return _resolve_ends(db, [record])[0]
