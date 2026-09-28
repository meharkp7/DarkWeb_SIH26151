"""Canonical hypothesis and attribution-assessment schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from aegis.schemas.base import CanonicalModel, migrate


class HypothesisKind(StrEnum):
    """Competing explanations tracked per case (spec §27)."""

    SAME_ACTOR = "same_actor"
    COLLABORATOR = "collaborator"
    IMPERSONATION = "impersonation"
    UNRELATED = "unrelated"


class HypothesisStatus(StrEnum):
    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EvidenceRole(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    UNKNOWN = "unknown"


class HypothesisEvidenceLink(CanonicalModel):
    """One evidence item's role in a hypothesis."""

    CURRENT_VERSION = "1.0"

    evidence_id: UUID
    role: EvidenceRole
    modality: str = Field(min_length=1, max_length=64)
    independence_group: str = Field(min_length=1, max_length=128)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)

    @classmethod
    def example(cls) -> HypothesisEvidenceLink:
        return cls(
            evidence_id=uuid4(),
            role=EvidenceRole.SUPPORTING,
            modality="handle",
            independence_group="platform:forum_alpha",
        )


class Hypothesis(CanonicalModel):
    """A reviewable attribution hypothesis with its evidence partition."""

    CURRENT_VERSION = "1.0"
    MIGRATIONS = {
        # 0.9 stored a flat ``evidence_ids`` list without roles.
        "0.9": lambda p: migrate(
            {
                **p,
                "links": [
                    {
                        "evidence_id": eid,
                        "role": "supporting",
                        "modality": "unknown",
                        "independence_group": "legacy",
                        "weight": 1.0,
                    }
                    for eid in p.pop("evidence_ids", []) or []
                ],
            },
            "1.0",
            drops=("evidence_ids",),
        ),
    }

    hypothesis_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    subject_entity_id: UUID
    object_entity_id: UUID
    kind: HypothesisKind
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    links: tuple[HypothesisEvidenceLink, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    """Modalities with no observation yet (e.g. ``stylometry``), never silently ignored."""
    analyst_disposition: str | None = Field(default=None, max_length=4096)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _distinct_entities(self) -> Hypothesis:
        if self.subject_entity_id == self.object_entity_id:
            raise ValueError("hypothesis must compare two distinct entities")
        return self

    @classmethod
    def example(cls) -> Hypothesis:
        return cls(
            case_id=uuid4(),
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            kind=HypothesisKind.SAME_ACTOR,
            links=(HypothesisEvidenceLink.example(),),
            missing_evidence=("stylometry",),
        )


class AttributionAssessment(CanonicalModel):
    """Model output for a hypothesis: raw score, calibrated confidence,
    modality signals, and the exact evidence that produced them.

    ``raw_score`` is deliberately *not* named ``probability``: until
    calibration runs, the value carries no probabilistic meaning.
    """

    CURRENT_VERSION = "1.0"

    assessment_id: UUID = Field(default_factory=uuid4)
    hypothesis_id: UUID
    case_id: UUID
    model_id: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=64)
    raw_score: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_version: str | None = None
    signals: dict[str, float] = Field(default_factory=dict)
    """Transparent per-modality inputs (S_h, S_p, S_w, S_t, S_b, S_i)."""
    supporting_evidence_ids: tuple[UUID, ...] = ()
    contradictory_evidence_ids: tuple[UUID, ...] = ()
    explanations: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _calibrated_implies_version(self) -> AttributionAssessment:
        if self.calibrated_confidence is not None and not self.calibration_version:
            raise ValueError("calibrated_confidence requires calibration_version")
        return self

    @classmethod
    def example(cls) -> AttributionAssessment:
        return cls(
            hypothesis_id=uuid4(),
            case_id=uuid4(),
            model_id="transparent-fusion",
            model_version="baseline-0.1",
            raw_score=0.84,
            signals={"S_h": 1.0, "S_w": 0.6},
            supporting_evidence_ids=(uuid4(),),
        )
