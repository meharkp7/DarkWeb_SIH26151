"""Canonical ontology: entity and relationship types shared by every service.

No service may invent its own evidence/entity/relationship vocabulary;
extension happens here so the graph, search, and reporting layers stay
consistent.
"""

from __future__ import annotations

from enum import StrEnum


class EntityCategory(StrEnum):
    """High-level grouping used by the graph and search layers."""

    IDENTITY = "identity"
    INFRASTRUCTURE = "infrastructure"
    FINANCIAL = "financial"
    CONTENT = "content"
    PLATFORM = "platform"
    ANALYTICAL = "analytical"


class EntityType(StrEnum):
    # Identity
    ACTOR_HYPOTHESIS = "actor_hypothesis"
    HANDLE = "handle"
    ALIAS = "alias"
    PGP_KEY = "pgp_key"
    EMAIL_IDENTIFIER = "email_identifier"
    CONTACT_IDENTIFIER = "contact_identifier"

    # Infrastructure
    ONION_SERVICE = "onion_service"
    DOMAIN = "domain"
    IP_OBSERVATION = "ip_observation"
    CERTIFICATE = "certificate"
    HOSTING_ENTITY = "hosting_entity"
    TECHNOLOGY_FINGERPRINT = "technology_fingerprint"
    SERVICE_FINGERPRINT = "service_fingerprint"

    # Financial
    WALLET_ADDRESS = "wallet_address"
    TRANSACTION = "transaction"
    ADDRESS_CLUSTER = "address_cluster"
    PAYMENT_IDENTIFIER = "payment_identifier"

    # Content
    POST = "post"
    LISTING = "listing"
    MESSAGE = "message"
    DOCUMENT = "document"
    IMAGE = "image"
    CODE_ARTIFACT = "code_artifact"

    # Platform
    MARKETPLACE = "marketplace"
    FORUM = "forum"
    CHANNEL = "channel"
    SOURCE = "source"
    COLLECTION_JOB = "collection_job"

    # Analytical
    BEHAVIORAL_PROFILE = "behavioral_profile"
    STYLOMETRIC_PROFILE = "stylometric_profile"
    EVIDENCE_ITEM = "evidence_item"
    HYPOTHESIS = "hypothesis"
    ATTRIBUTION_ASSESSMENT = "attribution_assessment"
    TIMELINE_EVENT = "timeline_event"
    CHANGE_POINT = "change_point"
    MIGRATION_ASSESSMENT = "migration_assessment"


