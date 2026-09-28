"""Object-store abstraction (Implementation Plan Phase 04).

Two adapters share one contract:

* :class:`LocalObjectStore` — content-addressed local filesystem store used
  in CI and single-node deployments.
* :class:`S3ObjectStore` — S3-compatible adapter (AWS/MinIO/R2) used in
  deployments; boto3 is imported lazily so the base install stays light.

All keys pass through :mod:`aegis.storage.keys` validation, which rejects
object-name injection before any adapter sees a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PutResult:
    """Result of a successful write."""

    key: str
    sha256: str
    size_bytes: int
    etag: str | None = None


@runtime_checkable
class ObjectStore(Protocol):
    """Minimal contract every adapter must satisfy."""

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> PutResult: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def list_keys(self, prefix: str) -> list[str]: ...
