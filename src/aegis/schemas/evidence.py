from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class SourceType(StrEnum):
    PUBLIC_WEB = "public_web"
    FORUM = "forum"
    MARKETPLACE = "marketplace"
    THREAT_FEED = "threat_feed"
    ANALYST_SUBMITTED = "analyst_submitted"
    SYNTHETIC = "synthetic"


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: SourceType
    name: str = Field(min_length=1, max_length=256)
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None


class EvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: UUID | None = None
    source_id: UUID
    source_type: SourceType
    observed_at: datetime | None = None
    collected_at: datetime
    entity_type: str | None = None
    entity_value_hash: str | None = None
    context_hash: str | None = None
    raw_artifact_uri: str
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    collector_name: str
    collector_version: str
    normalizer_version: str | None = None
    extraction_version: str | None = None
    source_reliability: float = Field(ge=0.0, le=1.0)
    independence_group: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(EvidenceCreate):
    evidence_id: UUID = Field(default_factory=uuid4)
    artifact_id: UUID | None = None
    created_at: datetime | None = None


class EvidenceProvenance(BaseModel):
    evidence_id: UUID
    sha256: str
    artifact_uri: str
    parent_evidence_ids: list[UUID]
    derivation_count: int