#: Maps each entity type to its ontological category.
ENTITY_CATEGORIES: dict[EntityType, EntityCategory] = {
    EntityType.ACTOR_HYPOTHESIS: EntityCategory.IDENTITY,
    EntityType.HANDLE: EntityCategory.IDENTITY,
    EntityType.ALIAS: EntityCategory.IDENTITY,
    EntityType.PGP_KEY: EntityCategory.IDENTITY,
    EntityType.EMAIL_IDENTIFIER: EntityCategory.IDENTITY,
    EntityType.CONTACT_IDENTIFIER: EntityCategory.IDENTITY,
    EntityType.ONION_SERVICE: EntityCategory.INFRASTRUCTURE,
    EntityType.DOMAIN: EntityCategory.INFRASTRUCTURE,
    EntityType.IP_OBSERVATION: EntityCategory.INFRASTRUCTURE,
    EntityType.CERTIFICATE: EntityCategory.INFRASTRUCTURE,
    EntityType.HOSTING_ENTITY: EntityCategory.INFRASTRUCTURE,
    EntityType.TECHNOLOGY_FINGERPRINT: EntityCategory.INFRASTRUCTURE,
    EntityType.SERVICE_FINGERPRINT: EntityCategory.INFRASTRUCTURE,
    EntityType.WALLET_ADDRESS: EntityCategory.FINANCIAL,
    EntityType.TRANSACTION: EntityCategory.FINANCIAL,
    EntityType.ADDRESS_CLUSTER: EntityCategory.FINANCIAL,
    EntityType.PAYMENT_IDENTIFIER: EntityCategory.FINANCIAL,
    EntityType.POST: EntityCategory.CONTENT,
    EntityType.LISTING: EntityCategory.CONTENT,
    EntityType.MESSAGE: EntityCategory.CONTENT,
    EntityType.DOCUMENT: EntityCategory.CONTENT,
    EntityType.IMAGE: EntityCategory.CONTENT,
    EntityType.CODE_ARTIFACT: EntityCategory.CONTENT,
    EntityType.MARKETPLACE: EntityCategory.PLATFORM,
    EntityType.FORUM: EntityCategory.PLATFORM,
    EntityType.CHANNEL: EntityCategory.PLATFORM,
    EntityType.SOURCE: EntityCategory.PLATFORM,
    EntityType.COLLECTION_JOB: EntityCategory.PLATFORM,
    EntityType.BEHAVIORAL_PROFILE: EntityCategory.ANALYTICAL,
    EntityType.STYLOMETRIC_PROFILE: EntityCategory.ANALYTICAL,
    EntityType.EVIDENCE_ITEM: EntityCategory.ANALYTICAL,
    EntityType.HYPOTHESIS: EntityCategory.ANALYTICAL,
    EntityType.ATTRIBUTION_ASSESSMENT: EntityCategory.ANALYTICAL,
    EntityType.TIMELINE_EVENT: EntityCategory.ANALYTICAL,
    EntityType.CHANGE_POINT: EntityCategory.ANALYTICAL,
    EntityType.MIGRATION_ASSESSMENT: EntityCategory.ANALYTICAL,
}


def category_of(entity_type: EntityType) -> EntityCategory:
    """Return the ontological category for an entity type."""
    return ENTITY_CATEGORIES[entity_type]


class RelationshipType(StrEnum):
    OBSERVED_AT = "OBSERVED_AT"
    USES_HANDLE = "USES_HANDLE"
    USES_PGP = "USES_PGP"
    ASSOCIATED_WITH_WALLET = "ASSOCIATED_WITH_WALLET"
    POSTED_ON = "POSTED_ON"
    MENTIONS = "MENTIONS"
    REPLIES_TO = "REPLIES_TO"
    SIMILAR_TO = "SIMILAR_TO"
    MIGRATED_TO = "MIGRATED_TO"
    USES_INFRASTRUCTURE = "USES_INFRASTRUCTURE"
    CERTIFICATE_ASSOCIATED_WITH = "CERTIFICATE_ASSOCIATED_WITH"
    INFRASTRUCTURE_SIMILAR_TO = "INFRASTRUCTURE_SIMILAR_TO"
    CO_OCCURS_WITH = "CO_OCCURS_WITH"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"
    OBSERVED_BY = "OBSERVED_BY"
    VALID_DURING = "VALID_DURING"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    POSTED_IN = "POSTED_IN"
    REPLY_TO = "REPLY_TO"


class RelationDirection(StrEnum):
    DIRECTED = "directed"
    SYMMETRIC = "symmetric"


#: Direction semantics per relationship type.
RELATIONSHIP_DIRECTION: dict[RelationshipType, RelationDirection] = {
    RelationshipType.SIMILAR_TO: RelationDirection.SYMMETRIC,
    RelationshipType.INFRASTRUCTURE_SIMILAR_TO: RelationDirection.SYMMETRIC,
    RelationshipType.CO_OCCURS_WITH: RelationDirection.SYMMETRIC,
    RelationshipType.CERTIFICATE_ASSOCIATED_WITH: RelationDirection.SYMMETRIC,
    RelationshipType.ASSOCIATED_WITH: RelationDirection.SYMMETRIC,
}
for _rel in RelationshipType:
    RELATIONSHIP_DIRECTION.setdefault(_rel, RelationDirection.DIRECTED)
del _rel

