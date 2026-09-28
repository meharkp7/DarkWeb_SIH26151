"""Dependency-free operational metrics foundation (Phase 26)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSnapshot:
    counters: dict[str, int]
    latencies_ms: dict[str, float]


class Metrics:
    """In-process metric accumulator; exporters can scrape ``snapshot``."""

    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._latency_total: defaultdict[str, float] = defaultdict(float)
        self._latency_count: defaultdict[str, int] = defaultdict(int)

    def increment(self, name: str, value: int = 1) -> None:
        if not name.strip() or value < 0:
            raise ValueError("metric name must be non-empty and value non-negative")
        self._counters[name] += value

    def observe_latency(self, name: str, milliseconds: float) -> None:
        if not name.strip() or milliseconds < 0.0:
            raise ValueError("metric name must be non-empty and latency non-negative")
        self._latency_total[name] += milliseconds
        self._latency_count[name] += 1

    def snapshot(self) -> MetricSnapshot:
        return MetricSnapshot(
            counters=dict(sorted(self._counters.items())),
            latencies_ms={
                name: round(self._latency_total[name] / self._latency_count[name], 3)
                for name in sorted(self._latency_count)
            },
        )
