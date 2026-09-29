"""Small, dependency-free API safety controls (Phase 25)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

#: PBKDF2 work factor. 600k is the OWASP 2023 recommendation for
#: PBKDF2-HMAC-SHA256 and keeps a single verification near 200 ms on
#: commodity hardware, which is the point: a low factor turns an offline
#: dump of this table into a fast dictionary attack.
PBKDF2_ITERATIONS = 600_000
_PBKDF2_PREFIX = "pbkdf2_sha256"


def hash_password(
    password: str, *, iterations: int = PBKDF2_ITERATIONS, salt: bytes | None = None
) -> str:
    """Hash a password for storage in ``users.password_hash``.

    The encoded form is ``pbkdf2_sha256$<iterations>$<salt-b64>$<hash-b64>``.
    Parameters live inside the string so the work factor can be raised later
    without invalidating existing rows.
    """
    if not password:
        raise ValueError("password must not be empty")
    resolved_salt = salt if salt is not None else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), resolved_salt, iterations)
    return "$".join(
        (
            _PBKDF2_PREFIX,
            str(iterations),
            base64.b64encode(resolved_salt).decode(),
            base64.b64encode(digest).decode(),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of ``password`` against a stored hash."""
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$")
        if algorithm != _PBKDF2_PREFIX:
            return False
        salt = base64.b64decode(raw_salt)
        expected = base64.b64decode(raw_digest)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(raw_iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


class RequestRateLimiter:
    """In-process sliding-window guard suitable for a single API process.

    Production multi-process deployments must replace this with a shared
    gateway/Redis limiter; keeping the interface here makes that swap explicit.
    """

    def __init__(
        self,
        limit: int = 120,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0.0:
            raise ValueError("limit and window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._requests: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        entries = self._requests.setdefault(key, deque())
        while entries and now - entries[0] >= self.window_seconds:
            entries.popleft()
        if len(entries) >= self.limit:
            return False
        entries.append(now)
        return True


def request_guard(limiter: RequestRateLimiter, max_bytes: int) -> Callable[[Request], None]:
    """Return a FastAPI dependency enforcing rate and declared body size."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    def guard(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded"
            )
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="payload too large"
            )

    return guard


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
