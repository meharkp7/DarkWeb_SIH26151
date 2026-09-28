from datetime import UTC, datetime

from aegis.gnn.graph import GnnNodeType, HeteroGraph
from aegis.gnn.models import RGCNEncoder
from aegis.gnn.training import GnnPairTrainer, LabeledNodePair
from aegis.ontology import RelationshipType


def _graph() -> HeteroGraph:
    graph = HeteroGraph()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for node_id, node_type, features in (
        ("actor", GnnNodeType.ACTOR, [[1.0, 0.0]]),
        ("handle", GnnNodeType.HANDLE, [[0.0, 1.0]]),
        ("wallet", GnnNodeType.WALLET, [[0.5, 0.5]]),
    ):
        graph.add_node(node_id, node_type, observed_at=now)
        graph.set_features(node_type, features)
    graph.add_edge(RelationshipType.USES_HANDLE, "actor", "handle", observed_at=now)
    graph.add_edge(RelationshipType.ASSOCIATED_WITH_WALLET, "actor", "wallet", observed_at=now)
    return graph


def test_supervised_pair_head_trains_on_labeled_graph_pairs() -> None:
    encoder = RGCNEncoder().fit(_graph())
    trainer = GnnPairTrainer(encoder, epochs=100).fit(
        [LabeledNodePair("actor", "handle", 1), LabeledNodePair("actor", "wallet", 0)]
    )
    positive = trainer.predict("actor", "handle")
    negative = trainer.predict("actor", "wallet")
    assert positive.model_id == "r-gcn-trained"
    assert positive.raw_score > negative.raw_score
