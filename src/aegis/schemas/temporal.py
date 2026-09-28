"""Canonical temporal schemas: timeline events, change points, migrations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from aegis.schemas.base import CanonicalModel, migrate


class TimelineEvent(CanonicalModel):
    """An interval-aware event attached to an entity for timeline queries."""

    CURRENT_VERSION = "1.0"
    MIGRATIONS = {
        # 0.9 used naive ``timestamp``.
        "0.9": lambda p: migrate(p, "1.0", renames=(("timestamp", "occurred_at"),)),
    }

    event_id: UUID = Field(default_factory=uuid4)
    case_id: UUID | None = None
    entity_id: UUID
    event_type: str = Field(min_length=1, max_length=64)
    occurred_at: datetime
    ended_at: datetime | None = None
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=8192)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ids: tuple[UUID, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_interval(self) -> TimelineEvent:
        if self.ended_at and self.ended_at < self.occurred_at:
            raise ValueError("ended_at must not precede occurred_at")
        return self

    @classmethod
    def example(cls) -> TimelineEvent:
        return cls(
            entity_id=uuid4(),
            event_type="first_observed",
            occurred_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
            title="Handle first observed on forum_alpha",
            evidence_ids=(uuid4(),),
        )


class ChangeMethod(StrEnum):
    CUSUM = "cusum"
    JS_DIVERGENCE = "js_divergence"
    BINARY_SEGMENTATION = "binary_segmentation"
    RUPTURES = "ruptures"


class ChangePoint(CanonicalModel):
    """A detected discontinuity in an entity's observed behaviour."""

    CURRENT_VERSION = "1.0"

    change_point_id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    feature: str = Field(min_length=1, max_length=128)
    detected_at: datetime
    method: ChangeMethod
    magnitude: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    pre_window_start: datetime | None = None
    pre_window_end: datetime | None = None
    post_window_start: datetime | None = None
    post_window_end: datetime | None = None
    evidence_ids: tuple[UUID, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def example(cls) -> ChangePoint:
        return cls(
            entity_id=uuid4(),
            feature="posting_rate",
            detected_at=datetime.fromisoformat("2026-04-01T00:00:00+00:00"),
            method=ChangeMethod.CUSUM,
            magnitude=3.2,
            confidence=0.87,
        )


class MigrationStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class MigrationAssessment(CanonicalModel):
    """Persona-migration hypothesis between two identities over a window."""

    CURRENT_VERSION = "1.0"

    migration_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    old_entity_id: UUID
    new_entity_id: UUID
    change_window_start: datetime
    change_window_end: datetime
    status: MigrationStatus = MigrationStatus.CANDIDATE
    confidence: float = Field(ge=0.0, le=1.0)
    signals: dict[str, float] = Field(default_factory=dict)
    supporting_evidence_ids: tuple[UUID, ...] = ()
    contradictory_evidence_ids: tuple[UUID, ...] = ()
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _check_window(self) -> MigrationAssessment:
        if self.change_window_end < self.change_window_start:
            raise ValueError("change_window_end must not precede change_window_start")
        if self.old_entity_id == self.new_entity_id:
            raise ValueError("migration must reference two distinct entities")
        return self

    @classmethod
    def example(cls) -> MigrationAssessment:
        return cls(
            case_id=uuid4(),
            old_entity_id=uuid4(),
            new_entity_id=uuid4(),
            change_window_start=datetime.fromisoformat("2026-03-01T00:00:00+00:00"),
            change_window_end=datetime.fromisoformat("2026-04-01T00:00:00+00:00"),
            confidence=0.71,
            signals={"stylometry": 0.82, "behavior": 0.64},
        )
