from datetime import UTC, datetime

import torch

from aegis.gnn.graph import GnnNodeType, HeteroGraph
from aegis.gnn.torch_models import TemporalHeterogeneousGNN
from aegis.gnn.torch_training import TemporalPair, split_by_group, train_pair_model
from aegis.ontology import RelationshipType


def _graph() -> HeteroGraph:
    graph = HeteroGraph()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    nodes = [
        ("a0", GnnNodeType.ACTOR, [1.0, 0.0, 0.1]),
        ("a1", GnnNodeType.ACTOR, [0.95, 0.05, 0.1]),
        ("a2", GnnNodeType.ACTOR, [0.0, 1.0, 0.8]),
        ("h0", GnnNodeType.HANDLE, [1.0, 0.0, 0.0]),
        ("h1", GnnNodeType.HANDLE, [0.0, 1.0, 0.0]),
    ]
    for node_id, node_type, _ in nodes:
        graph.add_node(node_id, node_type, observed_at=now)
    graph.set_features(
        GnnNodeType.ACTOR,
        [nodes[0][2], nodes[1][2], nodes[2][2]],
    )
    graph.set_features(
        GnnNodeType.HANDLE,
        [nodes[3][2], nodes[4][2]],
    )
    graph.add_edge(RelationshipType.USES_HANDLE, "a0", "h0", observed_at=now)
    graph.add_edge(RelationshipType.USES_HANDLE, "a1", "h0", observed_at=now)
    graph.add_edge(RelationshipType.USES_HANDLE, "a2", "h1", observed_at=now)
    graph.compile()
    return graph


def test_learned_temporal_gnn_forward_is_finite() -> None:
    model = TemporalHeterogeneousGNN(_graph(), hidden_dim=16, heads=4, layers=2)
    embedding = model.encode()
    assert embedding.shape == (5, 16)
    assert torch.isfinite(embedding).all()
    score = model.predict_pair("a0", "a1").raw_score
    assert 0.0 <= score <= 1.0


def test_contradiction_penalty_reduces_score() -> None:
    model = TemporalHeterogeneousGNN(_graph(), hidden_dim=16, heads=4)
    clean = model.predict_pair("a0", "a1").raw_score
    contradicted = model.predict_pair("a0", "a1", contradiction_weight=2.0).raw_score
    assert contradicted < clean


def test_group_split_has_no_overlap() -> None:
    pairs = [TemporalPair(f"a{i}", f"b{i}", i % 2, f"actor-{i}") for i in range(9)]
    split = split_by_group(pairs)
    groups = [set(p.group_id for p in part) for part in (split.train, split.validation, split.test)]
    assert not groups[0] & groups[1]
    assert not groups[0] & groups[2]
    assert not groups[1] & groups[2]


def test_training_updates_model_and_returns_test_scores() -> None:
    model = TemporalHeterogeneousGNN(_graph(), hidden_dim=16, heads=4)
    train = tuple(TemporalPair("a0", "a1", 1, "g0") for _ in range(2)) + tuple(
        TemporalPair("a0", "a2", 0, "g1") for _ in range(2)
    )
    validation = (TemporalPair("a1", "a2", 0, "g2"), TemporalPair("a0", "a1", 1, "g3"))
    test = (TemporalPair("a0", "a2", 0, "g4"), TemporalPair("a0", "a1", 1, "g5"))
    result = train_pair_model(model, train, validation, test, epochs=4, patience=2)
    assert result.best_epoch >= 1
    assert len(result.test_scores) == 2
    assert all(0.0 <= score <= 1.0 for score in result.test_scores)
