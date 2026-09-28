from datetime import UTC, datetime
from unittest.mock import Mock

from aegis.db.models import EvidenceRecord
from aegis.evidence.search_index import EvidenceSearchIndexer, evidence_from_record
from aegis.schemas.evidence import SourceType
from aegis.search import IndexedDocument, IndexName


def _record() -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="11111111-1111-4111-8111-111111111111",
        source_id="22222222-2222-4222-8222-222222222222",
        source_type=SourceType.PUBLIC_WEB.value,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
        entity_type="actor",
        entity_value_hash="entity-hash",
        context_hash="context-hash",
        raw_artifact_uri="file://artifact",
        artifact_id=None,
        sha256="a" * 64,
        collector_name="test",
        collector_version="1.0",
        normalizer_version="1.0",
        extraction_version="1.0",
        source_reliability=0.9,
        independence_group="test-source",
        metadata_json={"subject": "shadowbroker"},
    )


def test_evidence_from_record_preserves_canonical_identity() -> None:
    evidence = evidence_from_record(_record())

    assert str(evidence.evidence_id) == "11111111-1111-4111-8111-111111111111"
    assert evidence.sha256 == "a" * 64
    assert evidence.metadata["subject"] == "shadowbroker"


def test_indexer_indexes_evidence_document() -> None:
    search = Mock()
    record = _record()

    EvidenceSearchIndexer(search).index(record)

    document = search.index.call_args.args[0]

    assert isinstance(document, IndexedDocument)
    assert document.index is IndexName.EVIDENCE
    assert document.doc_id == str(record.evidence_id)
    assert document.payload is not None
