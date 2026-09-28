"""Phase 04 object storage tests: upload, checksum, retrieval, corruption,
authorization, object-name injection."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import pytest

from aegis.storage import (
    AccessContext,
    CorruptedArtifactError,
    EvidenceAccessDenied,
    EvidencePackageStore,
    InvalidObjectKey,
    LocalObjectStore,
    PackageNotFoundError,
    S3ObjectStore,
    S3StoreError,
    evidence_package_key,
    validate_key,
)

CASE_ID = str(uuid.uuid4())
EVIDENCE_ID = str(uuid.uuid4())
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def authorized() -> AccessContext:
    return AccessContext(user_id="analyst-1", case_ids=frozenset({CASE_ID}))


@pytest.fixture
def stranger() -> AccessContext:
    return AccessContext(user_id="analyst-2", case_ids=frozenset())


@pytest.fixture
def package_store(tmp_path) -> EvidencePackageStore:
    return EvidencePackageStore(LocalObjectStore(tmp_path))


def test_upload_checksum_and_retrieval(
    package_store: EvidencePackageStore, authorized: AccessContext
) -> None:
    raw = b"collected artifact bytes"
    normalized = b"collected artifact bytes"

    receipt = package_store.write(
        authorized,
        case_id=CASE_ID,
        evidence_id=EVIDENCE_ID,
        raw=raw,
        normalized=normalized,
        collected_at=NOW,
        source_id="SRC-1",
        metadata={"collector": "synthetic"},
    )

    assert receipt.raw_sha256 == __import__("hashlib").sha256(raw).hexdigest()
    assert receipt.prefix == f"evidence/2026/09/{CASE_ID}/{EVIDENCE_ID}"
    assert set(receipt.written_keys) == {
        f"evidence/2026/09/{CASE_ID}/{EVIDENCE_ID}/raw",
        f"evidence/2026/09/{CASE_ID}/{EVIDENCE_ID}/normalized",
        f"evidence/2026/09/{CASE_ID}/{EVIDENCE_ID}/metadata.json",
    }

    parts = package_store.read(
        authorized, case_id=CASE_ID, evidence_id=EVIDENCE_ID, year=2026, month=9
    )
    assert parts.raw == raw
    assert parts.normalized == normalized
    assert parts.metadata["sha256"] == receipt.raw_sha256
    assert parts.metadata["case_id"] == CASE_ID

    assert (
        package_store.verify(
            authorized, case_id=CASE_ID, evidence_id=EVIDENCE_ID, year=2026, month=9
        )
        == []
    )


def test_corrupted_artifact_detected(
    package_store: EvidencePackageStore, authorized: AccessContext
) -> None:
    package_store.write(
        authorized,
        case_id=CASE_ID,
        evidence_id=EVIDENCE_ID,
        raw=b"original bytes",
        collected_at=NOW,
    )

    # Tamper with the stored raw object behind the store's back.
    key = evidence_package_key(
        year=2026, month=9, case_id=CASE_ID, evidence_id=EVIDENCE_ID, part="raw"
    )
    package_store.store.corrupt_for_test(key, b"tampered bytes")  # type: ignore[attr-defined]

    corrupted = package_store.verify(
        authorized, case_id=CASE_ID, evidence_id=EVIDENCE_ID, year=2026, month=9
    )
    assert corrupted == ["raw"]

    with pytest.raises(CorruptedArtifactError) as excinfo:
        package_store.verify_strict(
            authorized, case_id=CASE_ID, evidence_id=EVIDENCE_ID, year=2026, month=9
        )
    assert "raw" in excinfo.value.corrupted_parts


def test_authorization_is_case_scoped(
    package_store: EvidencePackageStore, authorized: AccessContext, stranger: AccessContext
) -> None:
    package_store.write(
        authorized,
        case_id=CASE_ID,
        evidence_id=EVIDENCE_ID,
        raw=b"secret",
        collected_at=NOW,
    )

    with pytest.raises(EvidenceAccessDenied):
        package_store.read(stranger, case_id=CASE_ID, evidence_id=EVIDENCE_ID, year=2026, month=9)
    with pytest.raises(EvidenceAccessDenied):
        package_store.write(
            stranger,
            case_id=CASE_ID,
            evidence_id=str(uuid.uuid4()),
            raw=b"inject",
            collected_at=NOW,
        )
    with pytest.raises(EvidenceAccessDenied):
        package_store.verify(stranger, case_id=CASE_ID, evidence_id=EVIDENCE_ID, year=2026, month=9)


def test_admin_role_crosses_case_scope(package_store: EvidencePackageStore) -> None:
    admin = AccessContext(user_id="root", roles=frozenset({"admin"}))
    package_store.write(admin, case_id=CASE_ID, evidence_id=EVIDENCE_ID, raw=b"x", collected_at=NOW)
    assert (
        package_store.read(admin, case_id=CASE_ID, evidence_id=EVIDENCE_ID, year=2026, month=9).raw
        == b"x"
    )


def test_missing_package_raises_not_found(
    package_store: EvidencePackageStore, authorized: AccessContext
) -> None:
    with pytest.raises(PackageNotFoundError):
        package_store.read(
            authorized,
            case_id=CASE_ID,
            evidence_id=str(uuid.uuid4()),
            year=2026,
            month=9,
        )


@pytest.mark.parametrize(
    "key",
    [
        "../../etc/passwd",
        "evidence/../../secret",
        "/absolute/path",
        "evidence//double-slash",
        "evidence/././raw",
        "evidence/\x00/null",
        "evidence\\\\windows\\path",
        "evidence/2026/09/with space/raw",
        "",
    ],
)
def test_object_name_injection_rejected(key: str) -> None:
    with pytest.raises(InvalidObjectKey):
        validate_key(key)


def test_package_key_rejects_non_uuid_components() -> None:
    with pytest.raises(InvalidObjectKey):
        evidence_package_key(
            year=2026, month=9, case_id="../../etc", evidence_id=EVIDENCE_ID, part="raw"
        )
    with pytest.raises(InvalidObjectKey):
        evidence_package_key(
            year=2026, month=9, case_id=CASE_ID, evidence_id="not-a-uuid", part="raw"
        )
    with pytest.raises(InvalidObjectKey):
        evidence_package_key(
            year=2026, month=9, case_id=CASE_ID.upper(), evidence_id=EVIDENCE_ID, part="raw"
        )
    with pytest.raises(InvalidObjectKey):
        evidence_package_key(
            year=2026, month=13, case_id=CASE_ID, evidence_id=EVIDENCE_ID, part="raw"
        )
    with pytest.raises(InvalidObjectKey):
        evidence_package_key(
            year=2026, month=9, case_id=CASE_ID, evidence_id=EVIDENCE_ID, part="../../raw"
        )


# ----------------------------------------------------------------- S3 adapter


class FakeBody(io.BytesIO):
    def read(self, *args: object, **kwargs: object) -> bytes:  # noqa: ARG002
        return super().read()


class FakeS3Client:
    """Implements the S3 subset used by :class:`S3ObjectStore`."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
        self.calls: list[str] = []

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        Metadata: dict[str, str],
        ContentType: str | None = None,
        **_: object,
    ) -> dict[str, str]:
        del ContentType
        self.calls.append(f"put:{Bucket}/{Key}")
        self.objects[(Bucket, Key)] = (bytes(Body), dict(Metadata))
        return {"ETag": Metadata["sha256"]}

    def get_object(self, *, Bucket: str, Key: str, **_: object) -> dict[str, object]:
        self.calls.append(f"get:{Bucket}/{Key}")
        if (Bucket, Key) not in self.objects:
            raise FileNotFoundError(Key)
        body, metadata = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(body), "Metadata": metadata}

    def head_object(self, *, Bucket: str, Key: str, **_: object) -> dict[str, object]:
        self.calls.append(f"head:{Bucket}/{Key}")
        if (Bucket, Key) not in self.objects:
            raise FileNotFoundError(Key)
        return {}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, **_: object) -> dict[str, object]:
        self.calls.append(f"list:{Bucket}/{Prefix}")
        contents = [
            {"Key": key}
            for (bucket, key) in sorted(self.objects)
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}


