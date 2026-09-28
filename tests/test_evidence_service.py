"""Unit tests for :class:`aegis.evidence.service.EvidenceService`.

The service is exercised against a spy session (no database): what is
under test is the *transaction discipline* — commit vs flush-only,
audit-before-commit ordering, and ``IntegrityError`` → conflict
translation on both the flush and the commit path — plus the batched
digest prefetch queries (one round-trip, empty input = no query).
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from aegis.db.models import ArtifactRecord, AuditLogRecord, EvidenceRecord
from aegis.evidence.artifacts import ArtifactStore
from aegis.evidence.service import EvidenceService
from aegis.schemas.evidence import EvidenceCreate, SourceType

SOURCE_ID = UUID("00000000-0000-0000-0000-000000000001")
OBSERVED_AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


class _Rows:
    """Stand-in for SQLAlchemy's ScalarResult (``.all()`` only)."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _SpySession:
    """Session double recording SQL traffic and transaction events.

    ``rows`` are handed back by every ``scalars()`` call in the order
    given — emulating the ORDER BY the real database would apply.
    """

    def __init__(
        self,
        *,
        source_exists: bool = True,
        duplicate: object | None = None,
        rows: list[object] | None = None,
        fail_on_flush: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.statements: list[str] = []
        self.scalar_statements: list[Any] = []
        self.scalars_statements: list[Any] = []
        self.rows: list[object] = list(rows or [])
        self.duplicate = duplicate
        self.source_exists = source_exists
        self.fail_on_flush = fail_on_flush
        self.fail_on_commit = fail_on_commit
        self.commits = 0
        self.rollbacks = 0

    # -- identity map -------------------------------------------------
    def get(self, entity: object, ident: object) -> object | None:  # noqa: ARG002
        return object() if self.source_exists else None

    # -- SQL ----------------------------------------------------------
    def scalar(self, stmt: object) -> object | None:
        self.scalar_statements.append(stmt)
        self.statements.append(str(stmt))
        self.events.append("scalar")
        if "audit_logs" in str(stmt):  # chain tail lookup (AuditService.last_hash)
            return None
        return self.duplicate

    def scalars(self, stmt: object) -> _Rows:
        self.scalars_statements.append(stmt)
        self.statements.append(str(stmt))
        self.events.append("scalars")
        return _Rows(self.rows)

    def get_bind(self) -> None:
        # None => no Postgres advisory lock (see AuditService._lock_chain)
        return None

    # -- transaction --------------------------------------------------
    def add(self, obj: object) -> None:
        self.events.append(f"add:{type(obj).__name__}")

    def flush(self) -> None:
        self.events.append("flush")
        if self.fail_on_flush:
            raise IntegrityError("INSERT INTO evidence", {}, Exception("uq_evidence_observation"))

    def commit(self) -> None:
        self.events.append("commit")
        if self.fail_on_commit:
            raise IntegrityError("COMMIT", {}, Exception("uq_evidence_observation"))
        self.commits += 1

    def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1

    def refresh(self, obj: object) -> None:
        self.events.append("refresh")


def _payload(
    digest: str = DIGEST_A,
    observed_at: datetime | None = OBSERVED_AT,
    source_id: UUID = SOURCE_ID,
) -> EvidenceCreate:
    return EvidenceCreate(
        source_id=source_id,
        source_type=SourceType.SYNTHETIC,
        observed_at=observed_at,
        collected_at=OBSERVED_AT,
        raw_artifact_uri="synthetic://evidence/unit-test",
        sha256=digest,
        collector_name="unit-test",
        collector_version="0.1.0",
        source_reliability=1.0,
        independence_group="unit-test",
    )


def _service(db: _SpySession, tmp_path: Any) -> EvidenceService:
    return EvidenceService(db, ArtifactStore(tmp_path))


# ---------------------------------------------------------- commit control


def test_create_evidence_commits_by_default(tmp_path: Any) -> None:
    db = _SpySession()
    record = _service(db, tmp_path).create_evidence(_payload())

    assert db.commits == 1
    assert db.rollbacks == 0
    assert db.events.index("add:EvidenceRecord") < db.events.index("commit")
    assert "refresh" in db.events, "default (committing) mode refreshes the row"
    assert record.evidence_id is not None


def test_create_evidence_audits_before_commit(tmp_path: Any) -> None:
    """Mutation and audit must be written in the SAME transaction."""
    db = _SpySession()
    _service(db, tmp_path).create_evidence(_payload())

    audit_index = db.events.index(f"add:{AuditLogRecord.__name__}")
    assert audit_index < db.events.index("commit")
    assert audit_index > db.events.index("add:EvidenceRecord"), "audit follows the mutation"


def test_create_evidence_commit_false_flushes_only(tmp_path: Any) -> None:
    db = _SpySession()
    record = _service(db, tmp_path).create_evidence(_payload(), commit=False)

    assert db.commits == 0, "commit=False leaves the transaction to the batch caller"
    assert db.rollbacks == 0
    assert "refresh" not in db.events, "no refresh before the caller commits"
    # evidence insert and audit insert are both flushed inside the transaction
    audit_index = db.events.index(f"add:{AuditLogRecord.__name__}")
    assert db.events.index("add:EvidenceRecord") < db.events.index("flush") < audit_index
    assert db.events[-1] == "flush", "ends on the audit flush, awaiting the caller's commit"
    assert record.evidence_id is not None


def test_create_evidence_commit_false_still_writes_the_artifact(tmp_path: Any) -> None:
    content = b"artifact bytes"
    db = _SpySession()
    service = _service(db, tmp_path)

    record = service.create_evidence(
        _payload(digest=sha256(content).hexdigest()),
        content,
        commit=False,
    )

    assert db.commits == 0
    assert record.artifact_id is not None
    assert record.raw_artifact_uri.startswith("synthetic://") is False  # store rewrote it
    assert db.events.index(f"add:{ArtifactRecord.__name__}") < db.events.index("flush")


# ------------------------------------------------------ IntegrityError paths


@pytest.mark.parametrize("commit", [True, False])
def test_integrity_error_at_flush_is_translated_to_conflict(tmp_path: Any, commit: bool) -> None:
    """The unique-violation surfaces when the INSERT is emitted (flush);
    both modes must report it as the API's 409 conflict, not a 500."""
    db = _SpySession(fail_on_flush=True)

    with pytest.raises(ValueError, match="already observed"):
        _service(db, tmp_path).create_evidence(_payload(), commit=commit)

    assert db.rollbacks == 1
    assert db.commits == 0


def test_integrity_error_at_commit_is_translated_to_conflict(tmp_path: Any) -> None:
    db = _SpySession(fail_on_commit=True)

    with pytest.raises(ValueError, match="already observed"):
        _service(db, tmp_path).create_evidence(_payload())

    assert db.rollbacks == 1
    assert db.commits == 0


def test_unknown_source_is_rejected_before_any_sql(tmp_path: Any) -> None:
    db = _SpySession(source_exists=False)

    with pytest.raises(ValueError, match="Unknown source_id"):
        _service(db, tmp_path).create_evidence(_payload())

    assert db.statements == []
    assert db.events == []


def test_preexisting_observation_is_rejected_as_a_conflict(tmp_path: Any) -> None:
    db = _SpySession(duplicate=EvidenceRecord(sha256=DIGEST_A))

    with pytest.raises(ValueError, match="already observed"):
        _service(db, tmp_path).create_evidence(_payload())

    assert db.events == ["scalar"], "duplicate check runs before any write"
    assert db.commits == 0


# ------------------------------------------------------------ batch lookups


def test_get_observations_batch_runs_one_scoped_query(tmp_path: Any) -> None:
    later = datetime(2026, 3, 2, tzinfo=UTC)
    db = _SpySession(
        rows=[
            EvidenceRecord(sha256=DIGEST_A, observed_at=OBSERVED_AT, source_id=SOURCE_ID),
            EvidenceRecord(sha256=DIGEST_B, observed_at=None, source_id=SOURCE_ID),
        ]
    )

    found = _service(db, tmp_path).get_observations_batch([DIGEST_A, DIGEST_B], SOURCE_ID)

    assert len(db.scalars_statements) == 1, "one query for N digests"
    statement = str(db.scalars_statements[0])
    assert "evidence.sha256 IN" in statement, "digests go in an IN clause"
    assert "evidence.source_id" in statement, "scoped to the requesting source"
    assert found == {
        (DIGEST_A, OBSERVED_AT): db.rows[0],
        (DIGEST_B, None): db.rows[1],
    }

    # exact observation identity is (digest, observed time): a different
    # time simply is not a key in the map
    assert (DIGEST_A, later) not in found


def test_get_observations_batch_dedupes_digests(tmp_path: Any) -> None:
    db = _SpySession(
        rows=[
            EvidenceRecord(sha256=DIGEST_A, observed_at=OBSERVED_AT),
            EvidenceRecord(sha256=DIGEST_B, observed_at=OBSERVED_AT),
        ]
    )

    found = _service(db, tmp_path).get_observations_batch([DIGEST_A, DIGEST_A, DIGEST_B], SOURCE_ID)

    assert len(db.scalars_statements) == 1
    bind_lists = [
        value
        for value in db.scalars_statements[0].compile().params.values()
        if isinstance(value, list)
    ]
    assert bind_lists == [[DIGEST_A, DIGEST_B]], "duplicate digests collapse in the IN clause"
    assert len(found) == 2


def test_get_observations_batch_empty_input_issues_no_query(tmp_path: Any) -> None:
    db = _SpySession(rows=[EvidenceRecord(sha256=DIGEST_A, observed_at=OBSERVED_AT)])

    assert _service(db, tmp_path).get_observations_batch([], SOURCE_ID) == {}
    assert db.statements == []


def test_get_by_sha256_batch_returns_earliest_record_per_digest(tmp_path: Any) -> None:
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 6, 1, tzinfo=UTC)
    # rows arrive in (sha256, created_at) order — what the ORDER BY asks for
    earliest = EvidenceRecord(sha256=DIGEST_A, created_at=earlier)
    newest = EvidenceRecord(sha256=DIGEST_A, created_at=later)
    other = EvidenceRecord(sha256=DIGEST_B, created_at=later)
    db = _SpySession(rows=[earliest, newest, other])

    found = _service(db, tmp_path).get_by_sha256_batch([DIGEST_A, DIGEST_B])

    statement = str(db.scalars_statements[0])
    assert len(db.scalars_statements) == 1, "one query for N digests"
    assert "evidence.sha256 IN" in statement
    assert "ORDER BY" in statement and "created_at" in statement, (
        "earliest record per digest, matching get_by_sha256"
    )
    assert found == {DIGEST_A: earliest, DIGEST_B: other}


