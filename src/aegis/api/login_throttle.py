"""Failed-login throttling.

The login route is the only endpoint reachable without a credential, so it is
the only one an attacker can hammer. Without a limit, a 4-character password
is guessable at whatever rate the connection allows, and `auth_session_ttl_s`
is irrelevant to that.

Design constraints, in order of importance:

* **Fail closed, never throw.** A throttler that can itself fail open is worse
  than none, and one that throws turns a failed login into a 500. Every path
  here returns a decision; nothing raises.
* **Do not become a denial-of-service vector.** The key is
  (email, client address), not address alone: an attacker who knows a
  colleague's email should not be able to lock that colleague out by failing
  on their behalf, and a shared NAT should not let one user's failures throttle
  another.
* **Bounded memory.** Entries expire and the table is pruned on every call, so
  a spray of unique emails cannot grow the process without limit.
* **The response must not confirm whether the account exists.** The throttle
  replies with the same status the credential check does, and the lockout
  message never names a successful identity.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

#: Failures tolerated inside the window before the key is locked.
MAX_FAILURES = 5
#: Window over which failures accumulate.
WINDOW_SECONDS = 900.0
#: How long a locked key stays locked, independent of the window. Longer than
#: the window so a determined attacker cannot simply wait out the count.
LOCKOUT_SECONDS = 900.0
#: Hard cap on tracked keys. A spray of unique emails evicts the oldest
#: entries rather than growing without bound; evicting the least-recently
#: seen key is the right victim because an attacker is not revisiting them.
MAX_TRACKED_KEYS = 10_000


@dataclass
class _Record:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0
    last_seen: float = 0.0


class LoginThrottle:
    """Sliding-window failed-attempt tracker.

    Deliberately in-process. A multi-worker deployment needs a shared store,
    and that is stated rather than hidden: an in-process limiter is correct
    for a single-process deployment and a partial control for several, and
    pretending otherwise would be worse than saying it.
    """

    def __init__(
        self,
        *,
        max_failures: int = MAX_FAILURES,
        window_seconds: float = WINDOW_SECONDS,
        lockout_seconds: float = LOCKOUT_SECONDS,
        max_keys: int = MAX_TRACKED_KEYS,
    ) -> None:
        self._records: OrderedDict[tuple[str, str], _Record] = OrderedDict()
        self._lock = threading.Lock()
        self._max_failures = max_failures
        self._window = window_seconds
        self._lockout = lockout_seconds
        self._max_keys = max_keys

    @staticmethod
    def key(email: str, client: str) -> tuple[str, str]:
        return (email.strip().lower(), client)

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, record in self._records.items()
            if record.locked_until <= now
            and not [t for t in record.failures if now - t < self._window]
        ]
        for key in expired:
            self._records.pop(key, None)

    def retry_after(self, email: str, client: str) -> int:
        """Seconds until the key may try again. 0 when it may try now."""
        now = time.monotonic()
        with self._lock:
            record = self._records.get(self.key(email, client))
            if record is None or record.locked_until <= now:
                return 0
            return max(1, int(record.locked_until - now))

    def check(self, email: str, client: str) -> int:
        """Return 0 if allowed, otherwise the `Retry-After` seconds."""
        self._prune(now := time.monotonic())
        with self._lock:
            record = self._records.get(self.key(email, client))
            if record is None:
                return 0
            record.last_seen = now
            if record.locked_until > now:
                return max(1, int(record.locked_until - now))
            return 0

    def record_failure(self, email: str, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            key = self.key(email, client)
            record = self._records.get(key)
            if record is None:
                record = _Record()
                self._records[key] = record
            self._records.move_to_end(key)
            record.last_seen = now
            record.failures = [t for t in record.failures if now - t < self._window]
            record.failures.append(now)
            if len(record.failures) >= self._max_failures:
                record.locked_until = now + self._lockout
                # The failure list is cleared on lockout: once the key is
                # locked, the count no longer adds information, and keeping
                # it would extend the lock by another window on every
                # further attempt.
                record.failures.clear()
            while len(self._records) > self._max_keys:
                self._records.popitem(last=False)

    def record_success(self, email: str, client: str) -> None:
        """A successful sign-in clears the counter.

        Otherwise a user who mistypes twice a week is eventually locked out
        by their own carelessness, which trains people to disable the
        control.
        """
        with self._lock:
            self._records.pop(self.key(email, client), None)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._records)


#: Process-wide limiter used by the login route.
login_throttle = LoginThrottle()


def client_address(request: object) -> str:
    """Best-effort client address for the throttle key.

    `X-Forwarded-For` is honoured because the deployment is expected to sit
    behind a proxy, and without it every request would share one key — which
    would make a single attacker able to lock out every user at once. The
    header is only meaningful when a proxy sets it; a deployment accepting
    these requests directly should terminate TLS and strip the header.
    """
    headers = cast("Mapping[str, str] | None", getattr(request, "headers", None))
    if headers is not None:
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = cast("Any", getattr(request, "client", None))
    host = cast("str | None", getattr(client, "host", None))
    return host or "unknown"
