from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aegis.copilot.tools import (
    CopilotToolContext,
    compare_hypotheses,
    get_actor,
    get_timeline,
    query_graph,
)
from aegis.graph.schema import NodeLabel
from aegis.graph.store import InMemoryGraphStore
from aegis.ontology import EntityType, RelationshipType
from aegis.schemas.hypothesis import (
    EvidenceRole,
    Hypothesis,
    HypothesisEvidenceLink,
    HypothesisKind,
)
from aegis.timeline.types import TimelineEvent, TimelineEventKind


def test_query_graph_preserves_edge_evidence() -> None:
    graph = InMemoryGraphStore()

    graph.add_node("a", NodeLabel.ACTOR, entity_type=EntityType.ACTOR_HYPOTHESIS)
    graph.add_node("h", NodeLabel.HANDLE, entity_type=EntityType.HANDLE)

    graph.add_edge(
        RelationshipType.USES_HANDLE,
        "a",
        "h",
        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen=datetime(2026, 1, 2, tzinfo=UTC),
        confidence=0.9,
        evidence_ids=("e1", "e2"),
    )

    pack = query_graph(CopilotToolContext(graph=graph), "a")

    assert pack.ids == ("e1",)
    assert "e2" in pack.items[0].data_text
    assert all(item.tool.value == "query_graph" for item in pack.items)
    assert all(item.provenance["tool"] == "query_graph" for item in pack.items)


def test_get_actor_returns_evidence_items() -> None:
    graph = InMemoryGraphStore()
    graph.add_node("a", NodeLabel.ACTOR, entity_type=EntityType.ACTOR_HYPOTHESIS)

    pack = get_actor(CopilotToolContext(graph=graph), "a")

    assert len(pack.items) == 2
    assert [item.kind for item in pack.items] == ["GraphNode", "Neighborhood"]
    assert all(item.tool.value == "get_actor" for item in pack.items)


def test_timeline_is_sorted_and_evidence_backed() -> None:
    events = (
        TimelineEvent(
            "2",
            "actor-1",
            TimelineEventKind.HANDLE,
            datetime(2026, 1, 2, tzinfo=UTC),
            "handle-b",
            ("e2",),
        ),
        TimelineEvent(
            "1",
            "actor-1",
            TimelineEventKind.HANDLE,
            datetime(2026, 1, 1, tzinfo=UTC),
            "handle-a",
            ("e1",),
        ),
    )

    pack = get_timeline(CopilotToolContext(timeline=events), "actor-1")

    assert pack.ids == ("e1", "e2")
    assert len(pack.items) == 2
    assert all(item.kind == "TimelineEvent" for item in pack.items)
    assert all(item.tool.value == "get_timeline" for item in pack.items)


def test_compare_hypotheses_is_deterministic() -> None:
    case_id = uuid4()

    h1 = Hypothesis(
        case_id=case_id,
        subject_entity_id=uuid4(),
        object_entity_id=uuid4(),
        kind=HypothesisKind.SAME_ACTOR,
        links=(
            HypothesisEvidenceLink(
                evidence_id=uuid4(),
                role=EvidenceRole.SUPPORTING,
                modality="handle",
                independence_group="source-a",
            ),
        ),
    )

    h2 = Hypothesis(
        case_id=case_id,
        subject_entity_id=uuid4(),
        object_entity_id=uuid4(),
        kind=HypothesisKind.UNRELATED,
    )

    pack = compare_hypotheses(
        CopilotToolContext(hypotheses=(h2, h1)),
        (h1.hypothesis_id, h2.hypothesis_id),
    )

    expected_ids = tuple(
        str(link.evidence_id)
        for hypothesis in sorted(
            (h1, h2),
            key=lambda h: str(h.hypothesis_id),
        )
        for link in hypothesis.links
    )

    assert pack.ids[0] == expected_ids[0]
    assert pack.ids[1] == "compare_hypotheses:1"
    assert all(item.tool.value == "compare_hypotheses" for item in pack.items)


def test_missing_dependencies_fail_closed() -> None:
    with pytest.raises(RuntimeError):
        get_actor(CopilotToolContext(), "actor")
