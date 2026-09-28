"""S3-compatible object store (AWS S3, MinIO, Cloudflare R2).

boto3 is imported lazily; tests inject a client implementing the small
subset of the S3 API used here (``put_object``, ``get_object``,
``head_object``, ``list_objects_v2``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from typing import Any

from aegis.storage.base import PutResult
from aegis.storage.keys import validate_key


class S3StoreError(RuntimeError):
    """Raised for S3 adapter failures (missing keys, HTTP errors)."""


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str, *, prefix: str = "") -> None:
        if not bucket or not isinstance(bucket, str):
            raise S3StoreError("bucket name is required")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _full_key(self, key: str) -> str:
        validate_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> PutResult:
        full = self._full_key(key)
        digest = sha256(data).hexdigest()
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": full,
            "Body": data,
            "Metadata": {"sha256": digest},
        }
        if content_type:
            kwargs["ContentType"] = content_type
        try:
            response = self.client.put_object(**kwargs)
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            raise S3StoreError(f"put failed for {key!r}: {exc}") from exc
        etag = str(response.get("ETag", "")).strip('"') or None
        if etag is not None and etag != digest and "-" not in etag:
            raise S3StoreError(f"server etag mismatch for {key!r}")
        return PutResult(key=key, sha256=digest, size_bytes=len(data), etag=etag)

    def get(self, key: str) -> bytes:
        full = self._full_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=full)
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            raise S3StoreError(f"get failed for {key!r}: {exc}") from exc
        body = response["Body"].read()
        # Verify integrity on read: corruption must surface immediately.
        metadata = response.get("Metadata") or {}
        expected = metadata.get("sha256")
        actual = sha256(body).hexdigest()
        if expected and expected != actual:
            raise S3StoreError(f"checksum mismatch for {key!r}")
        return bytes(body)

    def exists(self, key: str) -> bool:
        full = self._full_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=full)
        except Exception:  # noqa: BLE001 - HEAD 404 and transport errors alike
            return False
        return True

    def list_keys(self, prefix: str) -> list[str]:
        validate_key(prefix)
        full_prefix = f"{self.prefix}/{prefix}" if self.prefix else prefix
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": full_prefix}
            if token:
                kwargs["ContinuationToken"] = token
            try:
                response = self.client.list_objects_v2(**kwargs)
            except Exception as exc:  # noqa: BLE001 - adapter boundary
                raise S3StoreError(f"list failed for {prefix!r}: {exc}") from exc
            strip = f"{self.prefix}/" if self.prefix else ""
            for item in response.get("Contents", []):
                keys.append(item["Key"].removeprefix(strip))
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
        return sorted(keys)


def s3_store_from_env(
    *,
    bucket: str,
    region: str | None = None,
    endpoint_url: str | None = None,
    prefix: str = "",
    client_factory: Callable[..., Any] | None = None,
) -> S3ObjectStore:
    """Build an :class:`S3ObjectStore` from environment-provided settings.

    ``client_factory`` exists so deployments can inject a custom
    credential chain; production uses boto3.
    """
    if client_factory is None:
        try:
            import boto3  # noqa: PLC0415 - lazy by design
        except ImportError as exc:
            raise S3StoreError(
                "boto3 is required for S3 storage; install aegis-intelligence[s3]"
            ) from exc
        client_factory = boto3.client
    client = client_factory("s3", region_name=region, endpoint_url=endpoint_url)
    return S3ObjectStore(client, bucket, prefix=prefix)


def metadata_json(payload: dict[str, object]) -> bytes:
    """Canonical metadata.json encoding (stable key order, trailing newline)."""
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