def test_get_by_sha256_batch_skips_unknown_digests(tmp_path: Any) -> None:
    db = _SpySession(rows=[EvidenceRecord(sha256=DIGEST_A, created_at=OBSERVED_AT)])

    found = _service(db, tmp_path).get_by_sha256_batch([DIGEST_A, DIGEST_B])

    assert set(found) == {DIGEST_A}


def test_get_by_sha256_batch_empty_input_issues_no_query(tmp_path: Any) -> None:
    db = _SpySession()

    assert _service(db, tmp_path).get_by_sha256_batch([]) == {}
    assert db.statements == []


def test_batch_lookups_preserve_single_row_semantics(tmp_path: Any) -> None:
    """A one-element batch returns exactly what the single-digest helpers do."""
    row = EvidenceRecord(sha256=DIGEST_A, observed_at=OBSERVED_AT, source_id=SOURCE_ID)
    db = _SpySession(rows=[row], duplicate=None)

    service = _service(db, tmp_path)
    by_observation = service.get_observations_batch([DIGEST_A], SOURCE_ID)
    by_digest = service.get_by_sha256_batch([DIGEST_A])

    assert by_observation[(DIGEST_A, OBSERVED_AT)] is row
    assert by_digest[DIGEST_A] is row


def test_unique_ids_are_client_assigned(tmp_path: Any) -> None:
    db = _SpySession()
    service = _service(db, tmp_path)

    first = service.create_evidence(_payload())
    second = service.create_evidence(_payload(digest=DIGEST_B))

    assert first.evidence_id != second.evidence_id
    assert isinstance(first.evidence_id, UUID)
    assert isinstance(second.evidence_id, UUID)
