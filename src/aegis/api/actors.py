"""Actor registry API — the problem statement's central deliverable.

The statement asks for a *result set*: for every tracked actor, a handle, a
category, the identifiers that pin the persona down, the marketplaces it trades
on, an attribution confidence, the date it was last scanned, and the source it
came from. ``entities`` rows of type ``actor`` cannot carry that — they belong
to one case, have no identity of their own and no scan state — so these routes
read the cross-case registry in ``aegis.db.models`` instead.

Three rules hold across every route here:

* **"Not assessed" is not zero.** ``actors.confidence`` is nullable and the
  schemas below keep it that way. An actor nobody has scored reads as ``null``
  and is *excluded* by a ``min_confidence`` filter rather than being silently
  treated as the worst possible score.
* **Counts are aggregated, never looped.** Registry rows carry their identifier
  and marketplace counts as correlated subqueries and their identifier kinds as
  one grouped read over the returned page, so the query count does not grow
  with the number of actors on screen.
* **No credential field is ever selected.** The registry never joins ``users``
  except through ``persona_linkages.adjudicated_by``, which is returned as a
  bare id — there is no path from this router to ``users.password_hash``.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, func, nullslast, or_, select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.db.models import (
    ActorIdentifierRecord,
    ActorMarketplaceRecord,
    ActorRecord,
    CaseRecord,
    PersonaLinkageRecord,
    SourceRecord,
)

router = APIRouter(prefix="/api/v1/actors", tags=["actors"])

#: Sort keys the registry accepts. An explicit vocabulary rather than a column
#: name interpolated from the query string, so a URL cannot name an arbitrary
#: attribute of the model.
SORT_KEYS: tuple[str, ...] = (
    "handle",
    "category",
    "confidence",
    "identifiers",
    "last_seen",
    "last_scan",
)

#: An actor not re-scanned within this many days is stale. A named constant
#: rather than a literal in the query, because the summary route, the export and
#: the frontend's stale badge have to agree on the threshold.
DEFAULT_STALE_DAYS = 30

#: Registry-wide export ceiling. An analyst exporting "everything" wants the
#: result set, not an unbounded dump that would stall the request.
EXPORT_LIMIT = 5_000


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class ActorRegistryRow(BaseModel):
    """One row of the result set the problem statement asks for.

    Every column the statement names is present on every row, and each says
    what produced it: ``identifier_count``/``marketplace_count`` are counts of
    stored rows, ``confidence`` is the recorded attribution score or ``None``
    when the actor has never been assessed, and ``last_scan_at`` is when the
    actor was last re-scanned — a different fact from ``last_seen``, which is
    when it was last observed.
    """

    model_config = ConfigDict(frozen=True)

    actor_id: UUID
    handle: str
    category: str
    status: str
    #: Attribution confidence, 0–1. ``None`` means *not assessed*, which is not
    #: the same claim as ``0.0`` ("assessed, and no confidence at all"), so the
    #: field is nullable here rather than defaulted.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    first_seen: datetime | None
    last_seen: datetime | None
    last_scan_at: datetime | None
    source_id: UUID | None
    source_name: str | None
    identifier_count: int
    marketplace_count: int
    #: Distinct investigations that cite one of this actor's identifiers, so
    #: the register shows how far an actor reaches across case boundaries.
    case_link_count: int
    #: Identifier counts by kind (handle, pgp, wallet, onion, clearnet, jabber),
    #: for the kind glyphs in the register row.
    identifier_kinds: dict[str, int] = Field(default_factory=dict)
    notes: str | None = None


class ActorIdentifier(BaseModel):
    """A single handle, key, wallet, onion address or messenger handle."""

    model_config = ConfigDict(frozen=True)

    identifier_id: UUID
    kind: str
    value: str
    #: Identifiers that are not independent observations. Three handles on one
    #: onion service are one source wearing three hats, and the analyst has to
    #: be able to discount them.
    independence_group: str | None
    #: Per-identifier confidence, 0–1, or ``None`` when unassessed — same
    #: distinction the actor-level confidence makes.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    first_seen: datetime | None
    last_seen: datetime | None
    source_id: UUID | None
    source_name: str | None
    case_id: UUID | None


class ActorMarketplacePresence(BaseModel):
    """One venue a persona was seen on, with the window it was seen for."""

    model_config = ConfigDict(frozen=True)

    presence_id: UUID
    marketplace: str
    role: str | None
    first_seen: datetime | None
    last_seen: datetime | None
    listing_count: int | None
    source_id: UUID | None
    source_name: str | None


class PersonaLinkageSummary(BaseModel):
    """A proposed or adjudicated link between a candidate persona and an actor.

    ``score`` is the model's and is never overwritten by a human ruling;
    ``status`` says whether an analyst has ruled on it. Only an adjudicated row
    may be presented as a finding, which is why the two are separate fields.
    """

    model_config = ConfigDict(frozen=True)

    linkage_id: UUID
    candidate_handle: str
    method: str
    score: float = Field(ge=0.0, le=1.0)
    status: str
    #: Features that agree, features that oppose, and features measured on both
    #: sides — a three-way split, because a contested feature is not agreement.
    aligned_features: list[str]
    apart_features: list[str]
    contested_features: list[str]
    limitations: list[str]
    case_id: UUID | None
    adjudicated_by: UUID | None
    adjudicated_at: datetime | None
    rationale: str | None


class ActorCaseLink(BaseModel):
    """An investigation that cites one of this actor's identifiers."""

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    name: str
    status: str
    identifier_count: int


