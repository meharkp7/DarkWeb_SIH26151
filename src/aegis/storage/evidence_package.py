"""Evidence package storage: the Phase 04 write/read/verify workflow.

Layout:

    evidence/{year}/{month}/{case_id}/{evidence_id}/
        raw           original artifact bytes (write-once)
        normalized    normalization pipeline output
        metadata.json digests + provenance for the package

Authorization is case-scoped: every operation receives an
:class:`AccessContext` and is rejected when the context is not
authorized for the case that owns the package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256

from aegis.storage.base import ObjectStore, PutResult
from aegis.storage.keys import (
    PART_METADATA,
    PART_NORMALIZED,
    PART_RAW,
    evidence_package_key,
    evidence_package_prefix,
)


class EvidenceAccessDenied(PermissionError):
    """Caller's access context does not cover the target case."""


class PackageNotFoundError(FileNotFoundError):
    """Evidence package (or one of its parts) is missing."""


class CorruptedArtifactError(RuntimeError):
    """A stored part no longer matches its recorded digest."""

    def __init__(self, corrupted_parts: list[str]) -> None:
        self.corrupted_parts = corrupted_parts
        super().__init__(f"corrupted evidence parts: {', '.join(corrupted_parts)}")


@dataclass(frozen=True)
class AccessContext:
    """Who is calling and which cases they may touch."""

    user_id: str
    case_ids: frozenset[str] = field(default_factory=frozenset)
    roles: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


@dataclass(frozen=True)
class PackageReceipt:
    """What a successful write produced."""

    case_id: str
    evidence_id: str
    prefix: str
    raw_sha256: str
    normalized_sha256: str | None
    written_keys: tuple[str, ...]


@dataclass(frozen=True)
class PackageParts:
    raw: bytes
    normalized: bytes | None
    metadata: dict[str, object]


class EvidencePackageStore:
    """Case-scoped, checksummed evidence package storage."""

    def __init__(self, store: ObjectStore) -> None:
        self.store = store

    # ------------------------------------------------------------ authz

    @staticmethod
    def _authorize(context: AccessContext, case_id: str) -> None:
        if context.is_admin or case_id in context.case_ids:
            return
        raise EvidenceAccessDenied(
            f"user {context.user_id} is not authorized for case {case_id}"
        )

    # ------------------------------------------------------------- write

    def write(
        self,
        context: AccessContext,
        *,
        case_id: str,
        evidence_id: str,
        raw: bytes,
        collected_at: datetime,
        normalized: bytes | None = None,
        metadata: dict[str, object] | None = None,
        source_id: str | None = None,
    ) -> PackageReceipt:
        self._authorize(context, case_id)
        timestamp = collected_at if collected_at.tzinfo else collected_at.replace(tzinfo=UTC)

        raw_key = evidence_package_key(
            year=timestamp.year, month=timestamp.month, case_id=case_id,
            evidence_id=evidence_id, part=PART_RAW,
        )
        norm_key = evidence_package_key(
            year=timestamp.year, month=timestamp.month, case_id=case_id,
            evidence_id=evidence_id, part=PART_NORMALIZED,
        )
        meta_key = evidence_package_key(
            year=timestamp.year, month=timestamp.month, case_id=case_id,
            evidence_id=evidence_id, part=PART_METADATA,
        )

        raw_result = self.store.put(raw_key, raw, content_type="application/octet-stream")
        results: list[PutResult] = [raw_result]
        raw_digest = results[0].sha256

        norm_digest: str | None = None
        written = [raw_key]
        if normalized is not None:
            norm_result = self.store.put(norm_key, normalized)
            norm_digest = norm_result.sha256
            written.append(norm_key)

        body: dict[str, object] = {
            "schema_version": "1.0",
            "case_id": case_id,
            "evidence_id": evidence_id,
            "source_id": source_id,
            "collected_at": timestamp.isoformat(),
            "sha256": raw_digest,
            "normalized_sha256": norm_digest,
            "size_bytes": len(raw),
            "metadata": metadata or {},
        }
        meta_payload = (
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        ).encode("utf-8")
        self.store.put(meta_key, meta_payload, content_type="application/json")
        written.append(meta_key)

        return PackageReceipt(
            case_id=case_id,
            evidence_id=evidence_id,
            prefix=evidence_package_prefix(
                year=timestamp.year, month=timestamp.month, case_id=case_id,
                evidence_id=evidence_id,
            ),
            raw_sha256=raw_digest,
            normalized_sha256=norm_digest,
            written_keys=tuple(written),
        )

    # -------------------------------------------------------------- read

    def read(
        self, context: AccessContext, *, case_id: str, evidence_id: str, year: int, month: int
    ) -> PackageParts:
        self._authorize(context, case_id)
        raw_key = evidence_package_key(
            year=year, month=month, case_id=case_id, evidence_id=evidence_id, part=PART_RAW
        )
        norm_key = evidence_package_key(
            year=year, month=month, case_id=case_id, evidence_id=evidence_id,
            part=PART_NORMALIZED,
        )
        meta_key = evidence_package_key(
            year=year, month=month, case_id=case_id, evidence_id=evidence_id,
            part=PART_METADATA,
        )
        if not self.store.exists(raw_key):
            raise PackageNotFoundError(raw_key)
        raw = self.store.get(raw_key)
        normalized = self.store.get(norm_key) if self.store.exists(norm_key) else None
        metadata: dict[str, object] = {}
        if self.store.exists(meta_key):
            metadata = json.loads(self.store.get(meta_key).decode("utf-8"))
        return PackageParts(raw=raw, normalized=normalized, metadata=metadata)

    # ------------------------------------------------------------- verify

    def verify(
        self, context: AccessContext, *, case_id: str, evidence_id: str, year: int, month: int
    ) -> list[str]:
        """Re-hash every part against metadata.json; return corrupted parts."""
        parts = self.read(context, case_id=case_id, evidence_id=evidence_id, year=year, month=month)
        corrupted: list[str] = []

        declared_raw = str(parts.metadata.get("sha256", ""))
        if declared_raw and sha256(parts.raw).hexdigest() != declared_raw:
            corrupted.append(PART_RAW)

        declared_norm = parts.metadata.get("normalized_sha256")
        if declared_norm:
            normalized_digest = (
                sha256(parts.normalized).hexdigest() if parts.normalized is not None else None
            )
            if normalized_digest != str(declared_norm):
                corrupted.append(PART_NORMALIZED)

        if not parts.metadata:
            corrupted.append(PART_METADATA)
        return corrupted

    def verify_strict(
        self, context: AccessContext, *, case_id: str, evidence_id: str, year: int, month: int
    ) -> None:
        """Like :meth:`verify` but raises :class:`CorruptedArtifactError`."""
        corrupted = self.verify(
            context, case_id=case_id, evidence_id=evidence_id, year=year, month=month
        )
        if corrupted:
            raise CorruptedArtifactError(corrupted)
