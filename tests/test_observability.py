from aegis.observability import Metrics


def test_metrics_accumulate_pipeline_counts_and_average_latency() -> None:
    metrics = Metrics()
    metrics.increment("collector.success")
    metrics.increment("collector.success", 2)
    metrics.observe_latency("api.request", 10.0)
    metrics.observe_latency("api.request", 20.0)
    snapshot = metrics.snapshot()
    assert snapshot.counters == {"collector.success": 3}
    assert snapshot.latencies_ms == {"api.request": 15.0}
