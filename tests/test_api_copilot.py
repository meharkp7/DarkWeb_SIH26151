from fastapi.testclient import TestClient

from aegis.api.app import app
from aegis.api.copilot import get_copilot_context
from aegis.copilot.tools import CopilotToolContext
from aegis.schemas.evidence import Evidence
from aegis.search import IndexedDocument, InProcessSearchEngine


def test_copilot_query_endpoint() -> None:
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))

    app.dependency_overrides[get_copilot_context] = lambda: CopilotToolContext(search=search)

    try:
        response = TestClient(app).post(
            "/api/v1/copilot/query",
            json={"question": "find evidence about shadowbroker"},
        )
    finally:
        app.dependency_overrides.pop(get_copilot_context, None)

    assert response.status_code == 200

    body = response.json()
    assert body["intent"] == "evidence_search"
    assert body["tools_run"] == ["search_evidence"]
    assert body["evidence_ids"] == [str(evidence.evidence_id)]


def test_copilot_query_rejects_empty_question() -> None:
    response = TestClient(app).post(
        "/api/v1/copilot/query",
        json={"question": ""},
    )

    assert response.status_code == 422
