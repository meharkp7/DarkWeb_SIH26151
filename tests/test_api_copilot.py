from fastapi import status
from fastapi.testclient import TestClient

from aegis.api.app import app
from aegis.api.copilot import get_copilot_context
from aegis.copilot.tools import CopilotToolContext
from aegis.schemas.evidence import Evidence
from aegis.search import IndexedDocument, InProcessSearchEngine


def test_copilot_query_endpoint(auth_headers: dict[str, str]) -> None:
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))

    app.dependency_overrides[get_copilot_context] = lambda: CopilotToolContext(search=search)

    try:
        response = TestClient(app).post(
            "/api/v1/copilot/query",
            json={"question": "find evidence about shadowbroker"},
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_copilot_context, None)

    assert response.status_code == 200

    body = response.json()
    assert body["intent"] == "evidence_search"
    assert body["tools_run"] == ["search_evidence"]
    assert body["evidence_ids"] == [str(evidence.evidence_id)]


def test_copilot_query_rejects_empty_question(auth_headers: dict[str, str]) -> None:
    response = TestClient(app).post(
        "/api/v1/copilot/query",
        json={"question": ""},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_copilot_query_rejects_anonymous_callers() -> None:
    """Authentication is checked before the request body is validated.

    An unauthenticated caller gets 401 rather than 422, which is deliberate:
    answering "your question was malformed" to someone who has not proven who
    they are leaks that the endpoint exists and what it accepts.
    """
    response = TestClient(app).post(
        "/api/v1/copilot/query",
        json={"question": "find evidence"},
    )

    assert response.status_code == 401


def test_context_is_accepted_as_its_own_field_and_echoed(
    auth_headers: dict[str, str],
) -> None:
    """Grounding travels as context, never concatenated onto the question.

    The console used to append "Context: … — viewing assessment" to the
    question text. The intent router matches on substrings, so every question
    typed on the assessment tab matched the assessment rule and was answered by
    a tool that then had no subject. Separating the two is what makes a question
    route on its own words.
    """
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))

    app.dependency_overrides[get_copilot_context] = lambda: CopilotToolContext(search=search)

    try:
        response = TestClient(app).post(
            "/api/v1/copilot/query",
            json={
                "question": "What evidence is driving this?",
                "context": "Operation Nightfall — viewing assessment",
            },
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_copilot_context, None)

    assert response.status_code == 200
    body = response.json()
    # The question reaches the router unmixed, so it takes the default route
    # rather than being captured by the word "assessment" in the context.
    assert body["question"] == "What evidence is driving this?"
    assert body["intent"] == "evidence_search"
    assert body["context"] == "Operation Nightfall — viewing assessment"


def test_copilot_query_is_rate_limited(auth_headers: dict[str, str]) -> None:
    """The copilot is the most expensive read in the console, so it is paced.

    It was the only POST in the application with neither a rate limit nor a
    body-size cap, so one analyst holding the shortcut could serialise the API
    against a backend that builds a graph per scoped question.
    """
    search = InProcessSearchEngine()
    app.dependency_overrides[get_copilot_context] = lambda: CopilotToolContext(search=search)
    client = TestClient(app)

    statuses: list[int] = []
    try:
        for _ in range(40):
            response = client.post(
                "/api/v1/copilot/query",
                json={"question": "find evidence"},
                headers=auth_headers,
            )
            statuses.append(response.status_code)
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                break
    finally:
        app.dependency_overrides.pop(get_copilot_context, None)

    assert status.HTTP_429_TOO_MANY_REQUESTS in statuses, (
        "the copilot endpoint accepted 40 consecutive queries with no rate limit"
    )
    # The limit has to bite *before* an unbounded number of graph builds, not
    # merely exist.
    assert len(statuses) <= 25
