"""Phase 17 contradiction-aware attribution evidence fusion."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from aegis.attribution.signals import sigmoid
from aegis.schemas.hypothesis import EvidenceRole


@dataclass(frozen=True)
class EvidenceContribution:
    evidence_id: str
    role: EvidenceRole
    reliability: float = 1.0
    quality: float = 1.0
    temporal_fit: float = 1.0
    independence_group: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must not be empty")
        for name in ("reliability", "quality", "temporal_fit"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and within [0, 1]")


@dataclass(frozen=True)
class FusionResult:
    raw_score: float
    supporting_weight: float
    contradictory_weight: float
    unknown_weight: float
    supporting_evidence_ids: tuple[str, ...]
    contradictory_evidence_ids: tuple[str, ...]
    unknown_evidence_ids: tuple[str, ...]


def _independence_discount(items: Sequence[EvidenceContribution]) -> list[float]:
    counts: dict[str, int] = {}
    for item in items:
        if item.independence_group:
            counts[item.independence_group] = counts.get(item.independence_group, 0) + 1

    return [
        1.0 / (counts[item.independence_group] ** 2) if item.independence_group else 1.0
        for item in items
    ]


def fuse_evidence(
    evidence: Sequence[EvidenceContribution],
    *,
    alpha: float = 1.0,
    beta: float = 1.0,
) -> FusionResult:
    """Fuse support and contradiction without treating copied evidence as independent."""
    if alpha < 0.0 or beta < 0.0 or not math.isfinite(alpha + beta):
        raise ValueError("alpha and beta must be finite and non-negative")

    discounts = _independence_discount(evidence)
    support = 0.0
    contradiction = 0.0
    unknown = 0.0
    supporting_ids: list[str] = []
    contradictory_ids: list[str] = []
    unknown_ids: list[str] = []

    for item, discount in zip(evidence, discounts, strict=True):
        weight = item.reliability * item.quality * item.temporal_fit * discount
        if item.role is EvidenceRole.SUPPORTING:
            support += weight
            supporting_ids.append(item.evidence_id)
        elif item.role is EvidenceRole.CONTRADICTING:
            contradiction += weight
            contradictory_ids.append(item.evidence_id)
        else:
            unknown += weight
            unknown_ids.append(item.evidence_id)

    raw_score = sigmoid(alpha * support - beta * contradiction)
    return FusionResult(
        raw_score=round(raw_score, 6),
        supporting_weight=round(support, 6),
        contradictory_weight=round(contradiction, 6),
        unknown_weight=round(unknown, 6),
        supporting_evidence_ids=tuple(supporting_ids),
        contradictory_evidence_ids=tuple(contradictory_ids),
        unknown_evidence_ids=tuple(unknown_ids),
    )
