"""Local filesystem object store (development, CI, single-node deployments)."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from aegis.storage.base import PutResult
from aegis.storage.keys import validate_key


class LocalObjectStore:
    """Stores objects under ``root`` with hierarchical key directories."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        # Defense in depth: even after key validation, ensure containment.
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"resolved object path escapes store root: {key!r}")
        return path

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> PutResult:
        del content_type  # local adapter has no media-type metadata
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_bytes()
            if existing != data:
                raise ValueError(f"object already exists with different content: {key!r}")
        else:
            path.write_bytes(data)
        digest = sha256(data).hexdigest()
        return PutResult(key=key, sha256=digest, size_bytes=len(data), etag=digest)

    def get(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def list_keys(self, prefix: str) -> list[str]:
        validate_key(prefix)
        base = self.root / prefix
        if not base.exists():
            return []
        if base.is_file():
            return [prefix]
        keys: list[str] = []
        for path in sorted(base.rglob("*")):
            if path.is_file():
                keys.append(path.relative_to(self.root).as_posix())
        return keys

    def corrupt_for_test(self, key: str, data: bytes) -> None:
        """Test helper bypassing the no-overwrite rule (simulates tampering)."""
        path = self._path_for(key)
        path.write_bytes(data)
