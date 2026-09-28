"""Unit tests for the experiment/baseline registry (H5): registration,
deterministic ids, lookup/listing, duplicate rejection, payloads."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

from aegis.experiments import (
    DuplicateExperimentError,
    ExperimentRecord,
    ExperimentRegistry,
    current_git_commit,
    deterministic_experiment_id,
)

#: Frozen key set of the registry entry (resolution_baselines.json).
PAYLOAD_KEYS = {
    "experiment_id",
    "dataset_version",
    "feature_version",
    "model_version",
    "seed",
    "hyperparameters",
    "metrics",
    "git_commit",
    "created_at",
    "report",
}


def _record(experiment_id: str = "exp-1", *, seed: int = 26151) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment_id,
        dataset_version=f"synthetic-corpus-seed-{seed}",
        feature_version="resolution-features-v1",
        model_version="baselines-v1",
        seed=seed,
        hyperparameters={"k": 5, "use_graph": True},
        metrics={"exact_handle": {"f1": 1.0}},
        git_commit="0" * 40,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        report={"baselines": []},
    )


def test_register_then_get_and_list() -> None:
    registry = ExperimentRegistry()
    record = _record()

    registered = registry.register(record)

    assert registered is record
    assert registry.get("exp-1") is record
    assert "exp-1" in registry
    assert len(registry) == 1


def test_list_is_deterministically_sorted() -> None:
    registry = ExperimentRegistry()
    for experiment_id in ("zeta", "alpha", "mid"):
        registry.register(_record(experiment_id))

    assert [record.experiment_id for record in registry.list()] == ["alpha", "mid", "zeta"]


def test_duplicate_registration_raises_instead_of_overwriting() -> None:
    registry = ExperimentRegistry()
    registry.register(_record("dup", seed=1))

    with pytest.raises(DuplicateExperimentError, match="already registered"):
        registry.register(_record("dup", seed=2))

    # the original record survives untouched
    assert registry.get("dup").seed == 1
    assert len(registry) == 1


def test_lookup_of_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError, match="unknown experiment"):
        ExperimentRegistry().get("missing")


def test_deterministic_experiment_id_is_stable_and_input_sensitive() -> None:
    first = deterministic_experiment_id(
        "Phase 09 Baselines!", dataset_version="corpus-v1", seed=26151
    )
    second = deterministic_experiment_id(
        "phase 09 baselines", dataset_version="corpus-v1", seed=26151
    )
    assert first == second
    assert re.fullmatch(r"[a-z0-9-]+", first), "id must be filesystem-safe"

    # different seed or dataset -> different id (no silent collisions)
    assert first != deterministic_experiment_id(
        "Phase 09 Baselines!", dataset_version="corpus-v1", seed=26152
    )
    assert first != deterministic_experiment_id(
        "Phase 09 Baselines!", dataset_version="corpus-v2", seed=26151
    )
    # different name -> different id
    assert first != deterministic_experiment_id(
        "Phase 10 Retrieval", dataset_version="corpus-v1", seed=26151
    )


def test_deterministic_experiment_id_rejects_empty_names() -> None:
    with pytest.raises(ValueError, match="alphanumeric"):
        deterministic_experiment_id("!!!", dataset_version="v1", seed=1)


def test_record_copies_its_mappings() -> None:
    hyperparameters = {"k": 5}
    record = ExperimentRecord(
        experiment_id="copy",
        dataset_version="d",
        feature_version="f",
        model_version="m",
        seed=1,
        hyperparameters=hyperparameters,
    )
    hyperparameters["k"] = 99

    assert record.hyperparameters["k"] == 5


def test_payload_is_json_ready_with_the_frozen_key_set() -> None:
    payload = _record().to_payload()

    assert set(payload) == PAYLOAD_KEYS
    assert payload["created_at"] == datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    assert json.loads(json.dumps(payload)) == payload


def test_empty_experiment_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="experiment_id"):
        _record("   ")


def test_current_git_commit_returns_hex_or_unknown() -> None:
    commit = current_git_commit()
    assert commit == "unknown" or re.fullmatch(r"[0-9a-f]{7,40}", commit)
