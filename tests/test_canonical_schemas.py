"""Canonical schema contract tests: serialization, rejection, versioning,
JSON round-trip (Implementation Plan Phase 02)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aegis.schemas import CANONICAL_SCHEMAS
from aegis.schemas.entity import Entity, Relationship
from aegis.schemas.evidence import EvidenceCreate, SourceCreate
from aegis.schemas.hypothesis import AttributionAssessment, Hypothesis, HypothesisKind
from aegis.schemas.model import ModelRun
from aegis.schemas.temporal import MigrationAssessment, TimelineEvent
from aegis.schemas.validation import run_schema_validation_suite


@pytest.mark.parametrize("name", sorted(CANONICAL_SCHEMAS))
def test_valid_serialization_round_trip(name: str) -> None:
    schema = CANONICAL_SCHEMAS[name]
    example = schema.example()

    assert schema.model_validate(example.model_dump()) == example
    assert schema.model_validate_json(example.model_dump_json()) == example


@pytest.mark.parametrize("name", sorted(CANONICAL_SCHEMAS))
def test_unknown_field_rejected(name: str) -> None:
    schema = CANONICAL_SCHEMAS[name]
    payload = schema.example().model_dump()
    payload["not_a_real_field"] = 1

    with pytest.raises(ValidationError):
        schema.model_validate(payload)


@pytest.mark.parametrize("name", sorted(CANONICAL_SCHEMAS))
def test_json_round_trip_is_stable(name: str) -> None:
    schema = CANONICAL_SCHEMAS[name]
    example = schema.example()

    first = example.model_dump_json()
    second = schema.model_validate_json(first).model_dump_json()

    assert json.loads(first) == json.loads(second)


def test_evidence_rejects_bad_hash() -> None:
    payload = EvidenceCreate.example().model_dump()
    payload["sha256"] = "deadbeef"

    with pytest.raises(ValidationError):
        EvidenceCreate.model_validate(payload)


def test_entity_rejects_unknown_ontology_type() -> None:
    payload = Entity.example().model_dump()
    payload["entity_type"] = "made_up_type"

    with pytest.raises(ValidationError):
        Entity.model_validate(payload)


def test_entity_rejects_inverted_time_window() -> None:
    payload = Entity.example().model_dump()
    payload["first_seen"] = "2026-06-01T00:00:00+00:00"
    payload["last_seen"] = "2026-01-01T00:00:00+00:00"

    with pytest.raises(ValidationError):
        Entity.model_validate(payload)


def test_relationship_requires_evidence_and_distinct_ends() -> None:
    payload = Relationship.example().model_dump()
    payload["evidence_ids"] = []

    with pytest.raises(ValidationError):
        Relationship.model_validate(payload)

    payload = Relationship.example().model_dump()
    same = payload["subject_entity_id"]
    payload["object_entity_id"] = same

    with pytest.raises(ValidationError):
        Relationship.model_validate(payload)


def test_hypothesis_requires_distinct_entities() -> None:
    payload = Hypothesis.example().model_dump()
    payload["object_entity_id"] = payload["subject_entity_id"]

    with pytest.raises(ValidationError):
        Hypothesis.model_validate(payload)


def test_assessment_requires_calibration_version_for_confidence() -> None:
    payload = AttributionAssessment.example().model_dump()
    payload["calibrated_confidence"] = 0.9

    with pytest.raises(ValidationError):
        AttributionAssessment.model_validate(payload)

    payload["calibration_version"] = "platt-v1"
    assert AttributionAssessment.model_validate(payload).calibration_version == "platt-v1"


def test_migration_rejects_inverted_window() -> None:
    payload = MigrationAssessment.example().model_dump()
    payload["change_window_start"] = "2026-05-01T00:00:00+00:00"
    payload["change_window_end"] = "2026-04-01T00:00:00+00:00"

    with pytest.raises(ValidationError):
        MigrationAssessment.model_validate(payload)


def test_timeline_rejects_inverted_interval() -> None:
    payload = TimelineEvent.example().model_dump()
    payload["ended_at"] = "2025-12-31T00:00:00+00:00"

    with pytest.raises(ValidationError):
        TimelineEvent.model_validate(payload)


# ----------------------------------------------------------------- versioning


def test_evidence_upgrades_from_0_9_hash_field() -> None:
    legacy = EvidenceCreate.example().model_dump()
    legacy["hash"] = legacy.pop("sha256")
    legacy["schema_version"] = "0.9"

    upgraded = EvidenceCreate.model_validate(legacy)

    assert upgraded.schema_version == "1.0"
    assert upgraded.sha256 == legacy["hash"]


def test_source_upgrades_from_0_9_independence_group() -> None:
    legacy = SourceCreate.example().model_dump()
    legacy.pop("independence_group")
    legacy["schema_version"] = "0.9"

    upgraded = SourceCreate.model_validate(legacy)

    assert upgraded.schema_version == "1.0"
    assert upgraded.independence_group.startswith("src-")


def test_entity_upgrades_from_0_9_type_field() -> None:
    legacy = Entity.example().model_dump()
    legacy["type"] = legacy.pop("entity_type")
    legacy["schema_version"] = "0.9"

    upgraded = Entity.model_validate(legacy)

    assert upgraded.entity_type.value == "handle"


def test_model_run_upgrades_from_0_9_without_calibration() -> None:
    legacy = ModelRun.example().model_dump()
    legacy.pop("calibration")
    legacy.pop("artifact_paths")
    legacy["schema_version"] = "0.9"

    upgraded = ModelRun.model_validate(legacy)

    assert upgraded.calibration == {}
    assert upgraded.artifact_paths == ()


def test_hypothesis_upgrades_from_flat_evidence_list() -> None:
    legacy = Hypothesis.example().model_dump()
    evidence_ids = [str(uuid4()), str(uuid4())]
    legacy.pop("links")
    legacy["evidence_ids"] = evidence_ids
    legacy["schema_version"] = "0.9"

    upgraded = Hypothesis.model_validate(legacy)

    assert upgraded.schema_version == "1.0"
    assert {str(link.evidence_id) for link in upgraded.links} == set(evidence_ids)
    assert all(link.role.value == "supporting" for link in upgraded.links)


def test_unsupported_version_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported schema_version"):
        Hypothesis.model_validate({**Hypothesis.example().model_dump(), "schema_version": "99.0"})


# ----------------------------------------------------------------- gate


@pytest.mark.parametrize("name", sorted(CANONICAL_SCHEMAS))
def test_schema_validation_suite_passes(name: str) -> None:
    result = run_schema_validation_suite(name, CANONICAL_SCHEMAS[name])
    assert result.ok, result.detail


def test_example_payloads_differ_per_instance() -> None:
    first = Hypothesis.example()
    second = Hypothesis.example()

    assert first.hypothesis_id != second.hypothesis_id
    assert first.kind is HypothesisKind.SAME_ACTOR
