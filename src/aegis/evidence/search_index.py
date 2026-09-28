"""OpenSearch indexing for persisted evidence."""

from aegis.db.models import EvidenceRecord
from aegis.schemas.evidence import Evidence, SourceType
from aegis.search import IndexedDocument, SearchEngine


def evidence_from_record(record: EvidenceRecord) -> Evidence:
    """Convert a persisted evidence row to its canonical search payload."""
    return Evidence(
        case_id=record.case_id,
        source_id=record.source_id,
        source_type=SourceType(record.source_type),
        observed_at=record.observed_at,
        collected_at=record.collected_at,
        entity_type=record.entity_type,
        entity_value_hash=record.entity_value_hash,
        context_hash=record.context_hash,
        raw_artifact_uri=record.raw_artifact_uri,
        sha256=record.sha256,
        collector_name=record.collector_name,
        collector_version=record.collector_version,
        normalizer_version=record.normalizer_version,
        extraction_version=record.extraction_version,
        source_reliability=record.source_reliability,
        independence_group=record.independence_group,
        metadata=record.metadata_json,
        evidence_id=record.evidence_id,
        artifact_id=record.artifact_id,
        created_at=record.created_at,
    )


class EvidenceSearchIndexer:
    """Index committed evidence without coupling it to DB transactions."""

    def __init__(self, search: SearchEngine) -> None:
        self.search = search

    def index(self, record: EvidenceRecord) -> None:
        evidence = evidence_from_record(record)
        self.search.index(IndexedDocument.from_evidence(evidence))
