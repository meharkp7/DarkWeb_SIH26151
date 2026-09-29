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


def test_metrics_endpoint_exposes_api_counters(auth_headers: dict[str, str]) -> None:
    client = TestClient(app)
    client.get("/health")
    response = client.get("/metrics", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["counters"]["api.status.200"] >= 1


def test_protected_routes_reject_anonymous_callers() -> None:
    """Every non-public route must refuse a request with no credential.

    The auth middleware is the only thing standing between an unauthenticated
    caller and the case ledger, so this is asserted directly rather than
    inferred from the routes that happen to be covered elsewhere.
    """
    client = TestClient(app)
    for path in ("/metrics", "/api/v1/cases", "/api/v1/dashboard/summary"):
        assert client.get(path).status_code == 401, path


def test_cors_preflight_is_not_gated_by_auth() -> None:
    """A preflight carries no credentials, so gating it rejects it.

    Found by deploying: the console on Vercel calling the API on Render
    failed on every request while the same request succeeded from curl. The
    Vite dev proxy is same-origin, so no preflight is ever sent and no unit
    test can reach this.
    """
    client = TestClient(app)
    preflight = client.options(
        "/api/v1/dashboard/summary",
        headers={
            "Origin": "https://console.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    # The gate must not answer 401 — that is the whole regression.
    #
    # 405 is the correct answer *here* and not in production: this environment
    # sets no `AEGIS_CORS_ORIGINS`, so CORSMiddleware is not installed and
    # the OPTIONS falls through to a route that only declares GET. With CORS
    # configured, CORSMiddleware intercepts and answers 200. Either way the
    # auth gate stayed out of it.
    assert preflight.status_code != 401, "preflight must not be auth-gated"
    assert preflight.status_code in {200, 400, 405}


def test_a_protected_route_still_rejects_an_unauthenticated_get() -> None:
    """The exemption is for OPTIONS only, not a hole in the gate."""
    client = TestClient(app)
    assert client.get("/api/v1/dashboard/summary").status_code == 401
