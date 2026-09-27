from io import BytesIO

import pytest

from aegis.evidence.artifacts import ArtifactStore
from aegis.evidence.hashing import sha256_bytes


def test_artifact_store_is_content_addressed(tmp_path):
    store = ArtifactStore(tmp_path)
    data = b"AEGIS evidence"
    uri, digest = store.put_bytes(data)
    assert digest == sha256_bytes(data)
    assert store.get_path(digest).read_bytes() == data
    assert store.verify(digest)
    assert uri.startswith("file://")


def test_artifact_store_rejects_wrong_hash(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        store.put_stream(BytesIO(b"abc"), "0" * 64)
