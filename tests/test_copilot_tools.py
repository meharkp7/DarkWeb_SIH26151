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

    # Ids are the hypotheses themselves, in hypothesis-id order. This test
    # previously asserted the *evidence* ids in pack order, which meant a
    # claim about a hypothesis cited an evidence record — the claim named a
    # different kind of object from the one it described. The determinism
    # being protected here is the ordering, so that is what is asserted.
    expected_ids = tuple(
        str(hypothesis.hypothesis_id)
        for hypothesis in sorted((h1, h2), key=lambda h: str(h.hypothesis_id))
    )

    assert pack.ids == expected_ids
    assert all(item.tool.value == "compare_hypotheses" for item in pack.items)

    # A re-run over the same input must produce the same citations, or the
    # same question cites different records each time it is asked.
    again = compare_hypotheses(
        CopilotToolContext(hypotheses=(h1, h2)),
        (h2.hypothesis_id, h1.hypothesis_id),
    )
    assert again.ids == expected_ids


def test_missing_dependencies_fail_closed() -> None:
    with pytest.raises(RuntimeError):
        get_actor(CopilotToolContext(), "actor")


def test_every_tool_produces_a_readable_summary_and_a_data_region() -> None:
    """No tool may fall back to the positional template or an empty data region.

    `_pack` has a default summary of ``"<tool> returned <Type> record <id>"`` and
    an empty ``data_text`` when a tool passes neither ``describe`` nor
    ``render``. `search_evidence` and `get_timeline` — the two tools the default
    and timeline routes actually use — did exactly that, so the most common
    answers in the product were a list of uuids with no content beside them.
    Nothing caught it because the pack was structurally valid.

    This asserts the property for the tools that need no database, which is
    where the regression is cheapest to reintroduce.
    """
    events = (
        TimelineEvent(
            "ev-1",
            "actor-1",
            TimelineEventKind.HANDLE,
            datetime(2026, 1, 2, tzinfo=UTC),
            "handle-b appeared on a new forum",
            ("e1",),
        ),
    )
    packs = {
        "get_timeline": get_timeline(CopilotToolContext(timeline=events), "actor-1"),
        "compare_hypotheses": compare_hypotheses(
            CopilotToolContext(
                hypotheses=(
                    Hypothesis(
                        case_id=uuid4(),
                        hypothesis_id=uuid4(),
                        kind=HypothesisKind.SAME_ACTOR,
                        subject_entity_id=uuid4(),
                        object_entity_id=uuid4(),
                        links=(
                            HypothesisEvidenceLink(
                                evidence_id=uuid4(),
                                role=EvidenceRole.SUPPORTING,
                                modality="handle",
                                independence_group="source-a",
                            ),
                        ),
                    ),
                )
            ),
            (),
        ),
    }

    for tool, pack in packs.items():
        assert pack.items, f"{tool} returned nothing to describe"
        for item in pack.items:
            assert " returned " not in item.summary, f"{tool} fell back to the template"
            assert item.summary.strip() != "", f"{tool} produced an empty summary"
            assert item.data_text.strip() != "", f"{tool} produced an empty data region"
            assert " object at 0x" not in item.data_text, f"{tool} leaked a Python repr"
