import pytest

from aegis.synthetic.evidence import SyntheticRelationship
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.graph import EvidenceGraphBuilder


def test_graph_contains_all_evidence_nodes() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, relationships = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    graph = EvidenceGraphBuilder().build(evidence, relationships)

    assert len(graph.nodes) == len(evidence)
    assert {node.node_id for node in graph.nodes} == {item.evidence_id for item in evidence}


def test_graph_contains_valid_relationship_edges() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, relationships = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    graph = EvidenceGraphBuilder().build(evidence, relationships)

    assert len(graph.edges) == len(relationships)

    node_ids = {node.node_id for node in graph.nodes}

    for edge in graph.edges:
        assert edge.source_id in node_ids
        assert edge.target_id in node_ids
        assert 0.0 <= edge.confidence <= 1.0


def test_graph_rejects_dangling_relationship() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(1)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    relationship = SyntheticRelationship(
        relationship_id="dangling-edge",
        source_evidence_id=evidence[0].evidence_id,
        target_evidence_id="missing-evidence",
        relationship_type="cross_platform_identity",
        confidence=0.9,
    )

    with pytest.raises(ValueError, match="Unknown target evidence"):
        EvidenceGraphBuilder().build(evidence, [relationship])


def test_graph_preserves_relationship_identity() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(1)
    evidence, relationships = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    graph = EvidenceGraphBuilder().build(evidence, relationships)

    assert [edge.edge_id for edge in graph.edges] == [
        relationship.relationship_id for relationship in relationships
    ]
