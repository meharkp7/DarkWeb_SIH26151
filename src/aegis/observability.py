"""Thread-safe operational and ML observability primitives (Phase 26)."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class MetricSnapshot:
    counters: dict[str, int]
    latencies_ms: dict[str, float]
    histograms_ms: dict[str, dict[str, int]]
    gauges: dict[str, float]
    ml: dict[str, float]


class Metrics:
    """Small in-process metrics registry with histogram and ML signals.

    It is intentionally dependency-free. Production deployments can export
    this snapshot to Prometheus/OpenTelemetry without changing call sites.
    """

    _BUCKETS = (5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0)

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._latency_total: defaultdict[str, float] = defaultdict(float)
        self._latency_count: defaultdict[str, int] = defaultdict(int)
        self._histograms: defaultdict[str, list[int]] = defaultdict(lambda: [0] * (len(self._BUCKETS) + 1))
        self._gauges: dict[str, float] = {}
        self._ml: dict[str, float] = {}

    def increment(self, name: str, value: int = 1) -> None:
        if not name.strip() or value < 0:
            raise ValueError("metric name must be non-empty and value non-negative")
        with self._lock:
            self._counters[name] += value

    def observe_latency(self, name: str, milliseconds: float) -> None:
        if not name.strip() or milliseconds < 0.0:
            raise ValueError("metric name must be non-empty and latency non-negative")
        with self._lock:
            self._latency_total[name] += milliseconds
            self._latency_count[name] += 1
            bucket = next((i for i, bound in enumerate(self._BUCKETS) if milliseconds <= bound), len(self._BUCKETS))
            self._histograms[name][bucket] += 1

    def set_gauge(self, name: str, value: float) -> None:
        if not name.strip():
            raise ValueError("metric name must be non-empty")
        with self._lock:
            self._gauges[name] = float(value)

    def observe_ml(self, name: str, value: float) -> None:
        if not name.strip():
            raise ValueError("metric name must be non-empty")
        with self._lock:
            self._ml[name] = float(value)

    def snapshot(self) -> MetricSnapshot:
        with self._lock:
            histograms = {}
            for name, counts in sorted(self._histograms.items()):
                labels = [f"le_{bound:g}" for bound in self._BUCKETS] + ["gt_max"]
                histograms[name] = dict(zip(labels, counts, strict=True))
            return MetricSnapshot(
                counters=dict(sorted(self._counters.items())),
                latencies_ms={
                    name: round(self._latency_total[name] / self._latency_count[name], 3)
                    for name in sorted(self._latency_count)
                },
                histograms_ms=histograms,
                gauges=dict(sorted(self._gauges.items())),
                ml=dict(sorted(self._ml.items())),
            )


def population_drift(reference: list[float], current: list[float]) -> float:
    """Return a simple normalized mean-shift drift signal in [0, 1]."""
    if not reference or not current:
        raise ValueError("reference and current samples must be non-empty")
    ref_mean = sum(reference) / len(reference)
    cur_mean = sum(current) / len(current)
    scale = max(abs(ref_mean), abs(cur_mean), 1e-12)
    return min(abs(cur_mean - ref_mean) / scale, 1.0)


def calibration_drift(reference: list[float], current: list[float]) -> float:
    """Compare mean confidence across two calibrated score populations."""
    return population_drift(reference, current)


def false_association_rate(false_associations: int, total_associations: int) -> float:
    if false_associations < 0 or total_associations < 0 or false_associations > total_associations:
        raise ValueError("invalid association counts")
    return false_associations / total_associations if total_associations else 0.0