#: Allowed (subject category, object category) pairs per relationship type.
#: A relationship whose categories are not listed for its type is rejected at
#: write time rather than silently accepted, keeping the graph ontologically
#: consistent.
ConstraintMap = dict[RelationshipType, frozenset[tuple[EntityCategory, EntityCategory]]]

RELATIONSHIP_CONSTRAINTS: ConstraintMap = (
    {
        RelationshipType.USES_HANDLE: frozenset(
            {
                (EntityCategory.IDENTITY, EntityCategory.IDENTITY),
                (EntityCategory.ANALYTICAL, EntityCategory.IDENTITY),
            }
        ),
        RelationshipType.USES_PGP: frozenset(
            {
                (EntityCategory.IDENTITY, EntityCategory.IDENTITY),
                (EntityCategory.ANALYTICAL, EntityCategory.IDENTITY),
            }
        ),
        RelationshipType.ASSOCIATED_WITH_WALLET: frozenset(
            {(EntityCategory.IDENTITY, EntityCategory.FINANCIAL),
             (EntityCategory.FINANCIAL, EntityCategory.FINANCIAL),
             (EntityCategory.ANALYTICAL, EntityCategory.FINANCIAL)}
        ),
        RelationshipType.POSTED_ON: frozenset(
            {(EntityCategory.CONTENT, EntityCategory.PLATFORM),
             (EntityCategory.IDENTITY, EntityCategory.PLATFORM)}
        ),
        RelationshipType.POSTED_IN: frozenset(
            {(EntityCategory.CONTENT, EntityCategory.PLATFORM)}
        ),
        RelationshipType.REPLIES_TO: frozenset({(EntityCategory.CONTENT, EntityCategory.CONTENT)}),
        RelationshipType.REPLY_TO: frozenset({(EntityCategory.CONTENT, EntityCategory.CONTENT)}),
        RelationshipType.MENTIONS: frozenset(
            {(EntityCategory.CONTENT, EntityCategory.IDENTITY),
             (EntityCategory.CONTENT, EntityCategory.INFRASTRUCTURE),
             (EntityCategory.CONTENT, EntityCategory.FINANCIAL)}
        ),
        RelationshipType.MIGRATED_TO: frozenset(
            {(EntityCategory.IDENTITY, EntityCategory.IDENTITY)}
        ),
        RelationshipType.USES_INFRASTRUCTURE: frozenset(
            {(EntityCategory.IDENTITY, EntityCategory.INFRASTRUCTURE),
             (EntityCategory.PLATFORM, EntityCategory.INFRASTRUCTURE)}
        ),
        RelationshipType.CERTIFICATE_ASSOCIATED_WITH: frozenset(
            {(EntityCategory.INFRASTRUCTURE, EntityCategory.INFRASTRUCTURE)}
        ),
        RelationshipType.DERIVED_FROM: frozenset(
            {(EntityCategory.ANALYTICAL, EntityCategory.ANALYTICAL),
             (EntityCategory.CONTENT, EntityCategory.CONTENT),
             (EntityCategory.ANALYTICAL, EntityCategory.CONTENT)}
        ),
        RelationshipType.SUPPORTS: frozenset(
            {(EntityCategory.ANALYTICAL, EntityCategory.ANALYTICAL)}
        ),
        RelationshipType.CONTRADICTS: frozenset(
            {(EntityCategory.ANALYTICAL, EntityCategory.ANALYTICAL)}
        ),
    }
)


def relationship_allowed(
    rel_type: RelationshipType,
    subject: EntityCategory,
    obj: EntityCategory,
) -> bool:
    """Check whether a (subject, object) category pair is valid for a relationship type.

    Types without an explicit constraint list accept any category pair; the
    default-deny rule only applies where the ontology states a restriction.
    """
    allowed = RELATIONSHIP_CONSTRAINTS.get(rel_type)
    if allowed is None:
        return True
    return (subject, obj) in allowed
