from aegis.observability import (
    Metrics,
    calibration_drift,
    false_association_rate,
    population_drift,
)


def test_metrics_accumulate_pipeline_counts_and_average_latency() -> None:
    metrics = Metrics()
    metrics.increment("collector.success")
    metrics.increment("collector.success", 2)
    metrics.observe_latency("api.request", 10.0)
    metrics.observe_latency("api.request", 20.0)
    snapshot = metrics.snapshot()
    assert snapshot.counters == {"collector.success": 3}
    assert snapshot.latencies_ms == {"api.request": 15.0}


def test_metrics_histogram_and_ml_snapshot() -> None:
    metrics = Metrics()
    metrics.increment("requests")
    metrics.observe_latency("api", 12.0)
    metrics.set_gauge("queue", 3)
    metrics.observe_ml("drift", 0.25)
    snapshot = metrics.snapshot()
    assert snapshot.counters["requests"] == 1
    assert snapshot.latencies_ms["api"] == 12.0
    assert snapshot.gauges["queue"] == 3.0
    assert snapshot.ml["drift"] == 0.25
    assert sum(snapshot.histograms_ms["api"].values()) == 1


def test_drift_helpers() -> None:
    assert population_drift([1, 1], [1, 1]) == 0.0
    assert calibration_drift([0.2, 0.4], [0.3, 0.5]) > 0.0
    assert false_association_rate(1, 4) == 0.25
