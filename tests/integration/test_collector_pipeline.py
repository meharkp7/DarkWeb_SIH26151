"""Phase 05 exit criterion against a real database:

    synthetic source -> collector -> evidence

The collector layer stays decoupled; only the ingest bridge touches the
ledger.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete, select

from aegis.collection import (
    CollectionIngestor,
    CollectionScope,
    CollectorOrchestrator,
    SyntheticForumCollector,
    SyntheticMarketplaceCollector,
)
from aegis.db.models import EvidenceRecord, SourceRecord
from aegis.db.session import SessionLocal
from aegis.evidence.artifacts import ArtifactStore
from aegis.evidence.service import EvidenceService
from aegis.schemas.evidence import SourceCreate, SourceType
from aegis.settings import settings

pytestmark = pytest.mark.integration


def test_synthetic_source_collector_evidence_pipeline() -> None:
    db = SessionLocal()
    tmp_store = ArtifactStore(f"{settings.evidence_storage_path}/collector-it")
    service = EvidenceService(db, tmp_store)

    source = service.create_source(
        SourceCreate(
            source_type=SourceType.SYNTHETIC,
            name="Phase 05 collector fixture",
            reliability=1.0,
            independence_group="collector-fixture",
        )
    )

    try:
        orchestrator = CollectorOrchestrator(
            [SyntheticForumCollector(), SyntheticMarketplaceCollector()]
        )
        report = asyncio.run(orchestrator.run(CollectionScope(limit=15)))
        assert report.total_observations == 30

        ingestor = CollectionIngestor(service)
        result = ingestor.ingest(report.observations, source_id=source.source_id)

        assert result.created == 30
        assert result.skipped_duplicates == 0
        assert len(result.evidence_ids) == 30

        rows = db.scalars(
            select(EvidenceRecord).where(EvidenceRecord.source_id == source.source_id)
        ).all()
        assert len(rows) == 30
        for row in rows:
            assert row.sha256 and len(row.sha256) == 64
            assert row.collector_name in {"synthetic_forum", "synthetic_marketplace"}
            assert row.collector_version == "0.1.0"
            assert row.independence_group
            # raw bytes live in the content-addressed store; the collector's
            # source URL is preserved as provenance metadata
            assert row.raw_artifact_uri.startswith("file://")
            assert str(row.metadata_json["source_url"]).startswith("synthetic://")
            assert row.metadata_json["author_hint"]

        # idempotency: re-ingesting the same observations creates nothing new
        repeat = ingestor.ingest(report.observations, source_id=source.source_id)
        assert repeat.created == 0
        assert repeat.skipped_duplicates == 30
    finally:
        db.execute(delete(EvidenceRecord).where(EvidenceRecord.source_id == source.source_id))
        db.execute(delete(SourceRecord).where(SourceRecord.source_id == source.source_id))
        db.commit()
        db.close()
