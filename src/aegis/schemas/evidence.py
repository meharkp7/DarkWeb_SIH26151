"""Canonical evidence, source, case, and observation schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from aegis.schemas.base import CanonicalModel, migrate


class SourceType(StrEnum):
    PUBLIC_WEB = "public_web"
    FORUM = "forum"
    MARKETPLACE = "marketplace"
    THREAT_FEED = "threat_feed"
    ANALYST_SUBMITTED = "analyst_submitted"
    SYNTHETIC = "synthetic"


class SourceTier(StrEnum):
    """Data-source policy tiers (docs/data-source-policy.md)."""

    A_SYNTHETIC = "A"
    B_PUBLIC_RESEARCH = "B"
    C_AUTHORIZED = "C"
    D_ANALYST_SUBMITTED = "D"
    E_RESTRICTED = "E"


class Source(CanonicalModel):
    """Canonical registry entry for a data source."""

    CURRENT_VERSION = "1.0"

    source_id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    name: str = Field(min_length=1, max_length=256)
    tier: SourceTier = SourceTier.A_SYNTHETIC
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    independence_group: str = Field(min_length=1, max_length=128)
    license_reference: str | None = None
    authorization_reference: str | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    @classmethod
    def example(cls) -> Source:
        return cls(
            source_type=SourceType.SYNTHETIC,
            name="AEGIS Synthetic Forum",
            tier=SourceTier.A_SYNTHETIC,
            reliability=1.0,
            independence_group="synthetic-forum-1",
        )


class CaseStatus(StrEnum):
    OPEN = "open"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CLOSED = "closed"
    ARCHIVED = "archived"


class Case(CanonicalModel):
    """Canonical investigation case."""

    CURRENT_VERSION = "1.0"

    case_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    status: CaseStatus = CaseStatus.OPEN
    tags: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def example(cls) -> Case:
        return cls(name="SIH-26151 synthetic rehearsal", tags=("rehearsal",))


class SourceCreate(CanonicalModel):
    """API payload for registering a source."""

    CURRENT_VERSION = "1.0"
    MIGRATIONS = {
        # 0.9 did not carry independence groups; derive one from the name.
        "0.9": lambda p: {
            **p,
            "independence_group": p.get("independence_group") or f"src-{p.get('name', 'unknown')}",
            "schema_version": "1.0",
        },
    }

    source_type: SourceType
    name: str = Field(min_length=1, max_length=256)
    tier: SourceTier = SourceTier.C_AUTHORIZED
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    independence_group: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def example(cls) -> SourceCreate:
        return cls(source_type=SourceType.SYNTHETIC, name="AEGIS Synthetic Generator")


class CaseCreate(CanonicalModel):
    """API payload for creating a case."""

    CURRENT_VERSION = "1.0"

    name: str = Field(min_length=1, max_length=256)
    description: str | None = None

    @classmethod
    def example(cls) -> CaseCreate:
        return cls(name="New investigation")


class EvidenceCreate(CanonicalModel):
    """API payload appending an immutable evidence record."""

    CURRENT_VERSION = "1.0"
    MIGRATIONS = {
        # 0.9 called the digest field ``hash``.
        "0.9": lambda p: migrate(p, "1.0", renames=(("hash", "sha256"),)),
    }

    case_id: UUID | None = None
    source_id: UUID
    source_type: SourceType
    observed_at: datetime | None = None
    collected_at: datetime
    entity_type: str | None = None
    entity_value_hash: str | None = None
    context_hash: str | None = None
    raw_artifact_uri: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    collector_name: str = Field(min_length=1, max_length=128)
    collector_version: str = Field(min_length=1, max_length=64)
    normalizer_version: str | None = None
    extraction_version: str | None = None
    source_reliability: float = Field(ge=0.0, le=1.0)
    independence_group: str = Field(min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def example(cls) -> EvidenceCreate:
        return cls(
            source_id=uuid4(),
            source_type=SourceType.SYNTHETIC,
            collected_at=datetime.fromisoformat("2026-09-28T00:00:00+00:00"),
            raw_artifact_uri="s3://aegis/evidence/2026/09/case/evidence/raw",
            sha256="a" * 64,
            collector_name="synthetic",
            collector_version="0.1.0",
            source_reliability=0.8,
            independence_group="synthetic-1",
        )


class Evidence(EvidenceCreate):
    """Immutable evidence record as returned by the evidence service."""

    CURRENT_VERSION = "1.0"

    evidence_id: UUID = Field(default_factory=uuid4)
    artifact_id: UUID | None = None
    created_at: datetime | None = None

    @classmethod
    def example(cls) -> Evidence:
        base = EvidenceCreate.example()
        return cls(**base.model_dump(), evidence_id=uuid4())


class EvidenceProvenance(CanonicalModel):
    CURRENT_VERSION = "1.0"

    evidence_id: UUID
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    artifact_uri: str
    parent_evidence_ids: tuple[UUID, ...] = ()
    derivation_count: int = Field(ge=0)

    @classmethod
    def example(cls) -> EvidenceProvenance:
        return cls(
            evidence_id=uuid4(),
            sha256="b" * 64,
            artifact_uri="file:///tmp/artifact",
            derivation_count=0,
        )


class Observation(CanonicalModel):
    """Normalized observation produced by Phase 06 normalization.

    One evidence artifact can yield several observations; the observation
    carries the deduplication and lineage signals that later stages use to
    discount non-independent corroboration.
    """

    CURRENT_VERSION = "1.0"

    observation_id: UUID = Field(default_factory=uuid4)
    evidence_id: UUID
    content_hash: str = Field(
        pattern=r"^[a-fA-F0-9]{64}$", description="SHA-256 of canonical encoding"
    )
    normalized_hash: str = Field(
        pattern=r"^[a-fA-F0-9]{64}$", description="SHA-256 of normalized text"
    )
    simhash: int = Field(ge=0, le=2**64 - 1, description="64-bit SimHash fingerprint")
    minhash_signatures: tuple[int, ...] = ()
    duplicate_cluster_id: str = Field(min_length=1, max_length=128)
    source_lineage: tuple[str, ...] = ()
    independence_group: str = Field(min_length=1, max_length=128)
    normalization_version: str = Field(min_length=1, max_length=64)
    observed_at: datetime | None = None
    collected_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def example(cls) -> Observation:
        return cls(
            evidence_id=uuid4(),
            content_hash="c" * 64,
            normalized_hash="d" * 64,
            simhash=123456789,
            duplicate_cluster_id="cluster-1",
            independence_group="synthetic-1",
            normalization_version="0.1.0",
            collected_at=datetime.fromisoformat("2026-09-28T00:00:00+00:00"),
        )
