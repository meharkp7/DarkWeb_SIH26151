from dataclasses import dataclass
from typing import Any

from aegis.synthetic.evidence import SyntheticEvidence, SyntheticRelationship


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float


@dataclass(frozen=True)
class EvidenceGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


class EvidenceGraphBuilder:
    """Build a validated graph from synthetic evidence and relationships."""

    def build(
        self,
        evidence: list[SyntheticEvidence],
        relationships: list[SyntheticRelationship],
    ) -> EvidenceGraph:
        evidence_ids = {item.evidence_id for item in evidence}

        nodes = tuple(
            GraphNode(
                node_id=item.evidence_id,
                node_type="evidence",
                attributes={
                    "actor_id": item.actor_id,
                    "evidence_type": item.evidence_type,
                    "value": item.value,
                    "confidence": item.confidence,
                    "platform": item.platform,
                    "independence_group": item.independence_group,
                    "observed_at": item.observed_at.isoformat(),
                },
            )
            for item in evidence
        )

        edges: list[GraphEdge] = []

        for relationship in relationships:
            if relationship.source_evidence_id not in evidence_ids:
                raise ValueError(f"Unknown source evidence: {relationship.source_evidence_id}")

            if relationship.target_evidence_id not in evidence_ids:
                raise ValueError(f"Unknown target evidence: {relationship.target_evidence_id}")

            if not 0.0 <= relationship.confidence <= 1.0:
                raise ValueError(
                    f"Relationship confidence must be between 0 and 1: {relationship.confidence}"
                )

            edges.append(
                GraphEdge(
                    edge_id=relationship.relationship_id,
                    source_id=relationship.source_evidence_id,
                    target_id=relationship.target_evidence_id,
                    relationship_type=relationship.relationship_type,
                    confidence=relationship.confidence,
                )
            )

        return EvidenceGraph(
            nodes=nodes,
            edges=tuple(edges),
        )
