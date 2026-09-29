"""Builds the copilot's tool context from the live database.

The copilot tools take a {@link CopilotToolContext} holding a graph store, an
assessment service, a timeline and a list of hypotheses. Until now the API
boundary supplied only the search adapter and left the other four unset, so
the graph, assessment, timeline and hypothesis tools all returned "not
available" — the agent could look up evidence and nothing else. That is why
its suggested questions ("compare the hypotheses", "trace this actor") were
promised but not answerable.

This module is the adapter. It maps the operational tables onto the canonical
ontology schemas the graph tools expect.

The mapping is deliberately lossy in one direction and explicit about it: an
entity whose stored ``entity_type`` has no ontology counterpart is *skipped*,
never coerced. A marketplace coerced into a generic platform node would give
the agent a graph that looks connected and is quietly wrong, which is worse
than a smaller graph that means what it says.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.attribution.persistence import AttributionAssessmentPersistenceService
from aegis.db.models import (
    AssessmentRecord,
    CaseRecord,
    EntityRecord,
    HypothesisRecord,
    RelationshipRecord,
)
from aegis.graph.schema import NodeLabel
from aegis.graph.store import InMemoryGraphStore
from aegis.ontology import EntityType, RelationshipType
from aegis.schemas.entity import Entity, Relationship
from aegis.schemas.hypothesis import Hypothesis, HypothesisKind, HypothesisStatus
from aegis.timeline.types import TimelineEvent, TimelineEventKind

logger = logging.getLogger(__name__)

#: Operational entity type -> ontology type.
#:
#: Deliberately an explicit allow-list. Anything absent is skipped rather
#: than mapped to a generic type, because a wrong mapping is indistinguishable
#: from a right one once it is in the graph.
ENTITY_TYPE_MAP: dict[str, EntityType] = {
    "actor": EntityType.ACTOR_HYPOTHESIS,
    "alias": EntityType.ALIAS,
    "handle": EntityType.HANDLE,
    "account": EntityType.HANDLE,
    "domain": EntityType.DOMAIN,
    "ip": EntityType.IP_OBSERVATION,
    "infrastructure": EntityType.CERTIFICATE,
    "wallet": EntityType.WALLET_ADDRESS,
    "marketplace": EntityType.MARKETPLACE,
    "document": EntityType.DOCUMENT,
    "onion": EntityType.ONION_SERVICE,
    "pgp": EntityType.PGP_KEY,
}

#: Operational relationship type -> ontology type.
#:
#: Both sides are explicit. The graph store enforces ontology category
#: compatibility and will reject an incompatible edge, so a relationship whose
#: type is unknown here is dropped instead of raising halfway through a build.
RELATIONSHIP_TYPE_MAP: dict[str, RelationshipType] = {
    "uses": RelationshipType.USES_HANDLE,
    "controls": RelationshipType.ASSOCIATED_WITH_WALLET,
    "authored": RelationshipType.POSTED_ON,
    "transacted": RelationshipType.ASSOCIATED_WITH_WALLET,
    "hosted": RelationshipType.USES_INFRASTRUCTURE,
    "resolved-to": RelationshipType.CERTIFICATE_ASSOCIATED_WITH,
    "associated-with": RelationshipType.ASSOCIATED_WITH,
    "derived-from": RelationshipType.MENTIONS,
    "communicates_with": RelationshipType.CO_OCCURS_WITH,
}


def _entity_type(raw: str) -> EntityType | None:
    return ENTITY_TYPE_MAP.get(raw.strip().lower())


def _relationship_type(raw: str) -> RelationshipType | None:
    return RELATIONSHIP_TYPE_MAP.get(raw.strip().lower())


def to_entity(record: EntityRecord) -> Entity | None:
    """One operational entity row -> the canonical ontology schema."""
    entity_type = _entity_type(record.entity_type)
    if entity_type is None:
        return None
    return Entity(
        entity_id=record.entity_id,
        entity_type=entity_type,
        surface_form=record.surface_form,
        normalized_form=record.normalized_form,
        confidence=min(1.0, max(0.0, record.confidence)),
        evidence_id=record.evidence_id,
        case_id=record.case_id,
    )


def to_relationship(record: RelationshipRecord) -> Relationship | None:
    """One operational relationship row -> the canonical ontology schema."""
    relationship_type = _relationship_type(record.relationship_type)
    if relationship_type is None:
        return None
    return Relationship(
        relationship_id=record.relationship_id,
        relationship_type=relationship_type,
        subject_entity_id=record.subject_entity_id,
        object_entity_id=record.object_entity_id,
        confidence=min(1.0, max(0.0, record.confidence)),
        first_seen=_aware(record.first_seen),
        last_seen=_aware(record.last_seen),
        evidence_ids=tuple(record.evidence_ids),
        case_id=record.case_id,
    )


def _aware(value: datetime | None) -> datetime:
    """Timestamps are timezone-aware everywhere except a legacy row.

    The graph store rejects naive datetimes, and a row written before the
    column was made `timezone=True` would otherwise fail the whole build for
    one bad value. Assuming UTC records what the column actually meant.
    """
    if value is None:
        return datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def build_graph(
    db: Session, *, case_id: UUID | None = None, limit: int = 2_000
) -> InMemoryGraphStore:
    """Assemble a graph store from the case graph, or from every case.

    `limit` bounds the build. A platform-wide graph over a large deployment is
    tens of thousands of nodes, and the copilot's neighbourhood tools are
    interactive: a two-hop expansion of a graph that took a minute to load is
    not an answer. The cap is enforced in SQL, not by slicing afterwards.
    """
    entity_query = select(EntityRecord).order_by(EntityRecord.last_seen.desc()).limit(limit)
    relationship_query = select(RelationshipRecord).limit(limit * 2)
    if case_id is not None:
        entity_query = entity_query.where(EntityRecord.case_id == case_id)
        relationship_query = relationship_query.where(RelationshipRecord.case_id == case_id)

    entities = [entity for row in db.scalars(entity_query).all() if (entity := to_entity(row))]
    relationships: list[Relationship] = []
    skipped_relationships = 0
    for row in db.scalars(relationship_query).all():
        try:
            mapped = to_relationship(row)
        except (ValueError, TypeError):
            # A row the canonical schema rejects — an inverted observation
            # window, a confidence outside [0,1]. Skipping it keeps one bad
            # record from costing the analyst the entire graph, and the count
            # is logged rather than swallowed.
            skipped_relationships += 1
            continue
        if mapped is not None:
            relationships.append(mapped)
    if skipped_relationships:
        logger.warning(
            "Skipped %d relationship(s) the canonical schema rejected", skipped_relationships
        )
    if not entities:
        return InMemoryGraphStore()

    store = InMemoryGraphStore()
    for entity in entities:
        store.add_node(
            str(entity.entity_id),
            _label_for(entity.entity_type),
            entity_type=entity.entity_type,
            properties={
                "surface_form": entity.surface_form,
                "normalized_form": entity.normalized_form,
                "confidence": entity.confidence,
            },
        )
    for relationship in relationships:
        source = str(relationship.subject_entity_id)
        target = str(relationship.object_entity_id)
        # An edge whose endpoint was not loaded is skipped, not raised: the
        # limit may have cut a node out from under its own edge, and failing
        # the whole build for that would be a worse answer than a graph with
        # a documented boundary.
        if source not in store.nodes or target not in store.nodes:
            continue
        try:
            store.add_edge(
                relationship.relationship_type,
                source,
                target,
                first_seen=relationship.first_seen,
                last_seen=relationship.last_seen,
                confidence=relationship.confidence,
                evidence_ids=[str(value) for value in relationship.evidence_ids],
            )
        except Exception:  # noqa: BLE001 - ontology compatibility, not fatal
            logger.debug("Skipped incompatible edge %s", relationship.relationship_id)
    return store


def _label_for(entity_type: EntityType) -> NodeLabel:
    from aegis.graph.schema import label_for_entity_type

    label = label_for_entity_type(entity_type)
    if label is None:
        # Reached only for a type the schema does not know, which cannot
        # happen through to_entity(); the guard keeps the failure loud if it
        # ever does.
        raise ValueError(f"no graph label for {entity_type}")
    return label


def load_hypotheses(db: Session, *, case_id: UUID | None = None) -> list[Hypothesis]:
    """Hypotheses for the copilot's hypothesis tools.

    Ordered newest-first and capped: the tools select from this list by id, so
    an unbounded list is a memory cost with no benefit.
    """
    query = select(HypothesisRecord).order_by(HypothesisRecord.created_at.desc()).limit(200)
    if case_id is not None:
        query = query.where(HypothesisRecord.case_id == case_id)
    return [
        Hypothesis(
            hypothesis_id=row.hypothesis_id,
            case_id=row.case_id,
            kind=_kind_for(row.kind),
            status=_status_for(row.status),
            subject_entity_id=row.subject_entity_id,
            object_entity_id=row.object_entity_id,
            missing_evidence=tuple(row.missing_evidence or ()),
        )
        for row in db.scalars(query).all()
    ]


def load_timeline(
    db: Session, *, case_id: UUID | None = None, limit: int = 200
) -> Sequence[TimelineEvent]:
    """Timeline events for the copilot's timeline tool.

    Case-scoped only. The tool's questions are "what happened to this actor
    within these bounds", and a platform-wide event stream without a case
    cannot be narrowed to one — returning the newest 200 events across every
    investigation would answer a different question than the one asked.
    """
    from aegis.api.dashboard_analytics import case_timeline_layers
    from aegis.timeline.types import TimelineEvent

    if case_id is None:
        return []
    events: list[TimelineEvent] = []
    for index, event in enumerate(case_timeline_layers(db, case_id, limit=limit)):
        if event.evidence_id is None:
            # `TimelineEvent` requires cited evidence, and rightly so: a
            # timeline entry resting on nothing is an assertion, not an
            # event. Audit actions without a citation stay visible in the
            # workspace timeline, but they are not facts the agent may assert.
            continue
        events.append(
            TimelineEvent(
                event_id=f"{event.occurred_at.isoformat()}:{index}",
                subject_id=str(event.case_id),
                kind=_timeline_kind(event.layer),
                observed_at=event.occurred_at,
                value=event.title,
                evidence_ids=(str(event.evidence_id),),
            )
        )
    return events


#: Stored kind -> canonical enum. The canonical vocabulary is coarser than
#: the operational one (an operational "attribution" hypothesis is about
#: whether two entities are the same actor), so the mapping is explicit in
#: both directions rather than assumed to be the same set.
KIND_MAP: dict[str, HypothesisKind] = {
    "attribution": HypothesisKind.SAME_ACTOR,
    "actor_linkage": HypothesisKind.SAME_ACTOR,
    "identity": HypothesisKind.SAME_ACTOR,
    "collaborator": HypothesisKind.COLLABORATOR,
    "collaboration": HypothesisKind.COLLABORATOR,
    "infrastructure": HypothesisKind.COLLABORATOR,
    "coordinated": HypothesisKind.COLLABORATOR,
    "financial": HypothesisKind.COLLABORATOR,
    "impersonation": HypothesisKind.IMPERSONATION,
    "unrelated": HypothesisKind.UNRELATED,
    "not_linked": HypothesisKind.UNRELATED,
}

STATUS_MAP: dict[str, HypothesisStatus] = {
    "candidate": HypothesisStatus.CANDIDATE,
    "open": HypothesisStatus.CANDIDATE,
    "under_review": HypothesisStatus.UNDER_REVIEW,
    "supported": HypothesisStatus.ACCEPTED,
    "confirmed": HypothesisStatus.ACCEPTED,
    "rejected": HypothesisStatus.REJECTED,
    "superseded": HypothesisStatus.SUPERSEDED,
}


#: Timeline lane -> the canonical event kind.
#:
#: The lanes are named for the workspace and the canonical kinds for the
#: timeline model, and the two vocabularies are genuinely different. Notably
#: there is no canonical "financial" event kind: a wallet movement is
#: identified by the entity that carried it, not by a lane label. A financial
#: event therefore maps to ``activity`` and keeps its layer in the event value,
#: rather than being forced into a category it does not have.
TIMELINE_KIND_MAP: dict[str, TimelineEventKind] = {
    "event": TimelineEventKind.ACTIVITY,
    "actor": TimelineEventKind.HANDLE,
    "infrastructure": TimelineEventKind.INFRASTRUCTURE,
    "financial": TimelineEventKind.ACTIVITY,
}


def _timeline_kind(raw: str) -> TimelineEventKind:
    return TIMELINE_KIND_MAP.get(raw.strip().lower(), TimelineEventKind.ACTIVITY)


def _kind_for(raw: str) -> HypothesisKind:
    """Map the stored kind onto the canonical enum, defaulting honestly.

    The column is free-form text so a new kind does not need a migration,
    which makes an unrecognised value a normal possibility rather than an
    error. An unknown kind maps to ``unrelated`` — the weakest claim — so the
    tools can still show it without implying an association that was never
    asserted.
    """
    return KIND_MAP.get(raw.strip().lower(), HypothesisKind.UNRELATED)


def _status_for(raw: str) -> HypothesisStatus:
    return STATUS_MAP.get(raw.strip().lower(), HypothesisStatus.CANDIDATE)


def assessment_service(db: Session) -> AttributionAssessmentPersistenceService:
    return AttributionAssessmentPersistenceService(db)


def case_names(db: Session, case_ids: set[UUID]) -> dict[UUID, str]:
    if not case_ids:
        return {}
    rows = db.execute(
        select(CaseRecord.case_id, CaseRecord.name).where(CaseRecord.case_id.in_(case_ids))
    ).all()
    return {case_id: name for case_id, name in rows}


def leading_confidence(db: Session, case_ids: Sequence[UUID]) -> dict[UUID, float]:
    """Highest calibrated confidence per case, for the copilot's grounding."""
    if not case_ids:
        return {}
    rows = db.execute(
        select(AssessmentRecord.case_id, AssessmentRecord.calibrated_confidence)
        .where(
            AssessmentRecord.case_id.in_(list(case_ids)),
            AssessmentRecord.calibrated_confidence.is_not(None),
        )
        .order_by(AssessmentRecord.case_id, AssessmentRecord.calibrated_confidence.desc())
    ).all()
    lead: dict[UUID, float] = {}
    for case_id, confidence in rows:
        if confidence is None:  # excluded in SQL; mypy cannot see that
            continue
        lead.setdefault(case_id, float(confidence))
    return lead
