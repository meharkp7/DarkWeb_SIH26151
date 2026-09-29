"""Session token issue/validate round-trip."""

from __future__ import annotations

from aegis.api.auth import issue_access_token, validate_access_token


def test_access_token_round_trip() -> None:
    token, _expires_at = issue_access_token()
    identity = validate_access_token(token)
    assert identity is not None
    assert identity.email
