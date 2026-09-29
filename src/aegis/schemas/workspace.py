"""Response schema for ``GET /api/v1/cases/{case_id}/workspace``.

The workspace endpoint used to return an untyped ``dict[str, object]``. That
is what let its evidence blocks drift from the frontend's ``WorkspaceEvidence``
interface: the serializer quietly omitted ``observed_at``, ``entity_type``,
``independence_group`` and ``metadata`` while the client was typed as if they
were always present, and nothing failed until a screen read one of them.

Declaring the shape here makes the contract explicit, puts it in OpenAPI, and
turns a missing field into a test failure rather than an undefined at runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aegis.schemas.evidence import CasePriority, CaseSeverity, CaseStatus


class WorkspaceCase(BaseModel):
    """The case header, including the triage state added in migration 0004."""

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    name: str
    description: str | None
    status: CaseStatus
    priority: CasePriority
    severity: CaseSeverity
    tags: list[str]
    assigned_to: str | None
    sla_due_at: datetime | None
    closed_at: datetime | None
    closure_reason: str | None
    created_at: datetime
    updated_at: datetime | None
    sla_overdue: bool


class WorkspaceEvidence(BaseModel):
    """One collected observation.

    ``observed_at`` is when the content was seen on the source and
    ``collected_at`` is when AEGIS ingested it; the gap is the collection
    latency, so a timeline cannot be built from one without the other.
    ``independence_group`` identifies sources that are not truly separate
    corroboration, which is what stops a confidence figure from being read as
    stronger than the evidence behind it supports.
    """

    model_config = ConfigDict(frozen=True)

    evidence_id: UUID
    source_id: UUID
    source_type: str
    observed_at: datetime | None
    collected_at: datetime
    entity_type: str | None
    reliability: float
    independence_group: str
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: UUID
    type: str
    surface_form: str
    normalized_form: str
    confidence: float


class WorkspaceRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    relationship_id: UUID
    subject_entity_id: UUID
    object_entity_id: UUID
    type: str
    confidence: float
    first_seen: datetime
    last_seen: datetime
    evidence_ids: list[UUID]


class WorkspaceAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_id: UUID
    hypothesis_id: UUID
    model_id: str
    model_version: str
    raw_score: float
    calibrated_confidence: float
    signals: dict[str, Any]
    explanations: list[str]
    limitations: list[str]
    supporting_evidence_ids: list[UUID]
    contradictory_evidence_ids: list[UUID]


class WorkspaceActivity(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    occurred_at: datetime
    action: str
    entity_type: str | None
    entity_id: str | None
    payload: dict[str, Any]


class WorkspaceResponse(BaseModel):
    """Everything the Investigation Workspace needs, in one round trip."""

    model_config = ConfigDict(frozen=True)

    case: WorkspaceCase
    counts: dict[str, int]
    evidence: list[WorkspaceEvidence]
    entities: list[WorkspaceEntity]
    relationships: list[WorkspaceRelationship]
    assessments: list[WorkspaceAssessment]
    activity: list[WorkspaceActivity]
