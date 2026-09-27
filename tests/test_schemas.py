from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aegis.schemas.evidence import EvidenceCreate, SourceType


def test_evidence_schema_accepts_valid_record() -> None:
    record = EvidenceCreate(
        source_id=uuid4(),
        source_type=SourceType.SYNTHETIC,
        collected_at=datetime.now(UTC),
        raw_artifact_uri="s3://aegis/test/1",
        sha256="a" * 64,
        collector_name="synthetic",
        collector_version="0.1.0",
        source_reliability=0.8,
        independence_group="synthetic-1",
    )
    assert record.source_type == SourceType.SYNTHETIC


def test_evidence_schema_rejects_bad_hash() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(
            source_id=uuid4(),
            source_type=SourceType.SYNTHETIC,
            collected_at=datetime.now(UTC),
            raw_artifact_uri="s3://aegis/test/1",
            sha256="bad",
            collector_name="synthetic",
            collector_version="0.1.0",
            source_reliability=0.8,
            independence_group="synthetic-1",
        )