class ActorProfile(BaseModel):
    """The actor profile: the register row, resolved into its parts.

    The identifiers arrive grouped by kind and the marketplaces as presence
    windows, because "this persona is on four venues and has moved off two of
    them" is a question about the shape of the record rather than about any one
    row of it.
    """

    model_config = ConfigDict(frozen=True)

    actor: ActorRegistryRow
    identifiers_by_kind: dict[str, list[ActorIdentifier]]
    marketplaces: list[ActorMarketplacePresence]
    #: Empty when nothing has been proposed. An empty list means "no linkage
    #: rows", not "no linkage exists".
    persona_linkages: list[PersonaLinkageSummary]
    linked_cases: list[ActorCaseLink]


class ActorCategoryCount(BaseModel):
    """One category and how many actors carry it, for the filter control."""

    model_config = ConfigDict(frozen=True)

    category: str
    count: int


class ActorStatusCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    count: int


class ActorIdentifierKindCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    count: int


class ActorSummary(BaseModel):
    """Registry-wide counts, all recomputed on each read.

    ``stale`` counts actors whose last scan is older than ``stale_days`` —
    including those never scanned at all, because "we have never looked" is the
    most stale state there is and a count that excluded it would understate the
    backlog.
    """

    model_config = ConfigDict(frozen=True)

    total: int
    by_status: list[ActorStatusCount]
    by_category: list[ActorCategoryCount]
    identifier_kinds: list[ActorIdentifierKindCount]
    identifiers: int
    marketplaces: int
    stale_days: int
    stale: int
    #: Actors carrying no attribution score — the population a ``min_confidence``
    #: filter excludes, stated so the exclusion is visible rather than silent.
    unassessed: int


# --------------------------------------------------------------------------
# Query construction
# --------------------------------------------------------------------------


