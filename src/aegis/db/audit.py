"""Append-only, hash-chained audit trail (Implementation Plan Phase 03).

Every mutating operation records an audit entry inside the same
transaction as the mutation. Entries form a hash chain:

    entry_hash = sha256(prev_hash | occurred_at | action | entity | payload)

so tampering with historical rows is detectable. The database trigger
from migration ``0002_ledger`` additionally blocks UPDATE/DELETE.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aegis.db.models import AuditLogRecord


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON encoding used for hash computation."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(
    prev_hash: str | None,
    occurred_at: datetime,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    payload: dict[str, Any],
) -> str:
    """SHA-256 over the normalized audit tuple."""
    material = "|".join(
        (
            prev_hash or "GENESIS",
            occurred_at.isoformat(),
            action,
            entity_type or "",
            entity_id or "",
            canonical_json(payload),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditService:
    """Append audit entries and verify chain integrity.

    Concurrent appenders serialize on a transaction-scoped Postgres
    advisory lock before reading the chain tail, so two writers can
    never fork the chain off the same ``prev_hash``.
    """

    #: Advisory-lock key for the audit chain tail (arbitrary but stable).
    _CHAIN_LOCK_KEY = 0x4145_4749_53

    def __init__(self, db: Session) -> None:
        self.db = db

    def _lock_chain(self) -> None:
        bind = self.db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": self._CHAIN_LOCK_KEY},
            )

    def last_hash(self) -> str | None:
        return self.db.scalar(
            select(AuditLogRecord.entry_hash).order_by(AuditLogRecord.seq.desc()).limit(1)
        )

    def record(
        self,
        action: str,
        *,
        actor_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        case_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditLogRecord:
        """Append one audit entry inside the caller's transaction.

        The entry is flushed but never committed here: the caller's
        ``commit()`` persists mutation and audit together, so a rollback
        discards both — preserving the invariant "no mutation without
        audit, no audit without mutation". Never call ``commit()`` here;
        doing so would break the surrounding transaction's atomicity.
        """
        self._lock_chain()
        body = payload or {}
        timestamp = occurred_at or datetime.now(UTC)
        prev_hash = self.last_hash()
        entry_hash = compute_entry_hash(prev_hash, timestamp, action, entity_type, entity_id, body)

        record = AuditLogRecord(
            occurred_at=timestamp,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            case_id=case_id,
            payload_json=body,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def verify_chain(self) -> bool:
        """Recompute the whole chain; returns False on any tamper evidence."""
        rows = self.db.scalars(select(AuditLogRecord).order_by(AuditLogRecord.seq.asc())).all()

        previous: str | None = None
        for row in rows:
            expected = compute_entry_hash(
                previous,
                row.occurred_at,
                row.action,
                row.entity_type,
                row.entity_id,
                row.payload_json,
            )
            if row.prev_hash != previous or row.entry_hash != expected:
                return False
            previous = row.entry_hash
        return True

    def entries_for_entity(self, entity_id: str) -> list[AuditLogRecord]:
        return list(
            self.db.scalars(
                select(AuditLogRecord)
                .where(AuditLogRecord.entity_id == entity_id)
                .order_by(AuditLogRecord.seq.asc())
            ).all()
        )
