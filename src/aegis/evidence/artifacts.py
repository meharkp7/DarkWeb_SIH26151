from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from aegis.evidence.hashing import sha256_bytes, sha256_stream


class ArtifactStore:
    """Local content-addressed artifact store for development and controlled deployments."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes, expected_sha256: str | None = None) -> tuple[str, str]:
        digest = sha256_bytes(data)
        self._verify_expected(digest, expected_sha256)
        path = self._path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return f"file://{path.resolve()}", digest

    def put_stream(
        self, stream: BinaryIO, expected_sha256: str | None = None
    ) -> tuple[str, str, int]:
        temp = self.root / ".incoming.tmp"
        size = 0
        digest = None
        with temp.open("wb") as output:
            import hashlib

            hasher = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                output.write(chunk)
                hasher.update(chunk)
                size += len(chunk)
            digest = hasher.hexdigest()
        assert digest is not None
        self._verify_expected(digest, expected_sha256)
        path = self._path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temp.replace(path)
        else:
            temp.unlink()
        return f"file://{path.resolve()}", digest, size

    def get_path(self, sha256: str) -> Path:
        path = self._path_for(sha256)
        if not path.exists():
            raise FileNotFoundError(sha256)
        return path

    def verify(self, sha256: str) -> bool:
        path = self.get_path(sha256)
        with path.open("rb") as stream:
            return sha256_stream(stream) == sha256

    def _path_for(self, digest: str) -> Path:
        return self.root / digest[:2] / digest[2:4] / digest

    @staticmethod
    def _verify_expected(actual: str, expected: str | None) -> None:
        if expected is not None and actual.lower() != expected.lower():
            raise ValueError(f"SHA-256 mismatch: expected {expected}, got {actual}")