def _actor_or_404(db: Session, actor_id: UUID) -> ActorRecord:
    record = db.get(ActorRecord, actor_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Actor not found")
    return record


def _identifier_count() -> ColumnElement[int]:
    return (
        select(func.count())
        .select_from(ActorIdentifierRecord)
        .where(ActorIdentifierRecord.actor_id == ActorRecord.actor_id)
        .correlate(ActorRecord.__table__)
        .scalar_subquery()
    )


def _marketplace_count() -> ColumnElement[int]:
    return (
        select(func.count())
        .select_from(ActorMarketplaceRecord)
        .where(ActorMarketplaceRecord.actor_id == ActorRecord.actor_id)
        .correlate(ActorRecord.__table__)
        .scalar_subquery()
    )


def _case_link_count() -> ColumnElement[int]:
    """Distinct investigations citing this actor's identifiers.

    ``count(distinct case_id)`` rather than ``count(*)``: an actor observed
    three times inside one investigation is one link, and counting the
    observations would read as three.
    """
    return (
        select(func.count(func.distinct(ActorIdentifierRecord.case_id)))
        .select_from(ActorIdentifierRecord)
        .where(
            ActorIdentifierRecord.actor_id == ActorRecord.actor_id,
            ActorIdentifierRecord.case_id.is_not(None),
        )
        .correlate(ActorRecord.__table__)
        .scalar_subquery()
    )


def _registry_filters(
    *,
    q: str | None,
    category: str | None,
    status: str | None,
    min_confidence: float | None,
    source_id: UUID | None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    needle = (q or "").strip().lower()
    if needle:
        pattern = f"%{needle}%"
        # Matched against the handle *and* against identifier values, because
        # "where have I seen this onion address" is the question the registry
        # exists to answer, and an actor whose handle differs from every one of
        # its identifiers would otherwise be unreachable by it.
        filters.append(
            or_(
                func.lower(ActorRecord.handle).like(pattern),
                ActorRecord.actor_id.in_(
                    select(ActorIdentifierRecord.actor_id).where(
                        func.lower(ActorIdentifierRecord.value).like(pattern)
                    )
                ),
            )
        )
    if category:
        filters.append(ActorRecord.category == category)
    if status:
        filters.append(ActorRecord.status == status)
    if min_confidence is not None:
        # `is_not(None)` is explicit rather than implied by the comparison: a
        # NULL comparison is never true in SQL, but relying on that would make
        # the exclusion of unassessed actors an accident of three-valued logic
        # instead of a stated rule.
        filters.append(
            ActorRecord.confidence.is_not(None) & (ActorRecord.confidence >= min_confidence)
        )
    if source_id is not None:
        filters.append(ActorRecord.source_id == source_id)
    return filters


def _order_by(sort: str, direction: Literal["asc", "desc"]) -> list[ColumnElement[Any]]:
    """Map a sort key onto an ORDER BY, with nulls last in both directions.

    Sorting a nullable column with a bare ``ASC`` already puts NULLs last, but
    ``DESC`` puts them first — which would float every unscanned actor to the
    top of a "most recently scanned" view. ``nullslast()`` makes the intent
    explicit instead of depending on the direction.

    Typed over ``Any`` rather than ``object``: SQLAlchemy's expression
    generics are invariant in their value parameter, so a narrow annotation
    would reject every expression this function is actually handed.
    """
    descending = direction == "desc"
    columns: dict[str, Any] = {
        "handle": func.lower(ActorRecord.handle),
        "category": ActorRecord.category,
        "confidence": ActorRecord.confidence,
        "identifiers": _identifier_count(),
        "last_seen": ActorRecord.last_seen,
        "last_scan": ActorRecord.last_scan_at,
    }
    chosen = columns[sort]
    ordered = chosen.desc() if descending else chosen.asc()
    # `NULLS LAST` has to be applied *after* the direction: SQLAlchemy renders
    # `nullslast(expr).desc()` as `expr NULLS LAST DESC`, which Postgres rejects
    # as a syntax error rather than silently reordering.
    return [nullslast(ordered), ActorRecord.actor_id.asc()]


def _identifier_kinds(db: Session, actor_ids: list[UUID]) -> dict[UUID, dict[str, int]]:
    """One grouped read for the whole page, not one query per actor."""
    if not actor_ids:
        return {}
    rows = db.execute(
        select(ActorIdentifierRecord.actor_id, ActorIdentifierRecord.kind, func.count())
        .where(ActorIdentifierRecord.actor_id.in_(actor_ids))
        .group_by(ActorIdentifierRecord.actor_id, ActorIdentifierRecord.kind)
    ).all()
    kinds: dict[UUID, dict[str, int]] = {}
    for actor_id, kind, total in rows:
        kinds.setdefault(actor_id, {})[str(kind)] = int(total)
    return kinds


def _registry_rows(
    db: Session,
    *,
    q: str | None,
    category: str | None,
    status: str | None,
    min_confidence: float | None,
    source_id: UUID | None,
    sort: str,
    direction: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> tuple[list[ActorRegistryRow], int]:
    filters = _registry_filters(
        q=q, category=category, status=status, min_confidence=min_confidence, source_id=source_id
    )
    total = int(db.scalar(select(func.count()).select_from(ActorRecord).where(*filters)) or 0)
    query = (
        select(
            ActorRecord,
            SourceRecord.name.label("source_name"),
            _identifier_count().label("identifier_count"),
            _marketplace_count().label("marketplace_count"),
            _case_link_count().label("case_link_count"),
        )
        .outerjoin(SourceRecord, ActorRecord.source_id == SourceRecord.source_id)
        .where(*filters)
        .order_by(*_order_by(sort, direction))
        .limit(limit)
        .offset(offset)
    )
    records = db.execute(query).all()
    kinds = _identifier_kinds(db, [record.actor_id for record, *_ in records])
    return [
        ActorRegistryRow(
            actor_id=record.actor_id,
            handle=record.handle,
            category=record.category,
            status=record.status,
            confidence=record.confidence,
            first_seen=record.first_seen,
            last_seen=record.last_seen,
            last_scan_at=record.last_scan_at,
            source_id=record.source_id,
            source_name=source_name,
            identifier_count=int(identifier_count),
            marketplace_count=int(marketplace_count),
            case_link_count=int(case_link_count),
            identifier_kinds=kinds.get(record.actor_id, {}),
            notes=record.notes,
        )
        for record, source_name, identifier_count, marketplace_count, case_link_count in records
    ], total


def _registry_row(db: Session, actor_id: UUID) -> ActorRegistryRow:
    """One registry row, built by the same projection the list route uses.

    The counts are the same correlated subqueries and the kinds the same grouped
    read, so a profile can never describe an actor with different numbers from
    the row an analyst clicked to reach it.
    """
    record = db.execute(
        select(
            ActorRecord,
            SourceRecord.name.label("source_name"),
            _identifier_count().label("identifier_count"),
            _marketplace_count().label("marketplace_count"),
            _case_link_count().label("case_link_count"),
        )
        .outerjoin(SourceRecord, ActorRecord.source_id == SourceRecord.source_id)
        .where(ActorRecord.actor_id == actor_id)
    ).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Actor not found")
    actor, source_name, identifier_count, marketplace_count, case_link_count = record
    kinds = _identifier_kinds(db, [actor_id])
    return ActorRegistryRow(
        actor_id=actor.actor_id,
        handle=actor.handle,
        category=actor.category,
        status=actor.status,
        confidence=actor.confidence,
        first_seen=actor.first_seen,
        last_seen=actor.last_seen,
        last_scan_at=actor.last_scan_at,
        source_id=actor.source_id,
        source_name=source_name,
        identifier_count=int(identifier_count),
        marketplace_count=int(marketplace_count),
        case_link_count=int(case_link_count),
        identifier_kinds=kinds.get(actor_id, {}),
        notes=actor.notes,
    )


def _identifier_schema(row: ActorIdentifierRecord, source_name: str | None) -> ActorIdentifier:
    return ActorIdentifier(
        identifier_id=row.identifier_id,
        kind=row.kind,
        value=row.value,
        independence_group=row.independence_group,
        confidence=row.confidence,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        source_id=row.source_id,
        source_name=source_name,
        case_id=row.case_id,
    )


# --------------------------------------------------------------------------
# Routes
#
# `/summary`, `/categories` and `/export` are declared before `/{actor_id}`:
# FastAPI matches routes in declaration order, and a path parameter typed as a
# UUID rejects "summary" with a 422 rather than falling through.
# --------------------------------------------------------------------------


@router.get("/summary", response_model=ActorSummary)
def actor_summary(
    db: Annotated[Session, Depends(get_db)],
    stale_days: Annotated[int, Query(ge=1, le=365)] = DEFAULT_STALE_DAYS,
) -> ActorSummary:
    """Registry-wide counts, recomputed on every read.

    Nothing here is cached or incremental: these are counts of stored rows, and
    a stale count on a registry screen is worse than a slightly slower query.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=stale_days)

    def grouped(column: Any) -> list[tuple[str, int]]:
        rows: list[tuple[Any, Any]] = list(
            db.execute(
                select(column, func.count()).group_by(column).order_by(func.count().desc())
            ).all()
        )
        return [(str(value), int(total)) for value, total in rows]

    by_status = [
        ActorStatusCount(status=value, count=count) for value, count in grouped(ActorRecord.status)
    ]
    by_category = [
        ActorCategoryCount(category=value, count=count)
        for value, count in grouped(ActorRecord.category)
    ]
    identifier_kinds = [
        ActorIdentifierKindCount(kind=value, count=count)
        for value, count in grouped(ActorIdentifierRecord.kind)
    ]

    total = int(db.scalar(select(func.count()).select_from(ActorRecord)) or 0)
    unassessed = int(
        db.scalar(
            select(func.count()).select_from(ActorRecord).where(ActorRecord.confidence.is_(None))
        )
        or 0
    )
    # Never scanned counts as stale. `last_scan_at IS NULL OR < cutoff` rather
    # than the comparison alone, because an actor nobody has ever looked at is
    # the back of the backlog, not an actor exempt from it.
    stale = int(
        db.scalar(
            select(func.count())
            .select_from(ActorRecord)
            .where((ActorRecord.last_scan_at.is_(None)) | (ActorRecord.last_scan_at < cutoff))
        )
        or 0
    )
    identifiers = int(db.scalar(select(func.count()).select_from(ActorIdentifierRecord)) or 0)
    marketplaces = int(db.scalar(select(func.count()).select_from(ActorMarketplaceRecord)) or 0)
    return ActorSummary(
        total=total,
        by_status=by_status,
        by_category=by_category,
        identifier_kinds=identifier_kinds,
        identifiers=identifiers,
        marketplaces=marketplaces,
        stale_days=stale_days,
        stale=stale,
        unassessed=unassessed,
    )


@router.get("/categories", response_model=list[ActorCategoryCount])
def actor_categories(db: Annotated[Session, Depends(get_db)]) -> list[ActorCategoryCount]:
    """Distinct categories with their counts, for the filter control.

    Served from the store rather than a hard-coded vocabulary: the problem
    statement names categories, but a registry that has never seen one should
    not offer it as a filter that returns nothing.
    """
    rows = db.execute(
        select(ActorRecord.category, func.count())
        .group_by(ActorRecord.category)
        .order_by(func.count().desc(), ActorRecord.category)
    ).all()
    return [ActorCategoryCount(category=str(value), count=int(total)) for value, total in rows]


@router.get("/export")
def actor_export(
    db: Annotated[Session, Depends(get_db)],
    format: Annotated[str, Query(pattern="^(csv|json|stix)$")] = "csv",
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    source_id: UUID | None = None,
    sort: Annotated[
        str, Query(pattern="^(handle|category|confidence|identifiers|last_seen|last_scan)$")
    ] = "handle",
    dir: Annotated[Literal["asc", "desc"], Query()] = "asc",
    limit: Annotated[int, Query(ge=1, le=EXPORT_LIMIT)] = EXPORT_LIMIT,
) -> Response:
    """The result set as a file — CSV, JSON or a STIX 2.1 bundle.

    The export takes the *same* filters as the list route and applies them with
    the same code path, so what an analyst downloads is the table they were
    looking at rather than the whole registry with the filters applied in
    someone's head afterwards. ``total`` in the JSON and STIX envelopes is the
    filtered count and ``limit`` is what was actually written, so a truncated
    export says so instead of quietly presenting itself as complete.
    """
    direction: Literal["asc", "desc"] = "desc" if dir == "desc" else "asc"
    rows, total = _registry_rows(
        db,
        q=q,
        category=category,
        status=status,
        min_confidence=min_confidence,
        source_id=source_id,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=0,
    )
    applied: dict[str, Any] = {
        "q": q,
        "category": category,
        "status": status,
        "min_confidence": min_confidence,
        "source_id": str(source_id) if source_id is not None else None,
        "sort": sort,
        "dir": direction,
    }
    stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    if format == "json":
        body = {
            "generated_at": stamp,
            "total": total,
            "returned": len(rows),
            "filters": applied,
            "actors": [row.model_dump(mode="json") for row in rows],
        }
        return Response(json.dumps(body, indent=2, sort_keys=True), media_type="application/json")

    if format == "stix":
        return Response(
            json.dumps(_stix_bundle(rows, applied, total, stamp), indent=2),
            media_type="application/json",
        )

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=_CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "actor_id": str(row.actor_id),
                "handle": row.handle,
                "category": row.category,
                "status": row.status,
                # An unassessed actor writes an empty cell, not `0` and not
                # `null`: both of those read as a score.
                "confidence": "" if row.confidence is None else row.confidence,
                "identifier_count": row.identifier_count,
                "marketplace_count": row.marketplace_count,
                "case_link_count": row.case_link_count,
                "identifier_kinds": ";".join(
                    f"{kind}={count}" for kind, count in sorted(row.identifier_kinds.items())
                ),
                "first_seen": row.first_seen.isoformat() if row.first_seen else "",
                "last_seen": row.last_seen.isoformat() if row.last_seen else "",
                "last_scan_at": row.last_scan_at.isoformat() if row.last_scan_at else "",
                "source_name": row.source_name or "",
                "notes": row.notes or "",
            }
        )
    return Response(buffer.getvalue(), media_type="text/csv")


#: The CSV column set, declared beside the export rather than inline in the
#: `DictWriter` call so the test that asserts the header has something to import.
_CSV_FIELDS: tuple[str, ...] = (
    "actor_id",
    "handle",
    "category",
    "status",
    "confidence",
    "identifier_count",
    "marketplace_count",
    "case_link_count",
    "identifier_kinds",
    "first_seen",
    "last_seen",
    "last_scan_at",
    "source_name",
    "notes",
)


def _stix_bundle(
    rows: list[ActorRegistryRow],
    filters: dict[str, Any],
    total: int,
    stamp: str,
) -> dict[str, object]:
    """A STIX 2.1 bundle of ``threat-actor`` objects, one per registry row.

    Deliberately conservative, and no more assertive than the platform is: each
    object carries its confidence as a custom property rather than an
    asserted ``identity``, because a registry row is a hypothesis about who
    someone is, not a finding that they are. The model score is never
    overwritten by an analyst ruling here because no ruling is exported.
    """
    objects: list[dict[str, object]] = []
    for row in rows:
        objects.append(
            {
                "type": "threat-actor",
                "spec_version": "2.1",
                # Deterministic from the row's own id, so re-exporting an
                # unchanged registry produces a byte-identical bundle and a
                # consumer can tell an update from a new object.
                "id": f"threat-actor--{uuid5(NAMESPACE_URL, f'aegis:actor:{row.actor_id}')}",
                "created": row.first_seen.isoformat().replace("+00:00", "Z")
                if row.first_seen
                else stamp,
                "modified": row.last_scan_at.isoformat().replace("+00:00", "Z")
                if row.last_scan_at
                else stamp,
                "name": row.handle,
                "description": row.notes or "Synthetic AEGIS actor registry record.",
                "labels": [row.category, row.status],
                "confidence": row.confidence,
                "x_aegis_actor_id": str(row.actor_id),
                "x_aegis_identifier_count": row.identifier_count,
                "x_aegis_identifier_kinds": sorted(row.identifier_kinds),
                "x_aegis_marketplace_count": row.marketplace_count,
                "x_aegis_case_link_count": row.case_link_count,
                "x_aegis_first_seen": row.first_seen.isoformat() if row.first_seen else None,
                "x_aegis_last_seen": row.last_seen.isoformat() if row.last_seen else None,
                "x_aegis_last_scan_at": row.last_scan_at.isoformat() if row.last_scan_at else None,
                "x_aegis_source_name": row.source_name,
                "external_references": [
                    {
                        "source_name": "aegis-actor-registry",
                        "external_id": str(row.actor_id),
                    }
                ],
            }
        )
    bundle_id = f"bundle--{uuid5(NAMESPACE_URL, f'aegis:actor-registry:{total}:{stamp}')}"
    return {
        "type": "bundle",
        "id": bundle_id,
        "objects": objects,
        # Non-standard `x_aegis_*` properties on the bundle itself: how many rows
        # matched the filters versus how many were written. A consumer that
        # ignores them still gets a valid bundle.
        "x_aegis_matched": total,
        "x_aegis_returned": len(rows),
        "x_aegis_filters": filters,
    }


@router.get("", response_model=list[ActorRegistryRow])
def list_actors(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    source_id: UUID | None = None,
    sort: Annotated[
        str, Query(pattern="^(handle|category|confidence|identifiers|last_seen|last_scan)$")
    ] = "handle",
    dir: Annotated[Literal["asc", "desc"], Query()] = "asc",
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ActorRegistryRow]:
    """The registry result set: one row per actor, filtered, sorted and paged.

    Filtering, sorting and counting all happen in SQL. The identifier and
    marketplace counts are correlated subqueries in the SELECT rather than a
    second query per row, and the identifier kinds come from a single grouped
    read over the page — so three queries serve any page size, and the number an
    analyst reads on screen is the number the database counted.
    """
    direction: Literal["asc", "desc"] = "desc" if dir == "desc" else "asc"
    rows, _total = _registry_rows(
        db,
        q=q,
        category=category,
        status=status,
        min_confidence=min_confidence,
        source_id=source_id,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return rows


@router.get("/{actor_id}", response_model=ActorProfile)
def get_actor(actor_id: UUID, db: Annotated[Session, Depends(get_db)]) -> ActorProfile:
    """One actor's profile: identifiers by kind, venue windows, linkages, cases.

    Assembled in a fixed number of queries regardless of how many identifiers
    the actor has, and the linkage list is simply empty when nothing has been
    proposed — an empty list that means "no rows", not "no link".
    """
    _actor_or_404(db, actor_id)
    actor_row = _registry_row(db, actor_id)

    identifier_rows = db.execute(
        select(ActorIdentifierRecord, SourceRecord.name)
        .outerjoin(SourceRecord, ActorIdentifierRecord.source_id == SourceRecord.source_id)
        .where(ActorIdentifierRecord.actor_id == actor_id)
        .order_by(ActorIdentifierRecord.kind, ActorIdentifierRecord.value)
    ).all()
    identifiers = [_identifier_schema(identifier, name) for identifier, name in identifier_rows]
    grouped: dict[str, list[ActorIdentifier]] = {}
    for identifier in identifiers:
        grouped.setdefault(identifier.kind, []).append(identifier)

    marketplace_rows = db.execute(
        select(ActorMarketplaceRecord, SourceRecord.name)
        .outerjoin(SourceRecord, ActorMarketplaceRecord.source_id == SourceRecord.source_id)
        .where(ActorMarketplaceRecord.actor_id == actor_id)
        .order_by(
            ActorMarketplaceRecord.last_seen.desc().nullslast(), ActorMarketplaceRecord.marketplace
        )
    ).all()
    marketplaces = [
        ActorMarketplacePresence(
            presence_id=presence.presence_id,
            marketplace=presence.marketplace,
            role=presence.role,
            first_seen=presence.first_seen,
            last_seen=presence.last_seen,
            listing_count=presence.listing_count,
            source_id=presence.source_id,
            source_name=name,
        )
        for presence, name in marketplace_rows
    ]

    linkage_rows = db.scalars(
        select(PersonaLinkageRecord)
        .where(PersonaLinkageRecord.actor_id == actor_id)
        .order_by(PersonaLinkageRecord.score.desc(), PersonaLinkageRecord.candidate_handle)
    ).all()
    linkages = [
        PersonaLinkageSummary(
            linkage_id=linkage.linkage_id,
            candidate_handle=linkage.candidate_handle,
            method=linkage.method,
            score=linkage.score,
            status=linkage.status,
            aligned_features=list(linkage.aligned_features or []),
            apart_features=list(linkage.apart_features or []),
            contested_features=list(linkage.contested_features or []),
            limitations=list(linkage.limitations or []),
            case_id=linkage.case_id,
            adjudicated_by=linkage.adjudicated_by,
            adjudicated_at=linkage.adjudicated_at,
            rationale=linkage.rationale,
        )
        for linkage in linkage_rows
    ]

    case_rows = db.execute(
        select(CaseRecord.case_id, CaseRecord.name, CaseRecord.status, func.count())
        .join(ActorIdentifierRecord, ActorIdentifierRecord.case_id == CaseRecord.case_id)
        .where(ActorIdentifierRecord.actor_id == actor_id)
        .group_by(CaseRecord.case_id, CaseRecord.name, CaseRecord.status)
        .order_by(func.count().desc(), CaseRecord.name)
    ).all()
    linked_cases = [
        ActorCaseLink(
            case_id=case_uuid,
            name=name,
            status=case_status,
            identifier_count=int(total),
        )
        for case_uuid, name, case_status, total in case_rows
    ]

    return ActorProfile(
        actor=actor_row,
        identifiers_by_kind=grouped,
        marketplaces=marketplaces,
        persona_linkages=linkages,
        linked_cases=linked_cases,
    )


@router.get("/{actor_id}/identifiers", response_model=list[ActorIdentifier])
def actor_identifiers(
    actor_id: UUID, db: Annotated[Session, Depends(get_db)]
) -> list[ActorIdentifier]:
    """Every identifier on file for one actor, ordered by kind then value.

    Returned as a flat list rather than the profile's grouping so this route can
    back a table or a "copy all identifiers" action without reshaping the
    payload in the browser.
    """
    _actor_or_404(db, actor_id)
    rows = db.execute(
        select(ActorIdentifierRecord, SourceRecord.name)
        .outerjoin(SourceRecord, ActorIdentifierRecord.source_id == SourceRecord.source_id)
        .where(ActorIdentifierRecord.actor_id == actor_id)
        .order_by(ActorIdentifierRecord.kind, ActorIdentifierRecord.value)
    ).all()
    return [_identifier_schema(identifier, name) for identifier, name in rows]


@router.get("/{actor_id}/marketplaces", response_model=list[ActorMarketplacePresence])
def actor_marketplaces(
    actor_id: UUID, db: Annotated[Session, Depends(get_db)]
) -> list[ActorMarketplacePresence]:
    """Venue presences for one actor, most recently seen first.

    Nulls last rather than first: an actor whose only presence window is unknown
    should not lead a "where are they trading now" list.
    """
    _actor_or_404(db, actor_id)
    rows = db.execute(
        select(ActorMarketplaceRecord, SourceRecord.name)
        .outerjoin(SourceRecord, ActorMarketplaceRecord.source_id == SourceRecord.source_id)
        .where(ActorMarketplaceRecord.actor_id == actor_id)
        .order_by(
            ActorMarketplaceRecord.last_seen.desc().nullslast(),
            ActorMarketplaceRecord.marketplace,
        )
    ).all()
    return [
        ActorMarketplacePresence(
            presence_id=presence.presence_id,
            marketplace=presence.marketplace,
            role=presence.role,
            first_seen=presence.first_seen,
            last_seen=presence.last_seen,
            listing_count=presence.listing_count,
            source_id=presence.source_id,
            source_name=name,
        )
        for presence, name in rows
    ]
