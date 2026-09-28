"""Object storage layer (Phase 04)."""

from aegis.storage.base import ObjectStore, PutResult
from aegis.storage.evidence_package import (
    AccessContext,
    CorruptedArtifactError,
    EvidenceAccessDenied,
    EvidencePackageStore,
    PackageNotFoundError,
    PackageParts,
    PackageReceipt,
)
from aegis.storage.keys import (
    InvalidObjectKey,
    evidence_package_key,
    evidence_package_prefix,
    validate_key,
)
from aegis.storage.local import LocalObjectStore
from aegis.storage.s3 import S3ObjectStore, S3StoreError

__all__ = [
    "AccessContext",
    "CorruptedArtifactError",
    "EvidenceAccessDenied",
    "EvidencePackageStore",
    "InvalidObjectKey",
    "LocalObjectStore",
    "ObjectStore",
    "PackageNotFoundError",
    "PackageParts",
    "PackageReceipt",
    "PutResult",
    "S3ObjectStore",
    "S3StoreError",
    "evidence_package_key",
    "evidence_package_prefix",
    "validate_key",
]
