import pytest

from aegis.copilot.intents import build_structured_query, parse_intent
from aegis.copilot.types import IntentKind, ToolName


def test_intent_routes_from_question_and_extracts_subject_without_data_access() -> None:
    intent = parse_intent("Compare hypothesis:h-1 with actor:shadowbroker")
    assert intent.intent is IntentKind.HYPOTHESIS_COMPARISON
    assert intent.tools == (ToolName.COMPARE_HYPOTHESES,)
    assert intent.query.subject("hypothesis") == "h-1"


def test_default_route_and_empty_question_rejection() -> None:
    assert parse_intent("find wallet mentions").intent is IntentKind.EVIDENCE_SEARCH
    with pytest.raises(ValueError, match="non-empty"):
        build_structured_query(" ")
