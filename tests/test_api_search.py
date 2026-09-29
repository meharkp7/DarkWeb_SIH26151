"""Tests for the global search endpoint.

Search is the answer to "where have I seen this", so two properties matter
more than ranking quality: a hit must name the case it came from, and a
term too short to be a search must be refused rather than scanned for.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aegis.api.app import app
from aegis.api.search import MIN_QUERY_LENGTH


def _client() -> TestClient:
    return TestClient(app)


def test_short_terms_are_refused_rather_than_scanned(
    auth_headers: dict[str, str], db_available: bool
) -> None:
    """A one-character prefix against the whole ledger returns the dataset.

    That is a table scan wearing a search box's clothes, and the response
    would look like a successful answer. 422 with a usable message is the
    honest response.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    for term in ("z", "ab"):
        response = client.get("/api/v1/search", params={"q": term}, headers=auth_headers)
        assert response.status_code == 422, term
        assert str(MIN_QUERY_LENGTH) in response.json()["detail"]


def test_every_hit_names_its_case(auth_headers: dict[str, str], db_available: bool) -> None:
    """A hit with no case is not actionable.

    The whole point of the box is answering "which investigation holds
    this", so a case-scoped result that omits the case fails at its job even
    though the label matched.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    response = client.get(
        "/api/v1/search", params={"q": "Blackbird", "limit": 25}, headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["hits"], "the seeded dataset must produce at least one hit"
    for hit in body["hits"]:
        if hit["kind"] == "source":
            # Sources are not case-scoped, and the response says so by
            # leaving `case_id` null rather than inventing one.
            assert hit["case_id"] is None
            continue
        assert hit["case_id"] is not None, hit
        assert hit["case_name"], hit


def test_case_search_returns_the_case_itself_first(
    auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    body = client.get(
        "/api/v1/search", params={"q": "Operation", "limit": 25}, headers=auth_headers
    ).json()
    cases = [hit for hit in body["hits"] if hit["kind"] == "case"]
    assert cases, "searching for a known case name must return that case"
    # Cases are ordered by operational weight, so the most urgent match is
    # first. `critical` outranks `high`.
    ranks = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
    weights = [ranks[hit["detail"].split(" · ")[-1]] for hit in cases]
    assert weights == sorted(weights), cases


def test_counts_reflect_the_groups_actually_returned(
    auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    body = client.get(
        "/api/v1/search", params={"q": "nightjar", "limit": 5}, headers=auth_headers
    ).json()
    assert body["counts"], "a matching query must report what it matched"
    assert sum(body["counts"].values()) == len(body["hits"])
    assert body["query"] == "nightjar"


def test_a_term_with_no_matches_returns_an_empty_result_not_an_error(
    auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    body = client.get(
        "/api/v1/search",
        params={"q": "zzz-not-a-real-identifier-zzz"},
        headers=auth_headers,
    ).json()
    assert body["hits"] == []
    assert body["counts"] == {}


def test_search_requires_a_credential(db_available: bool) -> None:
    """The ledger is not public, and neither is the index over it."""
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    assert _client().get("/api/v1/search", params={"q": "nightjar"}).status_code == 401


def test_limit_is_bounded(auth_headers: dict[str, str], db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    assert (
        client.get(
            "/api/v1/search", params={"q": "nightjar", "limit": 500}, headers=auth_headers
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/search", params={"q": "nightjar", "limit": 0}, headers=auth_headers
        ).status_code
        == 422
    )
    # An empty query is a validation failure, not a request for everything.
    assert client.get("/api/v1/search", params={"q": ""}, headers=auth_headers).status_code == 422


def test_unknown_case_id_is_still_not_reachable(db_available: bool) -> None:
    """Search does not become a way to enumerate case ids."""
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    assert _client().get("/api/v1/search", params={"q": str(uuid4())}).status_code == 401
