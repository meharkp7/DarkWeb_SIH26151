"""Registry primitives: records, deterministic ids, and registration.

See :mod:`aegis.experiments` for the package-level contract. This module
owns the two invariants that make a registry trustworthy:

1.  **Ids are deterministic** — derived from the run's identity, never
    from wall-clock time or a counter, so re-running the same
    configuration yields the same id.
2.  **Ids are unique** — a second registration under an existing id
    raises instead of overwriting, because a registry entry is evidence
    of what produced a metric.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class DuplicateExperimentError(RuntimeError):
    """Two runs tried to claim the same experiment id."""


def deterministic_experiment_id(
    name: str,
    *,
    dataset_version: str,
    seed: int,
) -> str:
    """Deterministic id for a run: slugified *name* + short stable hash.

    The hash covers the run's full identity (slug, dataset version,
    seed), so identical inputs always map to one id while a changed
    dataset or seed maps to a different one — no silent collisions and
    no dependence on registration order.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not slug:
        raise ValueError("experiment name must contain at least one alphanumeric character")
    digest = hashlib.sha256(f"{slug}|{dataset_version}|{seed}".encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def current_git_commit(*, cwd: str | Path = ".") -> str:
    """HEAD commit of the checkout that produced a run.

    Returns ``"unknown"`` when git or the checkout is unavailable — a
    missing provenance detail must never fail a training run.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


@dataclass(frozen=True)
class ExperimentRecord:
    """One registered run — the registry entry of plan section 35.

    ``to_payload()`` yields the JSON-ready entry whose keys are frozen
    by the first consumer (``resolution_baselines.json``): experiment
    id, dataset/feature/model versions, seed, hyperparameters, metrics,
    git commit, creation timestamp, and the full report.
    """

    experiment_id: str
    dataset_version: str
    feature_version: str
    model_version: str
    seed: int
    hyperparameters: Mapping[str, object] = field(default_factory=dict)
    metrics: Mapping[str, object] = field(default_factory=dict)
    git_commit: str = "unknown"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    report: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.experiment_id.strip():
            raise ValueError("experiment_id must be a non-empty string")
        # Copy the mappings so a caller cannot mutate a registered record.
        object.__setattr__(self, "hyperparameters", dict(self.hyperparameters))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "report", dict(self.report))

    def to_payload(self) -> dict[str, object]:
        """JSON-serializable registry entry (stable key set)."""
        return {
            "experiment_id": self.experiment_id,
            "dataset_version": self.dataset_version,
            "feature_version": self.feature_version,
            "model_version": self.model_version,
            "seed": self.seed,
            "hyperparameters": dict(self.hyperparameters),
            "metrics": dict(self.metrics),
            "git_commit": self.git_commit,
            "created_at": self.created_at.isoformat(),
            "report": dict(self.report),
        }


class ExperimentRegistry:
    """Register-once, lookup/list registry keyed by experiment id."""

    def __init__(self) -> None:
        self._records: dict[str, ExperimentRecord] = {}

    def register(self, record: ExperimentRecord) -> ExperimentRecord:
        """Add *record* and return it.

        Raises :class:`DuplicateExperimentError` when the id is already
        registered — overwriting would destroy the provenance of the
        earlier run.
        """
        if record.experiment_id in self._records:
            raise DuplicateExperimentError(
                f"experiment {record.experiment_id!r} is already registered; "
                "register the run under a distinct id instead of overwriting"
            )
        self._records[record.experiment_id] = record
        return record

    def get(self, experiment_id: str) -> ExperimentRecord:
        """The record for *experiment_id*; raises ``KeyError`` when absent."""
        try:
            return self._records[experiment_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown experiment {experiment_id!r}; registered: {sorted(self._records)}"
            ) from exc

    def list(self) -> tuple[ExperimentRecord, ...]:
        """Every record in deterministic (id-sorted) order."""
        return tuple(self._records[key] for key in sorted(self._records))

    def __contains__(self, experiment_id: object) -> bool:
        return experiment_id in self._records

    def __len__(self) -> int:
        return len(self._records)
