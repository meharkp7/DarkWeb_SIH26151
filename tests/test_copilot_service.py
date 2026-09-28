from __future__ import annotations

from aegis.copilot.service import run_copilot
from aegis.copilot.tools import CopilotToolContext
from aegis.copilot.types import IntentKind
from aegis.graph.schema import EntityType, NodeLabel
from aegis.graph.store import InMemoryGraphStore
from aegis.schemas.evidence import Evidence
from aegis.search import IndexedDocument, InProcessSearchEngine


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
