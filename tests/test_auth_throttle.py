"""Tests for failed-login throttling.

The login route is the only endpoint reachable without a credential, so these
assert the properties that make the control worth having *and* the properties
that stop it becoming a denial-of-service vector against the analysts it is
meant to protect.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aegis.api.app import app
from aegis.api.login_throttle import LoginThrottle, client_address, login_throttle

BAD = {"email": "nobody@example.invalid", "password": "wrong"}


@pytest.fixture(autouse=True)
def _reset_throttle() -> None:
    login_throttle.clear()
    yield
    login_throttle.clear()


def test_login_still_works_after_a_few_failures() -> None:
    client = TestClient(app)
    for _ in range(2):
        assert client.post("/api/v1/auth/login", json=BAD).status_code == 401
    assert client.get("/health").status_code == 200


def test_a_locked_key_reports_a_usable_retry_after() -> None:
    """A bare refusal gives the caller nothing to schedule around."""
    limiter = LoginThrottle(max_failures=3, window_seconds=60, lockout_seconds=30)
    email, address = "a@b.invalid", "10.1.1.1"
    for _ in range(3):
        limiter.record_failure(email, address)
    retry_after = limiter.check(email, address)
    assert 0 < retry_after <= 30
    assert limiter.retry_after(email, address) == retry_after


def test_the_lockout_expires() -> None:
    """A control that never releases is a self-inflicted outage."""
    import time

    limiter = LoginThrottle(max_failures=2, window_seconds=1, lockout_seconds=0.05)
    for _ in range(2):
        limiter.record_failure("a@b.invalid", "10.1.1.1")
    assert limiter.check("a@b.invalid", "10.1.1.1") > 0
    time.sleep(0.1)
    assert limiter.check("a@b.invalid", "10.1.1.1") == 0


def test_throttle_does_not_lock_a_colleague() -> None:
    """Keying on address alone would let one attacker lock everyone out."""
    limiter = LoginThrottle(max_failures=2, window_seconds=60, lockout_seconds=60)
    for _ in range(4):
        limiter.record_failure("victim@example.invalid", "10.1.1.1")
    assert limiter.check("victim@example.invalid", "10.1.1.1") > 0
    # Same address, different identity: unaffected.
    assert limiter.check("attacker@example.invalid", "10.1.1.1") == 0
    # Same identity, different address: also unaffected.
    assert limiter.check("victim@example.invalid", "10.1.1.2") == 0


def test_success_clears_the_counter() -> None:
    """Otherwise a careful user locks themselves out by their own typos."""
    limiter = LoginThrottle(max_failures=3, window_seconds=60, lockout_seconds=60)
    limiter.record_failure("a@b.invalid", "10.1.1.1")
    limiter.record_failure("a@b.invalid", "10.1.1.1")
    limiter.record_success("a@b.invalid", "10.1.1.1")
    assert limiter.check("a@b.invalid", "10.1.1.1") == 0


def test_memory_is_bounded() -> None:
    """A spray of unique emails must not grow the process without limit."""
    limiter = LoginThrottle(max_failures=5, max_keys=25)
    for index in range(500):
        limiter.record_failure(f"spray{index}@example.invalid", "10.2.2.2")
    assert limiter.tracked_keys() <= 25


def test_entries_expire() -> None:
    """A key that stopped being attacked must stop being remembered."""
    limiter = LoginThrottle(max_failures=2, window_seconds=0.01, lockout_seconds=0.01)
    for _ in range(2):
        limiter.record_failure("a@b.invalid", "10.3.3.3")
    assert limiter.check("a@b.invalid", "10.3.3.3") > 0

    import time

    time.sleep(0.05)
    assert limiter.check("a@b.invalid", "10.3.3.3") == 0


def test_client_address_reads_the_forwarded_header() -> None:
    """Without this every request behind a proxy shares one throttle key."""

    class Request:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = None

    assert client_address(Request()) == "203.0.113.7"

    class DirectRequest:
        headers: dict[str, str] = {}

        class client:  # noqa: N801 - mimicking the Starlette attribute name
            host = "198.51.100.4"

    assert client_address(DirectRequest()) == "198.51.100.4"

    class Anonymous:
        headers = {}
        client = None

    assert client_address(Anonymous()) == "unknown"


def test_login_does_not_reveal_whether_an_account_exists() -> None:
    """A wrong email and a wrong password must be indistinguishable."""
    client = TestClient(app)
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.invalid", "password": "x"},
    )
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@aegis-intelligence.com", "password": "x"},
    )
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()
