from __future__ import annotations

from collections.abc import Sequence
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

    def create_source(self, payload: SourceCreate, *, commit: bool = True) -> SourceRecord:
        """Register a source and append its audit event.

        Batch workflows can pass ``commit=False`` to keep their source,
        evidence, hypotheses, and audit records in one atomic transaction.
        """
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
        if commit:
            self.db.commit()
            self.db.refresh(source)
        return source

    def create_evidence(
        self,
        payload: EvidenceCreate,
        artifact_bytes: bytes | None = None,
        *,
        commit: bool = True,
    ) -> EvidenceRecord:
        """Create one evidence observation.

        Args:
            payload: The observation to ledger.
            artifact_bytes: Optional raw bytes; written through the
                artifact store and verified against ``payload.sha256``.
            commit: ``True`` (default, every existing caller) commits the
                transaction here. ``False`` flushes only, so a batch
                caller can insert N rows and commit once at the end
                (see :meth:`aegis.synthetic.persistence.
                SyntheticPersistenceService.persist_evidence`); in that
                mode the caller owns commit/rollback, and server
                populated columns such as ``created_at`` stay unrefreshed
                until the commit expires the row.

        Raises:
            ValueError: On a duplicate observation, or when the database
                rejects the insert (``IntegrityError`` from *either*
                ``flush()`` or ``commit()`` is translated to the same
                conflict message the API maps to HTTP 409).

        .. note::
           On an ``IntegrityError`` the session is rolled back in both
           modes: Postgres aborts the whole transaction on a constraint
           violation, so a batch caller's earlier flushes are lost with
           it — the exception message tells the caller the batch failed.
        """
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
            raw_artifact_uri=payload.raw_artifact_uri,
            artifact_id=None,
            sha256=payload.sha256.lower(),
            collector_name=payload.collector_name,
            collector_version=payload.collector_version,
            normalizer_version=payload.normalizer_version,
            extraction_version=payload.extraction_version,
            source_reliability=payload.source_reliability,
            independence_group=payload.independence_group,
            metadata_json=payload.metadata,
        )

        try:
            # Artifact write + evidence insert + audit append all happen in
            # the caller's transaction: AuditService.record() must run (and
            # flush) BEFORE any commit so mutation and audit commit together.
            if artifact_bytes is not None:
                # Server-side verification: put_bytes recomputes the digest of
                # the actual bytes and raises on mismatch with payload.sha256.
                uri, computed = self.artifact_store.put_bytes(artifact_bytes, digest)
                record.raw_artifact_uri = uri
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
                record.artifact_id = artifact.artifact_id

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
        except IntegrityError as exc:
            # Lost the race against a concurrent identical observation:
            # uq_evidence_observation (the DB-side check the review asked
            # for) rejects it atomically. The violation surfaces at flush
            # time (the INSERT is emitted there) or, in deferred-commit
            # mode, at the caller's commit — both paths translate here.
            self.db.rollback()
            raise ValueError(
                f"Evidence already observed for this source at this time: {digest}"
            ) from exc

        if commit:
            try:
                self.db.commit()
            except IntegrityError as exc:
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

    def get_observations_batch(
        self, sha256s: Sequence[str], source_id: UUID
    ) -> dict[tuple[str, datetime | None], EvidenceRecord]:
        """Prefetch observations of *sha256s* from one source in ONE query.

        Batched counterpart of :meth:`get_observation` for callers that
        would otherwise run one idempotency SELECT per row: collect all
        digests first, call this once, then match in memory against the
        returned ``(sha256, observed_at)`` lookup map — exactly the
        observation identity ``get_observation`` checks. An empty digest
        list issues no query at all.

        Returns:
            ``(sha256, observed_at)`` -> matching record; digests without
            an observation are simply absent from the map.
        """
        digests = list(dict.fromkeys(sha256s))  # dedupe, keep caller order (deterministic)
        if not digests:
            return {}
        rows = self.db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.sha256.in_(digests),
                EvidenceRecord.source_id == source_id,
            )
        ).all()
        # uq_evidence_observation guarantees one row per key, so first-wins
        # matches get_observation's .limit(1) lookup.
        found: dict[tuple[str, datetime | None], EvidenceRecord] = {}
        for row in rows:
            found.setdefault((row.sha256, row.observed_at), row)
        return found

    def get_by_sha256_batch(self, sha256s: Sequence[str]) -> dict[str, EvidenceRecord]:
        """Prefetch the earliest observation of each digest in ONE query.

        Batched counterpart of :meth:`get_by_sha256` (content-level
        reuse): rows come back ordered by ``(sha256, created_at)`` so the
        first row seen for a digest is its earliest observation — the same
        record the single-digest lookup returns. An empty digest list
        issues no query at all.

        Returns:
            ``sha256`` -> earliest record; unknown digests are absent.
        """
        digests = list(dict.fromkeys(sha256s))  # dedupe, keep caller order (deterministic)
        if not digests:
            return {}
        rows = self.db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.sha256.in_(digests))
            .order_by(EvidenceRecord.sha256.asc(), EvidenceRecord.created_at.asc())
        ).all()
        found: dict[str, EvidenceRecord] = {}
        for row in rows:
            found.setdefault(row.sha256, row)  # first row per digest = earliest (see above)
        return found

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
