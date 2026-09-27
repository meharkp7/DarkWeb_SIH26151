import json

from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.graph import EvidenceGraphBuilder
from aegis.synthetic.graph_serializer import EvidenceGraphSerializer


def _build_graph():
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, relationships = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    return EvidenceGraphBuilder().build(evidence, relationships)


def test_graph_serializes_to_expected_structure() -> None:
    graph = _build_graph()

    payload = EvidenceGraphSerializer.to_dict(graph)

    assert set(payload) == {"nodes", "edges"}
    assert len(payload["nodes"]) == len(graph.nodes)
    assert len(payload["edges"]) == len(graph.edges)


def test_graph_json_is_valid_and_deterministic() -> None:
    graph = _build_graph()

    first = EvidenceGraphSerializer.to_json(graph)
    second = EvidenceGraphSerializer.to_json(graph)

    assert first == second

    parsed = json.loads(first)
    assert len(parsed["nodes"]) == len(graph.nodes)
    assert len(parsed["edges"]) == len(graph.edges)


def test_graph_serialization_preserves_edge_fields() -> None:
    graph = _build_graph()

    payload = EvidenceGraphSerializer.to_dict(graph)
    edge = payload["edges"][0]

    assert edge["edge_id"] == graph.edges[0].edge_id
    assert edge["source_id"] == graph.edges[0].source_id
    assert edge["target_id"] == graph.edges[0].target_id
    assert edge["relationship_type"] == graph.edges[0].relationship_type
    assert edge["confidence"] == graph.edges[0].confidence
