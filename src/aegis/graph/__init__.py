"""Temporal graph layer (Phase 08).

In-process store implementing the six required queries (two-hop
neighborhood, common identifiers, historical associations, time-filtered
neighborhood, evidence path, candidate-pair similarity), plus a lazy
Neo4j adapter issuing equivalent parameterized Cypher.
"""

from aegis.graph.neo4j import CypherBuilder, CypherQuery, Neo4jGraphAdapter
from aegis.graph.schema import (
    EDGE_PROPERTIES,
    GRAPH_TYPE_LABELS,
    PLAN_REQUIRED_EDGE_TYPES,
    GraphValidationError,
    MissingNodeError,
    NodeLabel,
    active_at,
    ensure_aware,
    label_for_entity_type,
    overlaps,
)
from aegis.graph.store import (
    EvidencePath,
    GraphEdge,
    GraphNode,
    InMemoryGraphStore,
    Neighborhood,
    NeighborhoodSimilarity,
)

__all__ = [
    "EDGE_PROPERTIES",
    "GRAPH_TYPE_LABELS",
    "PLAN_REQUIRED_EDGE_TYPES",
    "CypherBuilder",
    "CypherQuery",
    "EvidencePath",
    "GraphEdge",
    "GraphNode",
    "GraphValidationError",
    "InMemoryGraphStore",
    "MissingNodeError",
    "Neighborhood",
    "NeighborhoodSimilarity",
    "Neo4jGraphAdapter",
    "NodeLabel",
    "active_at",
    "ensure_aware",
    "label_for_entity_type",
    "overlaps",
]
