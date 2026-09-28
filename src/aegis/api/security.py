"""Small, dependency-free API safety controls (Phase 25)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status


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
