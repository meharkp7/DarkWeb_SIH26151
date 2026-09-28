"""Canonical entity and relationship schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from aegis.ontology import EntityCategory, EntityType, RelationshipType, relationship_allowed
from aegis.schemas.base import CanonicalModel, migrate


class EntitySpan(CanonicalModel):
    """Character span inside an evidence artifact, kept so an analyst can
    inspect exactly why an entity was extracted."""

    CURRENT_VERSION = "1.0"

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    field: str = Field(default="body", max_length=64)

    @model_validator(mode="after")
    def _check_bounds(self) -> EntitySpan:
        if self.end < self.start:
            raise ValueError("span end must be >= span start")
        return self

    @classmethod
    def example(cls) -> EntitySpan:
        return cls(start=0, end=5)


class Entity(CanonicalModel):
    """A typed entity extracted from evidence, with provenance."""

    CURRENT_VERSION = "1.0"
    MIGRATIONS = {
        # 0.9 stored the ontology type as free-form ``type``.
        "0.9": lambda p: migrate(p, "1.0", renames=(("type", "entity_type"),)),
    }

    entity_id: UUID = Field(default_factory=uuid4)
    entity_type: EntityType
    surface_form: str = Field(min_length=1, max_length=1024)
    normalized_form: str = Field(min_length=1, max_length=1024)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_id: UUID
    span: EntitySpan | None = None
    case_id: UUID | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_window(self) -> Entity:
        if self.first_seen and self.last_seen and self.last_seen < self.first_seen:
            raise ValueError("last_seen must not precede first_seen")
        return self

    @classmethod
    def example(cls) -> Entity:
        return cls(
            entity_type=EntityType.HANDLE,
            surface_form="ghostbroker",
            normalized_form="ghostbroker",
            confidence=0.97,
            evidence_id=uuid4(),
            span=EntitySpan(start=14, end=25),
        )


class Relationship(CanonicalModel):
    """A temporally bounded, evidence-backed typed edge."""

    CURRENT_VERSION = "1.0"
    MIGRATIONS = {
        # 0.9 called evidence references ``evidence`` instead of ``evidence_ids``.
        "0.9": lambda p: migrate(p, "1.0", renames=(("evidence", "evidence_ids"),)),
    }

    relationship_id: UUID = Field(default_factory=uuid4)
    subject_entity_id: UUID
    object_entity_id: UUID
    relationship_type: RelationshipType
    first_seen: datetime
    last_seen: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    case_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_temporal(self) -> Relationship:
        if self.last_seen < self.first_seen:
            raise ValueError("last_seen must not precede first_seen")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not precede valid_from")
        if self.subject_entity_id == self.object_entity_id:
            raise ValueError("a relationship cannot connect an entity to itself")
        return self

    @classmethod
    def example(cls) -> Relationship:
        return cls(
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            relationship_type=RelationshipType.USES_HANDLE,
            first_seen=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
            last_seen=datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
            confidence=0.9,
            evidence_ids=(uuid4(),),
        )


def validate_relationship_categories(
    rel_type: RelationshipType,
    subject_category: str,
    object_category: str,
) -> bool:
    """Bridge helper for services that only carry category strings."""
    try:
        subject = EntityCategory(subject_category)
        obj = EntityCategory(object_category)
    except ValueError:
        return False
    return relationship_allowed(rel_type, subject, obj)
