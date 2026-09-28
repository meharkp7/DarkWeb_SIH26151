"""Phase 03 exit test: 10,000 synthetic evidence records.

Verifies uniqueness, index usage, rollback semantics, and audit-chain
creation against a real PostgreSQL instance (skipped when unavailable).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, insert, select, text

from aegis.db.audit import AuditService
from aegis.db.models import AuditLogRecord, CaseRecord, EvidenceRecord, SourceRecord
from aegis.db.session import SessionLocal

pytestmark = pytest.mark.integration

BATCH_SIZE = 10_000


@pytest.fixture
def ledger_env() -> Iterator[tuple[uuid.UUID, uuid.UUID, str]]:
    """Create an isolated case + source and yield a run-scoped marker."""
    run_marker = f"loadtest-{uuid.uuid4().hex[:12]}"
    case_id = uuid.uuid4()
    source_id = uuid.uuid4()
    db = SessionLocal()
    try:
        db.add(CaseRecord(case_id=case_id, name=f"load-{run_marker}"))
        db.add(
            SourceRecord(
                source_id=source_id,
                source_type="synthetic",
                name=f"load-source-{run_marker}",
                reliability=1.0,
                metadata_json={"run": run_marker},
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        yield case_id, source_id, run_marker
    finally:
        # Bulk evidence and the source are removable; audit rows are
        # append-only (DB trigger) so only their test-scoped marker remains.
        db = SessionLocal()
        try:
            db.execute(
                delete(EvidenceRecord).where(
                    EvidenceRecord.independence_group.startswith(run_marker)
                )
            )
            db.execute(delete(SourceRecord).where(SourceRecord.source_id == source_id))
            db.execute(delete(CaseRecord).where(CaseRecord.case_id == case_id))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _rows(
    count: int, case_id: uuid.UUID, source_id: uuid.UUID, marker: str
) -> list[dict[str, object]]:
    base = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for index in range(count):
        digest = hashlib.sha256(f"{marker}:{index}".encode()).hexdigest()
        rows.append(
            {
                "evidence_id": uuid.uuid4(),
                "case_id": case_id,
                "source_id": source_id,
                "source_type": "synthetic",
                "observed_at": base - timedelta(minutes=index),
                "collected_at": base,
                "entity_type": "handle",
                "entity_value_hash": hashlib.sha256(f"h{index}".encode()).hexdigest()[:128],
                "context_hash": None,
                "raw_artifact_uri": f"file://load/{marker}/{index}",
                "artifact_id": None,
                "sha256": digest,
                "collector_name": "load-test",
                "collector_version": "0.1.0",
                "normalizer_version": "0.1.0",
                "extraction_version": None,
                "source_reliability": 1.0,
                "independence_group": marker,
                "metadata_json": {"index": index, "run": marker},
            }
        )
    return rows


def test_ten_thousand_records_unique_and_indexed(
    ledger_env: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    case_id, source_id, marker = ledger_env
    db = SessionLocal()
    try:
        rows = _rows(BATCH_SIZE, case_id, source_id, marker)
        db.execute(insert(EvidenceRecord), rows)
        db.commit()

        # 1. count + uniqueness
        count = db.scalar(
            select(text("count(*)"))
            .select_from(EvidenceRecord)
            .where(EvidenceRecord.independence_group == marker)
        )
        distinct = db.scalar(
            select(text("count(DISTINCT sha256)"))
            .select_from(EvidenceRecord)
            .where(EvidenceRecord.independence_group == marker)
        )
        assert count == BATCH_SIZE
        assert distinct == BATCH_SIZE

        # duplicate sha256 must be rejected at the database level
        with pytest.raises(Exception):  # noqa: B017 - driver-specific IntegrityError
            db.execute(
                insert(EvidenceRecord).values(**{**rows[0], "evidence_id": uuid.uuid4()})
            )
            db.commit()
        db.rollback()

        # 2. index usage for the required lookup paths
        plan = db.execute(
            text("EXPLAIN SELECT evidence_id FROM evidence WHERE sha256 = :digest"),
            {"digest": rows[0]["sha256"]},
        ).scalars().all()
        plan_text = "\n".join(str(line) for line in plan)
        assert "ix_evidence_sha256" in plan_text, plan_text

        plan_case = db.execute(
            text("EXPLAIN SELECT evidence_id FROM evidence WHERE case_id = :cid"),
            {"cid": str(case_id)},
        ).scalars().all()
        assert "ix_evidence_case_id" in "\n".join(str(line) for line in plan_case)

        # 3. audit creation + verifiable hash chain
        audit = AuditService(db)
        audit.record(
            "bulk_ingest",
            actor_id=None,
            entity_type="evidence",
            entity_id=marker,
            payload={"count": BATCH_SIZE, "case_id": str(case_id), "marker": marker},
        )
        audit.record(
            "bulk_verify",
            entity_type="evidence",
            entity_id=marker,
            payload={"unique": True, "marker": marker},
        )
        assert audit.verify_chain() is True
        assert len(audit.entries_for_entity(marker)) == 2

        # 4. audit log is append-only at the database level
        entry = db.scalar(
            select(AuditLogRecord).where(AuditLogRecord.entity_id == marker).limit(1)
        )
        assert entry is not None
        with pytest.raises(Exception):  # noqa: B017 - raises via DB trigger
            db.execute(
                text("UPDATE audit_logs SET action = 'tampered' WHERE audit_id = :aid"),
                {"aid": str(entry.audit_id)},
            )
        db.rollback()
    finally:
        db.close()


def test_transaction_rollback_leaves_no_partial_state(
    ledger_env: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    case_id, source_id, marker = ledger_env
    db = SessionLocal()
    scoped = f"{marker}-rollback"
    try:
        rows = _rows(500, case_id, source_id, scoped)
        db.execute(insert(EvidenceRecord), rows)
        db.rollback()  # simulated failure after partial work

        remaining = db.scalar(
            select(text("count(*)"))
            .select_from(EvidenceRecord)
            .where(EvidenceRecord.independence_group == scoped)
        )
        assert remaining == 0
    finally:
        db.close()
