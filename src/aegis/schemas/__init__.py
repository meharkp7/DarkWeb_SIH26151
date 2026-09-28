"""Canonical schema registry.

Every AEGIS service imports its contracts from here. No service may
invent its own evidence schema.
"""

from __future__ import annotations

from aegis.schemas.base import CanonicalModel
from aegis.schemas.entity import Entity, EntitySpan, Relationship
from aegis.schemas.evidence import (
    Case,
    CaseCreate,
    CaseStatus,
    Evidence,
    EvidenceCreate,
    EvidenceProvenance,
    Observation,
    Source,
    SourceCreate,
    SourceTier,
    SourceType,
)
from aegis.schemas.hypothesis import (
    AttributionAssessment,
    EvidenceRole,
    Hypothesis,
    HypothesisEvidenceLink,
    HypothesisKind,
    HypothesisStatus,
)
from aegis.schemas.model import ModelRun, RunStatus
from aegis.schemas.temporal import (
    ChangeMethod,
    ChangePoint,
    MigrationAssessment,
    MigrationStatus,
    TimelineEvent,
)

CANONICAL_SCHEMAS: dict[str, type[CanonicalModel]] = {
    "Case": Case,
    "CaseCreate": CaseCreate,
    "ChangePoint": ChangePoint,
    "AttributionAssessment": AttributionAssessment,
    "Entity": Entity,
    "EntitySpan": EntitySpan,
    "Evidence": Evidence,
    "EvidenceCreate": EvidenceCreate,
    "EvidenceProvenance": EvidenceProvenance,
    "Hypothesis": Hypothesis,
    "HypothesisEvidenceLink": HypothesisEvidenceLink,
    "MigrationAssessment": MigrationAssessment,
    "ModelRun": ModelRun,
    "Observation": Observation,
    "Relationship": Relationship,
    "Source": Source,
    "SourceCreate": SourceCreate,
    "TimelineEvent": TimelineEvent,
}

__all__ = [
    "AttributionAssessment",
    "CANONICAL_SCHEMAS",
    "CanonicalModel",
    "Case",
    "CaseCreate",
    "CaseStatus",
    "ChangeMethod",
    "ChangePoint",
    "Entity",
    "EntitySpan",
    "Evidence",
    "EvidenceCreate",
    "EvidenceProvenance",
    "EvidenceRole",
    "Hypothesis",
    "HypothesisEvidenceLink",
    "HypothesisKind",
    "HypothesisStatus",
    "MigrationAssessment",
    "MigrationStatus",
    "ModelRun",
    "Observation",
    "Relationship",
    "RunStatus",
    "Source",
    "SourceCreate",
    "SourceTier",
    "SourceType",
    "TimelineEvent",
]
