from aegis.evidence.hashing import sha256_bytes


def test_sha256_is_deterministic() -> None:
    assert sha256_bytes(b"AEGIS") == sha256_bytes(b"AEGIS")
    assert len(sha256_bytes(b"AEGIS")) == 64


def test_sha256_changes_with_content() -> None:
    assert sha256_bytes(b"AEGIS") != sha256_bytes(b"aegis")
