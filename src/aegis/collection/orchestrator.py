"""Collector orchestration: discover → collect → normalize with retry and
rate limiting. The orchestrator operates purely on value objects — it has
no database dependency.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aegis.collection.base import Collector
from aegis.collection.types import (
    Candidate,
    CollectionScope,
    CollectorRejected,
    CollectorTimeout,
    NormalizedArtifact,
)


@dataclass(frozen=True)
class CollectorOutcome:
    collector_name: str
    collector_version: str
    candidates: int
    observations: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollectionReport:
    scope: CollectionScope
    started_at: datetime
    finished_at: datetime
    outcomes: tuple[CollectorOutcome, ...] = ()
    observations: tuple[NormalizedArtifact, ...] = field(default_factory=tuple)

    @property
    def total_candidates(self) -> int:
        return sum(outcome.candidates for outcome in self.outcomes)

    @property
    def total_observations(self) -> int:
        return sum(outcome.observations for outcome in self.outcomes)

    @property
    def error_count(self) -> int:
        return sum(len(outcome.errors) for outcome in self.outcomes)

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class RateLimiter:
    """Sliding-window limiter; ``limit_per_minute <= 0`` disables it."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        self._windows: dict[str, deque[float]] = {}

    async def acquire(self, channel: str) -> None:
        if self.limit_per_minute <= 0:
            return
        window = self._windows.setdefault(channel, deque())
        now = time.monotonic()
        while window and now - window[0] >= 60.0:
            window.popleft()
        if len(window) < self.limit_per_minute:
            window.append(now)
            return
        await asyncio.sleep(max(0.0, 60.0 - (now - window[0])))
        window.append(time.monotonic())


class CollectorOrchestrator:
    """Runs collectors under timeouts, retries, and rate limits.

    Failure policy:

    * :class:`CollectorRejected` — scope refused, recorded, not retried.
    * :class:`CollectorTimeout` — retried up to ``max_attempts``.
    * any other error — recorded as a collector error; other collectors
      continue (one bad collector must not sink the batch).
    """

    def __init__(self, collectors: Sequence[Collector], *, max_attempts: int = 2) -> None:
        if not collectors:
            raise ValueError("at least one collector is required")
        self.collectors = tuple(collectors)
        self.max_attempts = max(1, max_attempts)

    async def run(self, scope: CollectionScope) -> CollectionReport:
        started = datetime.now(UTC)
        outcomes: list[CollectorOutcome] = []
        observations: list[NormalizedArtifact] = []

        for collector in self.collectors:
            errors: list[str] = []
            candidates: list[Candidate] = []
            try:
                candidates = list(await collector.discover(scope))
            except CollectorRejected as exc:
                outcomes.append(
                    CollectorOutcome(collector.name, collector.version, 0, 0, (str(exc),))
                )
                continue

            limiter = RateLimiter(collector.rate_limit_per_minute)
            produced: list[NormalizedArtifact] = []

            for candidate in candidates:
                artifact = None
                for attempt in range(1, self.max_attempts + 1):
                    try:
                        await limiter.acquire(collector.name)
                        artifact = await collector.collect(candidate)
                        break
                    except CollectorTimeout as exc:
                        if attempt >= self.max_attempts:
                            errors.append(f"{candidate.candidate_id}: timeout ({exc})")
                    except CollectorRejected as exc:
                        errors.append(f"{candidate.candidate_id}: rejected ({exc})")
                        break
                    except Exception as exc:  # noqa: BLE001 - isolate per candidate
                        errors.append(f"{candidate.candidate_id}: {type(exc).__name__}: {exc}")
                        break

                if artifact is None:
                    continue
                try:
                    produced.extend(await collector.normalize(artifact))
                except Exception as exc:  # noqa: BLE001 - isolate per candidate
                    errors.append(
                        f"{candidate.candidate_id}: normalize {type(exc).__name__}: {exc}"
                    )

            outcomes.append(
                CollectorOutcome(
                    collector.name,
                    collector.version,
                    len(candidates),
                    len(produced),
                    tuple(errors),
                )
            )
            observations.extend(produced)

        finished = datetime.now(UTC)
        return CollectionReport(
            scope=scope,
            started_at=started,
            finished_at=finished,
            outcomes=tuple(outcomes),
            observations=tuple(observations),
        )
