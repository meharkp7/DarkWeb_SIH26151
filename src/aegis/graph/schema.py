"""Temporal graph schema (Phase 08).

Mirrors the Neo4j schema from the implementation plan:

**Nodes** (labels): Actor, Handle, PGP, Wallet, Marketplace, Forum,
Infrastructure, Post, Evidence.

**Edges**: at minimum USES_HANDLE, USES_PGP, ASSOCIATED_WITH,
POSTED_ON, OBSERVED_AT, SIMILAR_TO — the store accepts every
``RelationshipType`` in the ontology so ledger relationships import
without loss.

**Edge properties**: ``first_seen``, ``last_seen``, ``confidence``,
``evidence_ids`` — every edge is temporal and evidence-backed.

The schema maps ontology entity types onto node labels; analytical
objects (hypotheses, profiles) are deliberately not graph nodes — they
live in the analysis store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from aegis.ontology import EntityType, RelationshipType


class NodeLabel(StrEnum):
    ACTOR = "Actor"
    HANDLE = "Handle"
    PGP = "PGP"
    WALLET = "Wallet"
    MARKETPLACE = "Marketplace"
    FORUM = "Forum"
    INFRASTRUCTURE = "Infrastructure"
    POST = "Post"
    EVIDENCE = "Evidence"


#: Entity types that become graph nodes, by label.
GRAPH_TYPE_LABELS: dict[EntityType, NodeLabel] = {
    # identity
    EntityType.ACTOR_HYPOTHESIS: NodeLabel.ACTOR,
    EntityType.HANDLE: NodeLabel.HANDLE,
    EntityType.ALIAS: NodeLabel.HANDLE,
    EntityType.EMAIL_IDENTIFIER: NodeLabel.HANDLE,
    EntityType.CONTACT_IDENTIFIER: NodeLabel.HANDLE,
    EntityType.PGP_KEY: NodeLabel.PGP,
    # financial
    EntityType.WALLET_ADDRESS: NodeLabel.WALLET,
    EntityType.ADDRESS_CLUSTER: NodeLabel.WALLET,
    EntityType.TRANSACTION: NodeLabel.WALLET,
    EntityType.PAYMENT_IDENTIFIER: NodeLabel.WALLET,
    # platforms
    EntityType.MARKETPLACE: NodeLabel.MARKETPLACE,
    EntityType.FORUM: NodeLabel.FORUM,
    EntityType.CHANNEL: NodeLabel.FORUM,
    # infrastructure
    EntityType.ONION_SERVICE: NodeLabel.INFRASTRUCTURE,
    EntityType.DOMAIN: NodeLabel.INFRASTRUCTURE,
    EntityType.URL: NodeLabel.INFRASTRUCTURE,
    EntityType.IP_OBSERVATION: NodeLabel.INFRASTRUCTURE,
    EntityType.CERTIFICATE: NodeLabel.INFRASTRUCTURE,
    EntityType.HOSTING_ENTITY: NodeLabel.INFRASTRUCTURE,
    EntityType.TECHNOLOGY_FINGERPRINT: NodeLabel.INFRASTRUCTURE,
    EntityType.SERVICE_FINGERPRINT: NodeLabel.INFRASTRUCTURE,
    # content
    EntityType.POST: NodeLabel.POST,
    EntityType.LISTING: NodeLabel.POST,
    EntityType.MESSAGE: NodeLabel.POST,
    EntityType.DOCUMENT: NodeLabel.POST,
    EntityType.IMAGE: NodeLabel.POST,
    EntityType.CODE_ARTIFACT: NodeLabel.POST,
    # evidence
    EntityType.EVIDENCE_ITEM: NodeLabel.EVIDENCE,
}


def label_for_entity_type(entity_type: EntityType) -> NodeLabel | None:
    """Node label for an entity type, or None when the type is not a
    graph node (analytical objects, collection jobs, raw sources)."""
    return GRAPH_TYPE_LABELS.get(entity_type)


#: The six edge types the plan requires; all are present in the
#: ontology's RelationshipType and therefore accepted by the store.
PLAN_REQUIRED_EDGE_TYPES: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.USES_HANDLE,
        RelationshipType.USES_PGP,
        RelationshipType.ASSOCIATED_WITH,
        RelationshipType.POSTED_ON,
        RelationshipType.OBSERVED_AT,
        RelationshipType.SIMILAR_TO,
    }
)

#: Every edge carries these temporal/evidential properties.
EDGE_PROPERTIES: tuple[str, ...] = ("first_seen", "last_seen", "confidence", "evidence_ids")


class GraphValidationError(ValueError):
    """Raised when a node/edge violates the graph schema."""


class MissingNodeError(GraphValidationError):
    """An edge references a node that is not in the store."""


def ensure_aware(value: datetime, *, field_name: str) -> datetime:
    """Graph windows are timezone-aware; naive datetimes are rejected
    (silent local-time windows are how temporal bugs start)."""
    if value.tzinfo is None:
        raise GraphValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def overlaps(
    first_seen: datetime,
    last_seen: datetime,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    """True when [first_seen, last_seen] intersects [since, until]
    (open-ended when either bound is None)."""
    if since is not None and last_seen < since:
        return False
    if until is not None and first_seen > until:
        return False
    return True


def active_at(first_seen: datetime, last_seen: datetime, at_time: datetime) -> bool:
    return first_seen <= at_time <= last_seen
