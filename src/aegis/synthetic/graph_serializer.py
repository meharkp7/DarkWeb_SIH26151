import json
from typing import Any

from aegis.synthetic.graph import EvidenceGraph


class EvidenceGraphSerializer:
    """Serialize an EvidenceGraph into a stable JSON-compatible structure."""

    @staticmethod
    def to_dict(graph: EvidenceGraph) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "attributes": node.attributes,
                }
                for node in graph.nodes
            ],
            "edges": [
                {
                    "edge_id": edge.edge_id,
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "relationship_type": edge.relationship_type,
                    "confidence": edge.confidence,
                }
                for edge in graph.edges
            ],
        }

    @classmethod
    def to_json(cls, graph: EvidenceGraph) -> str:
        return json.dumps(
            cls.to_dict(graph),
            sort_keys=True,
            separators=(",", ":"),
        )
