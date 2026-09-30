from datetime import UTC, datetime, timedelta

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


def test_a_question_is_routed_from_the_analysts_own_words_alone() -> None:
    """Grounding must not change what a question is taken to mean.

    The console used to append "Context: … — viewing assessment" to the
    question, and the router matches on substrings. So every question typed on
    the assessment tab matched the `("assessment", "confidence")` rule and was
    sent to `get_assessment`, which then had no subject and answered nothing.
    A question the analyst can see and correct must route the same way whatever
    screen it was typed on.
    """
    for question in (
        "What evidence is driving this?",
        "Summarize the collected evidence",
        "What changed in this investigation?",
    ):
        intent = parse_intent(question)
        assert intent.intent is IntentKind.EVIDENCE_SEARCH, question
        assert intent.tools == (ToolName.SEARCH_EVIDENCE,), question


def test_search_terms_are_the_analysts_words_only() -> None:
    """Grounding words must not become AND-ed search terms.

    With the grounding suffix appended, every query reached the search engine
    carrying `context`, `current`, `investigation`, `viewing`, the view name and
    the case name as required terms — so a two-word question could not match
    anything at all.
    """
    terms = build_structured_query("compare the competing hypotheses").terms
    assert "context" not in terms
    assert "viewing" not in terms
    assert "investigation" not in terms
    assert terms == ("compare", "the", "competing", "hypotheses")


def test_a_relative_window_becomes_a_query_bound() -> None:
    """A named window must actually narrow the query.

    "Summarize the last 24 hours" is one of the console's own suggestions. The
    query could not express a window, so `since` stayed `None` and the timeline
    tool returned the entire case history — the analyst asked for a day and was
    given everything, with nothing on screen saying so.
    """
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    query = build_structured_query("Summarize the last 24 hours", now=now)

    assert query.since == datetime(2026, 2, 28, 12, 0, tzinfo=UTC)
    assert query.until == now


@pytest.mark.parametrize(
    ("question", "expected_since"),
    [
        ("events in the last 30 minutes", datetime(2026, 3, 1, 11, 30, tzinfo=UTC)),
        ("activity in the last 2 weeks", datetime(2026, 2, 15, 12, 0, tzinfo=UTC)),
        ("what happened in the last week", datetime(2026, 2, 22, 12, 0, tzinfo=UTC)),
        ("anything in the past 3 days", datetime(2026, 2, 26, 12, 0, tzinfo=UTC)),
    ],
)
def test_each_relative_unit_is_read(question: str, expected_since: datetime) -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    assert build_structured_query(question, now=now).since == expected_since


def test_an_absent_window_leaves_the_query_unbounded() -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    for question in ("find evidence about shadowbroker", "who is the leading actor?"):
        query = build_structured_query(question, now=now)
        assert query.since is None, question
        assert query.until is None, question


def test_an_absurd_window_is_clamped_rather_than_returning_everything() -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    query = build_structured_query("everything in the last 500 days", now=now)
    assert query.since == now - timedelta(days=90)


def test_a_named_window_routes_to_the_timeline() -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    intent = parse_intent("Summarize the last 24 hours", now=now)
    assert intent.intent is IntentKind.TIMELINE
    assert intent.rule == "time-window"


def test_an_explicit_marker_still_wins_over_a_window() -> None:
    """A question naming a window *and* a more specific verb keeps the verb."""
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    intent = parse_intent("compare the hypotheses from the last 7 days", now=now)
    assert intent.intent is IntentKind.HYPOTHESIS_COMPARISON
