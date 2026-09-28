from datetime import UTC, datetime

import pytest

from aegis.gnn.graph import GnnNodeType
from aegis.gnn.store_adapter import build_gnn_graph
from aegis.graph import InMemoryGraphStore, NodeLabel
from aegis.ontology import EntityType, RelationshipType


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.add_node("actor", NodeLabel.ACTOR, entity_type=EntityType.ACTOR_HYPOTHESIS)
    store.add_node("handle", NodeLabel.HANDLE, entity_type=EntityType.HANDLE)
    store.add_edge(
        RelationshipType.USES_HANDLE,
        "actor",
        "handle",
        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen=datetime(2026, 1, 20, tzinfo=UTC),
        confidence=0.9,
        evidence_ids=["e1"],
    )
    return store


def test_adapter_preserves_typed_nodes_and_builds_point_in_time_snapshot() -> None:
    store = _store()
    features = {"actor": [1.0, 0.0], "handle": [0.0, 1.0]}
    times = {
        "actor": datetime(2026, 1, 1, tzinfo=UTC),
        "handle": datetime(2026, 1, 1, tzinfo=UTC),
    }
    graph = build_gnn_graph(
        store,
        features=features,
        observed_at=times,
        cutoff=datetime(2026, 1, 10, tzinfo=UTC),
    )
    assert graph.node_count == 2
    assert graph.edge_count == 1
    assert graph.input_dims[GnnNodeType.ACTOR] == 2
    assert graph.input_dims[GnnNodeType.HANDLE] == 2


def test_adapter_can_add_behavior_profile_nodes_without_changing_phase_08_schema() -> None:
    store = _store()
    graph = build_gnn_graph(
        store,
        features={"actor": [1.0, 0.0], "handle": [0.0, 1.0]},
        observed_at={
            "actor": datetime(2026, 1, 1, tzinfo=UTC),
            "handle": datetime(2026, 1, 1, tzinfo=UTC),
        },
        extra_nodes={
            "behavior": (GnnNodeType.BEHAVIOR_PROFILE, datetime(2026, 1, 1, tzinfo=UTC), [0.2, 0.8])
        },
        extra_edges=(
            (
                RelationshipType.ASSOCIATED_WITH,
                "actor",
                "behavior",
                datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ),
    )
    assert GnnNodeType.BEHAVIOR_PROFILE in graph.node_types
    assert graph.node_count == 3


def test_adapter_excludes_future_nodes_and_edges() -> None:
    store = _store()
    store.add_node("future", NodeLabel.HANDLE, entity_type=EntityType.HANDLE)
    features = {"actor": [1.0], "handle": [0.0], "future": [0.5]}
    times = {
        "actor": datetime(2026, 1, 1, tzinfo=UTC),
        "handle": datetime(2026, 1, 1, tzinfo=UTC),
        "future": datetime(2026, 2, 1, tzinfo=UTC),
    }
    graph = build_gnn_graph(
        store,
        features=features,
        observed_at=times,
        cutoff=datetime(2026, 1, 10, tzinfo=UTC),
    )
    assert not graph.has_node("future")


def test_adapter_rejects_missing_features() -> None:
    store = _store()
    with pytest.raises(ValueError, match="missing GNN features"):
        build_gnn_graph(
            store,
            features={"actor": [1.0]},
            observed_at={
                "actor": datetime(2026, 1, 1, tzinfo=UTC),
                "handle": datetime(2026, 1, 1, tzinfo=UTC),
            },
        )
