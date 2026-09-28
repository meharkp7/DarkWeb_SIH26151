from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aegis.db.audit import AuditService
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
        self.db.flush()
        AuditService(self.db).record(
            "source.created",
            entity_type="source",
            entity_id=str(source.source_id),
            payload={"name": payload.name, "reliability": payload.reliability},
        )
        self.db.commit()
        self.db.refresh(source)
        return source

    def create_evidence(
        self, payload: EvidenceCreate, artifact_bytes: bytes | None = None
    ) -> EvidenceRecord:
        if self.db.get(SourceRecord, payload.source_id) is None:
            raise ValueError(f"Unknown source_id: {payload.source_id}")

        # Duplicate check BEFORE any artifact write so a rejected request
        # cannot leave an orphan object behind (review finding), and
        # against the observation identity — the same content observed
        # again from another source or a later scan is a new observation,
        # not a conflict (content identity lives on ArtifactRecord).
        digest = payload.sha256.lower()
        duplicate = self.db.scalar(
            select(EvidenceRecord).where(
                EvidenceRecord.sha256 == digest,
                EvidenceRecord.source_id == payload.source_id,
                EvidenceRecord.observed_at == payload.observed_at,
            )
        )
        if duplicate is not None:
            raise ValueError(f"Evidence already observed for this source at this time: {digest}")

        artifact_id = None
        raw_uri = payload.raw_artifact_uri
        if artifact_bytes is not None:
            # Server-side verification: put_bytes recomputes the digest of
            # the actual bytes and raises on mismatch with payload.sha256.
            uri, computed = self.artifact_store.put_bytes(artifact_bytes, digest)
            raw_uri = uri
            artifact = self.db.scalar(
                select(ArtifactRecord).where(ArtifactRecord.sha256 == computed)
            )
            if artifact is None:
                artifact = ArtifactRecord(
                    artifact_id=uuid4(),
                    sha256=computed,
                    storage_uri=uri,
                    size_bytes=len(artifact_bytes),
                )
                self.db.add(artifact)
                self.db.flush()
            artifact_id = artifact.artifact_id

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
        self.db.flush()
        AuditService(self.db).record(
            "evidence.created",
            case_id=payload.case_id,
            entity_type="evidence",
            entity_id=str(record.evidence_id),
            payload={
                "sha256": digest,
                "source_id": str(payload.source_id),
                "collector_name": payload.collector_name,
            },
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            # Lost the race against a concurrent identical observation:
            # uq_evidence_observation (the DB-side check the review asked
            # for) rejects it atomically; roll back and report as a conflict.
            self.db.rollback()
            raise ValueError(
                f"Evidence already observed for this source at this time: {digest}"
            ) from exc
        self.db.refresh(record)
        return record

    def get(self, evidence_id: UUID) -> EvidenceRecord | None:
        return self.db.get(EvidenceRecord, evidence_id)

    def get_by_sha256(self, sha256: str) -> EvidenceRecord | None:
        """Any observation of this content (content-level lookup).

        Multiple sources may observe the same bytes, so this returns the
        earliest record rather than assuming uniqueness.
        """
        return self.db.scalar(
            select(EvidenceRecord)
            .where(EvidenceRecord.sha256 == sha256)
            .order_by(EvidenceRecord.created_at.asc())
            .limit(1)
        )

    def get_observation(
        self, sha256: str, source_id: UUID, observed_at: datetime | None
    ) -> EvidenceRecord | None:
        """Exact observation identity: content + source + observed time."""
        return self.db.scalar(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.sha256 == sha256,
                EvidenceRecord.source_id == source_id,
                EvidenceRecord.observed_at == observed_at,
            )
            .limit(1)
        )

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
