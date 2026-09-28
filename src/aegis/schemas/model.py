"""Canonical model-run and calibration schemas (MLOps registry, spec §33)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from aegis.schemas.base import CanonicalModel


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ModelRun(CanonicalModel):
    """Immutable record of one training/evaluation/calibration run.

    Screenshots of terminal output are never experiment records; every run
    carries dataset/feature/model versions, seed, hyperparameters, metrics,
    git commit, and artifact paths.
    """

    CURRENT_VERSION = "1.0"
    MIGRATIONS = {
        # 0.9 omitted calibration and artifact paths.
        "0.9": lambda p: {**p, "calibration": p.get("calibration") or {},
                          "artifact_paths": p.get("artifact_paths") or [],
                          "schema_version": "1.0"},
    }

    run_id: UUID = Field(default_factory=uuid4)
    model_id: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=64)
    dataset_version: str = Field(min_length=1, max_length=64)
    feature_version: str = Field(min_length=1, max_length=64)
    git_commit: str = Field(min_length=7, max_length=64)
    seed: int
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    calibration: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: tuple[str, ...] = ()
    status: RunStatus = RunStatus.COMPLETED
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _ordered_timestamps(self) -> ModelRun:
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self

    @classmethod
    def example(cls) -> ModelRun:
        return cls(
            model_id="entity-resolution-baseline",
            model_version="baseline-0.1",
            dataset_version="synthetic-26151-v1",
            feature_version="pairs-0.1",
            git_commit="5cc97cc000000000000000000000000000000000",
            seed=26151,
            hyperparameters={"max_iter": 200},
            metrics={"f1": 0.81},
            calibration={"method": "platt", "brier": 0.12},
            artifact_paths=("models/entity-resolution-baseline-0.1.joblib",),
        )
