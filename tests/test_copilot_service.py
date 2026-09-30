from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aegis.copilot.service import run_copilot
from aegis.copilot.tools import CopilotToolContext
from aegis.copilot.types import IntentKind
from aegis.graph.schema import EntityType, NodeLabel
from aegis.graph.store import InMemoryGraphStore
from aegis.schemas.evidence import Evidence
from aegis.search import IndexedDocument, InProcessSearchEngine
from aegis.timeline.types import TimelineEvent, TimelineEventKind


def test_run_copilot_routes_default_search() -> None:
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))

    answer = run_copilot(
        "find evidence about shadowbroker",
        CopilotToolContext(search=search),
    )

    assert answer.intent.intent is IntentKind.EVIDENCE_SEARCH
    assert answer.tools_run
    assert answer.pack.ids == (str(evidence.evidence_id),)
    assert answer.claims


def test_run_copilot_routes_actor_profile() -> None:
    graph = InMemoryGraphStore()
    graph.add_node(
        "shadowbroker",
        NodeLabel.ACTOR,
        entity_type=EntityType.ACTOR_HYPOTHESIS,
    )

    answer = run_copilot(
        "show actor:shadowbroker profile",
        CopilotToolContext(graph=graph),
    )

    assert answer.intent.intent is IntentKind.ACTOR_PROFILE
    assert answer.tools_run
    assert len(answer.pack.items) == 2


def test_run_copilot_report_intent_does_not_execute_report_as_retrieval() -> None:
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))

    answer = run_copilot(
        "create a report about shadowbroker",
        CopilotToolContext(search=search),
    )

    assert answer.intent.intent is IntentKind.REPORT_BRIEF
    assert answer.report is None
    assert answer.tools_run[-1].value == "generate_report"


def test_an_unavailable_tool_degrades_instead_of_raising() -> None:
    """A question the analyst was entitled to ask must not become a 500.

    The graph is only built for a case-scoped request, so asking "trace
    actor:x" from the platform-wide context raised `RuntimeError` straight out
    of the service and the endpoint answered 500. A missing optional adapter is
    a capability limit, and the synthesis layer already states it truthfully.
    """
    answer = run_copilot("trace actor:shadowbroker", CopilotToolContext())

    # The question is still recognised and the tool that would answer it is
    # still named; only the tool contributes nothing, which is the capability
    # limit the analyst needs to see. What matters is that this is a 200 with a
    # stated answer rather than an exception out of the service.
    assert answer.intent.intent is IntentKind.ACTOR_PROFILE
    assert answer.tools_run
    assert answer.pack.items == ()
    assert answer.text.strip() != ""
    assert "Traceback" not in answer.text


def test_an_unknown_id_degrades_instead_of_raising() -> None:
    """A wrong hypothesis id is a normal outcome, not a server fault.

    `compare_hypotheses` raises `LookupError` for an id that is not in scope.
    That is a question with a bad premise, so the answer is an empty
    comparison — not an exception that surfaces as a server error.
    """
    answer = run_copilot(f"compare hypothesis:{uuid4()}", CopilotToolContext(hypotheses=()))

    assert answer.intent.intent is IntentKind.HYPOTHESIS_COMPARISON
    assert answer.pack.items == ()


def test_the_case_timeline_is_reachable_without_typing_an_id() -> None:
    """`load_timeline` stamps every event with the case, so the case is the subject.

    "How did this investigation evolve" names no subject, so the timeline tool
    used to match none and return nothing — a question the console itself
    suggests, unanswerable by construction.
    """
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))
    case_id = uuid4()

    answer = run_copilot(
        "timeline of this investigation",
        CopilotToolContext(
            search=search,
            timeline=(
                TimelineEvent(
                    "ev-1",
                    str(case_id),
                    TimelineEventKind.HANDLE,
                    datetime(2026, 1, 2, tzinfo=UTC),
                    "a new handle appeared",
                    (str(evidence.evidence_id),),
                ),
            ),
        ),
    )

    assert "get_timeline" in [tool.value for tool in answer.tools_run]
    assert any(item.tool.value == "get_timeline" for item in answer.pack.items)
