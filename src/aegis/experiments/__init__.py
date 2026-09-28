"""Experiment & baseline registry (plan section 35).

Every training run registers exactly one :class:`ExperimentRecord` —
experiment id, dataset/feature/model versions, seed, hyperparameters,
metrics, git commit, timestamp, and the frozen report — so any metric
can be traced back to precisely what produced it. The artifact written
by a training script *is* the registry entry (same payload, JSON).

-   :func:`deterministic_experiment_id` derives a filesystem-safe,
    collision-resistant id from a run's identity (name, dataset version,
    seed): identical inputs always produce the same id.
-   :class:`ExperimentRegistry` is the in-memory registry: register
    once, look up and list forever; re-registering an id raises
    :class:`DuplicateExperimentError` rather than silently overwriting
    the provenance of an earlier run.

``scripts/train_baselines.py`` is the first consumer — it registers the
frozen Phase 09 resolution-baseline report through this package.
"""

from aegis.experiments.registry import (
    DuplicateExperimentError,
    ExperimentRecord,
    ExperimentRegistry,
    current_git_commit,
    deterministic_experiment_id,
)

__all__ = [
    "DuplicateExperimentError",
    "ExperimentRecord",
    "ExperimentRegistry",
    "current_git_commit",
    "deterministic_experiment_id",
]
