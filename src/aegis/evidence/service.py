from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.db.models import ArtifactRecord, EvidenceDerivationRecord, EvidenceRecord, SourceRecord
from aegis.evidence.artifacts import ArtifactStore
from aegis.schemas.evidence import EvidenceCreate, EvidenceProvenance, SourceCreate


class EvidenceService:
    def __init__(self, db: Session, artifact_store: ArtifactStore):
        self.db = db
        self.artifact_store = artifact_store

    def create_source(self, payload: SourceCreate) -> SourceRecord:
        source = SourceRecord(
            source_id=uuid4(),
            source_type=payload.source_type.value,
            name=payload.name,
            reliability=payload.reliability,
            metadata_json=payload.metadata,
        )
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def create_evidence(
        self, payload: EvidenceCreate, artifact_bytes: bytes | None = None
    ) -> EvidenceRecord:
        if self.db.get(SourceRecord, payload.source_id) is None:
            raise ValueError(f"Unknown source_id: {payload.source_id}")

        artifact_id = None
        raw_uri = payload.raw_artifact_uri
        if artifact_bytes is not None:
            uri, digest = self.artifact_store.put_bytes(artifact_bytes, payload.sha256)
            raw_uri = uri
            artifact = self.db.scalar(select(ArtifactRecord).where(ArtifactRecord.sha256 == digest))
            if artifact is None:
                artifact = ArtifactRecord(
                    artifact_id=uuid4(),
                    sha256=digest,
                    storage_uri=uri,
                    size_bytes=len(artifact_bytes),
                )
                self.db.add(artifact)
                self.db.flush()
            artifact_id = artifact.artifact_id
        elif payload.raw_artifact_uri.startswith("file://"):
            pass

        duplicate = self.db.scalar(
            select(EvidenceRecord).where(EvidenceRecord.sha256 == payload.sha256)
        )
        if duplicate is not None:
            raise ValueError(f"Evidence with SHA-256 already exists: {payload.sha256}")

        record = EvidenceRecord(
            evidence_id=uuid4(),
            case_id=payload.case_id,
            source_id=payload.source_id,
            source_type=payload.source_type.value,
            observed_at=payload.observed_at,
            collected_at=payload.collected_at,
            entity_type=payload.entity_type,
            entity_value_hash=payload.entity_value_hash,
            context_hash=payload.context_hash,
            raw_artifact_uri=raw_uri,
            artifact_id=artifact_id,
            sha256=payload.sha256.lower(),
            collector_name=payload.collector_name,
            collector_version=payload.collector_version,
            normalizer_version=payload.normalizer_version,
            extraction_version=payload.extraction_version,
            source_reliability=payload.source_reliability,
            independence_group=payload.independence_group,
            metadata_json=payload.metadata,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get(self, evidence_id: UUID) -> EvidenceRecord | None:
        return self.db.get(EvidenceRecord, evidence_id)

    def get_by_sha256(self, sha256: str) -> EvidenceRecord | None:
        return self.db.scalar(select(EvidenceRecord).where(EvidenceRecord.sha256 == sha256))

    def provenance(self, evidence_id: UUID) -> EvidenceProvenance:
        evidence = self.db.get(EvidenceRecord, evidence_id)
        if evidence is None:
            raise ValueError(f"Unknown evidence_id: {evidence_id}")
        rows = self.db.scalars(
            select(EvidenceDerivationRecord).where(
                EvidenceDerivationRecord.derived_evidence_id == evidence_id
            )
        ).all()
        return EvidenceProvenance(
            evidence_id=evidence.evidence_id,
            sha256=evidence.sha256,
            artifact_uri=evidence.raw_artifact_uri,
            parent_evidence_ids=tuple(row.parent_evidence_id for row in rows),
            derivation_count=len(rows),
        )