def test_s3_store_round_trip_and_checksum_enforcement() -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client, "aegis-evidence", prefix="prod")

    result = store.put(
        "evidence/2026/09/x/y/raw", b"bytes", content_type="application/octet-stream"
    )
    assert result.size_bytes == 5
    assert store.exists("evidence/2026/09/x/y/raw")
    assert store.get("evidence/2026/09/x/y/raw") == b"bytes"
    assert store.list_keys("evidence") == ["evidence/2026/09/x/y/raw"]

    # Corruption must surface on read.
    key = ("aegis-evidence", "prod/evidence/2026/09/x/y/raw")
    body, metadata = client.objects[key]
    client.objects[key] = (b"tamper", metadata)
    with pytest.raises(S3StoreError, match="checksum mismatch"):
        store.get("evidence/2026/09/x/y/raw")


def test_s3_store_rejects_injection_keys() -> None:
    store = S3ObjectStore(FakeS3Client(), "aegis-evidence")
    with pytest.raises(InvalidObjectKey):
        store.put("../../etc/passwd", b"x")
    with pytest.raises(InvalidObjectKey):
        store.get("/etc/passwd")


def test_s3_store_missing_key_behaviour() -> None:
    store = S3ObjectStore(FakeS3Client(), "aegis-evidence")
    assert store.exists("evidence/2026/09/ab/cd/raw") is False
    with pytest.raises(S3StoreError):
        store.get("evidence/2026/09/ab/cd/raw")
