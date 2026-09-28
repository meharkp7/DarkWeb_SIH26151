from fastapi.testclient import TestClient

from aegis.api.app import app
from aegis.api.security import RequestRateLimiter


def test_health_response_has_security_headers() -> None:
    response = TestClient(app).get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_sliding_window_rate_limiter_expires_entries() -> None:
    now = [0.0]
    limiter = RequestRateLimiter(limit=2, window_seconds=10.0, clock=lambda: now[0])
    assert limiter.allow("client")
    assert limiter.allow("client")
    assert not limiter.allow("client")
    now[0] = 10.0
    assert limiter.allow("client")


def test_metrics_endpoint_exposes_api_counters() -> None:
    client = TestClient(app)
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.json()["counters"]["api.status.200"] >= 1
