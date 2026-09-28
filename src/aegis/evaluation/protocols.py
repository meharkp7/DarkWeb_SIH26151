"""Leakage-safe evaluation splits and migration-degradation reporting (Phase 21)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from aegis.evaluation.metrics import EvaluationMetrics
from aegis.synthetic.evidence import SyntheticEvidence
from aegis.synthetic.persona_simulator import MigrationLevel, PersonaMigration


@dataclass(frozen=True)
class EvaluationSplit:
    train: tuple[SyntheticEvidence, ...]
    test: tuple[SyntheticEvidence, ...]
    kind: str

    def __post_init__(self) -> None:
        if not self.train or not self.test:
            raise ValueError("evaluation splits require non-empty train and test partitions")


@dataclass(frozen=True)
class MigrationPerformance:
    level: MigrationLevel
    metrics: EvaluationMetrics
    f1_degradation: float


def temporal_split(evidence: Sequence[SyntheticEvidence], cutoff: datetime) -> EvaluationSplit:
    """Train strictly before *cutoff*, test at/after it; no temporal leakage."""
    train = tuple(item for item in evidence if item.observed_at < cutoff)
    test = tuple(item for item in evidence if item.observed_at >= cutoff)
    return EvaluationSplit(train, test, "temporal")


def platform_disjoint_split(
    evidence: Sequence[SyntheticEvidence], held_out_platforms: set[str]
) -> EvaluationSplit:
    """Hold out a source/platform family for cross-platform generalisation."""
    if not held_out_platforms or any(not platform.strip() for platform in held_out_platforms):
        raise ValueError("held_out_platforms must contain non-empty platform names")
    train = tuple(item for item in evidence if item.platform not in held_out_platforms)
    test = tuple(item for item in evidence if item.platform in held_out_platforms)
    return EvaluationSplit(train, test, "platform-disjoint")


def migration_degradation(
    baseline: EvaluationMetrics,
    migrations: Sequence[PersonaMigration],
    evaluate: Callable[[MigrationLevel, Sequence[PersonaMigration]], EvaluationMetrics],
) -> tuple[MigrationPerformance, ...]:
    """Evaluate each L1–L5 cohort and report F1 loss from clean performance."""
    by_level: dict[MigrationLevel, list[PersonaMigration]] = {}
    for migration in migrations:
        by_level.setdefault(migration.level, []).append(migration)
    if set(by_level) != set(MigrationLevel):
        raise ValueError("migration evaluation requires every L1–L5 level")
    results = []
    for level in MigrationLevel:
        metrics = evaluate(level, tuple(by_level[level]))
        results.append(
            MigrationPerformance(
                level=level,
                metrics=metrics,
                f1_degradation=round(max(0.0, baseline.f1 - metrics.f1), 3),
            )
        )
    return tuple(results)
