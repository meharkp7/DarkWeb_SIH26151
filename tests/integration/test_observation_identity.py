"""Observation identity regression tests (review findings 🔴 #1).

Evidence rows are observations keyed by (source_id, sha256, observed_at):
the same content re-observed from another source or at a later scan is a
new record, while an identical re-submit of the same observation conflicts.
Content identity stays on artifacts.sha256.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from aegis.evidence.artifacts import ArtifactStore
from aegis.evidence.service import EvidenceService
from aegis.schemas.evidence import EvidenceCreate, SourceCreate, SourceType
from aegis.settings import settings

pytestmark = pytest.mark.integration

CONTENT = b"observation identity fixture"


def _payload(source_id, observed_at: datetime, digest: str) -> EvidenceCreate:
    return EvidenceCreate(
        source_id=source_id,
        source_type=SourceType.SYNTHETIC,
        observed_at=observed_at,
        collected_at=datetime.now(UTC),
        raw_artifact_uri="synthetic://observation-identity",
        sha256=digest,
        collector_name="observation-identity-test",
        collector_version="0.1.0",
        source_reliability=1.0,
        independence_group="observation-identity",
    )


def test_same_content_from_other_source_is_new_observation(tmp_path) -> None:
    from aegis.db.session import SessionLocal

    db = SessionLocal()
    store = ArtifactStore(f"{settings.evidence_storage_path}/obs-identity-a")
    service = EvidenceService(db, store)
    now = datetime.now(UTC)
    digest = sha256(CONTENT).hexdigest()

    source_a = service.create_source(
        SourceCreate(source_type=SourceType.SYNTHETIC, name="obs-A", reliability=1.0)
    )
    source_b = service.create_source(
        SourceCreate(source_type=SourceType.SYNTHETIC, name="obs-B", reliability=1.0)
    )
    try:
        first = service.create_evidence(_payload(source_a.source_id, now, digest), CONTENT)
        # Same bytes, different source: a distinct observation, not a 409.
        second = service.create_evidence(_payload(source_b.source_id, now, digest), CONTENT)
        assert first.evidence_id != second.evidence_id
        assert first.sha256 == second.sha256 == digest

        # Same bytes, same source, later scan: also a distinct observation.
        later = service.create_evidence(
            _payload(source_a.source_id, now + timedelta(hours=1), digest), CONTENT
        )
        assert later.evidence_id != first.evidence_id

        # Identical observation re-submit: conflict (idempotent ingest guard).
        with pytest.raises(ValueError, match="already observed"):
            service.create_evidence(_payload(source_a.source_id, now, digest), CONTENT)

        # Content lookup still finds a record with this digest.
        found = service.get_by_sha256(digest)
        assert found is not None
        assert found.sha256 == digest

        # Observation lookup is source+time scoped.
        assert service.get_observation(digest, source_a.source_id, now) is not None
        assert service.get_observation(digest, source_b.source_id, now) is not None
        assert service.get_observation(digest, source_a.source_id, now - timedelta(days=1)) is None
    finally:
        db.rollback()
        db.close()


def test_server_side_hash_mismatch_rejected_without_orphan(tmp_path) -> None:
    from aegis.db.session import SessionLocal

    db = SessionLocal()
    store = ArtifactStore(f"{settings.evidence_storage_path}/obs-identity-b")
    service = EvidenceService(db, store)
    now = datetime.now(UTC)
    declared = sha256(b"what the client claims").hexdigest()
    source = service.create_source(
        SourceCreate(source_type=SourceType.SYNTHETIC, name="obs-C", reliability=1.0)
    )
    try:
        # Bytes do not match the declared digest: server-side verification
        # must reject before any artifact object or evidence row is written.
        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            service.create_evidence(_payload(source.source_id, now, declared), CONTENT)
        assert service.get_by_sha256(declared) is None
    finally:
        db.rollback()
        db.close()
