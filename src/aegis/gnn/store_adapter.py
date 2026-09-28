"""Adapters from the canonical Phase 08 graph into the Phase 19 model graph.

The adapter is deliberately strict: production callers must provide a feature
vector and observation time for every graph node.  It never hashes identifiers
or silently invents timestamps, which prevents identity leakage and temporal
leakage from entering the research model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

import numpy as np

from aegis.gnn.graph import GnnNodeType, HeteroGraph
from aegis.graph import InMemoryGraphStore, NodeLabel, ensure_aware
from aegis.ontology import RelationshipType

NodeFeatures = Mapping[str, Sequence[float]]
NodeTimes = Mapping[str, datetime]
ExtraNodes = Mapping[str, tuple[GnnNodeType, datetime, Sequence[float]]]
ExtraEdges = Iterable[tuple[RelationshipType, str, str, datetime]]


def build_gnn_graph(
    store: InMemoryGraphStore,
    *,
    features: NodeFeatures,
    observed_at: NodeTimes,
    cutoff: datetime | None = None,
    extra_nodes: ExtraNodes | None = None,
    extra_edges: ExtraEdges = (),
) -> HeteroGraph:
    """Convert a canonical graph snapshot into the Phase 19 graph.

    ``features`` and ``observed_at`` are keyed by canonical node id.  Every
    included node must have both values.  When ``cutoff`` is supplied, only
    edges whose observation window intersects the point-in-time snapshot and
    whose first observation is no later than the cutoff are retained.
    """

    moment = ensure_aware(cutoff, field_name="cutoff") if cutoff is not None else None
    graph = HeteroGraph()
    included: set[str] = set()

    for node_id, node in sorted(store.nodes.items()):
        node_type = _node_type(node.label)
        if node_type is None:
            continue
        if node_id not in features:
            raise ValueError(f"missing GNN features for node {node_id!r}")
        if node_id not in observed_at:
            raise ValueError(f"missing observation time for node {node_id!r}")
        node_time = ensure_aware(observed_at[node_id], field_name="observed_at")
        if moment is not None and node_time > moment:
            continue
        vector = np.asarray(features[node_id], dtype=np.float64)
        if vector.ndim != 1 or vector.size == 0:
            raise ValueError(f"features for node {node_id!r} must be a non-empty 1-D vector")
        if not np.isfinite(vector).all():
            raise ValueError(f"features for node {node_id!r} contain non-finite values")
        graph.add_node(node_id, node_type, observed_at=node_time)
        included.add(node_id)

    for node_id, (node_type, node_time, vector_values) in sorted((extra_nodes or {}).items()):
        if node_id in included:
            raise ValueError(f"duplicate extra node id {node_id!r}")
        aware_time = ensure_aware(node_time, field_name="observed_at")
        if moment is not None and aware_time > moment:
            continue
        vector = np.asarray(vector_values, dtype=np.float64)
        if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
            raise ValueError(f"features for extra node {node_id!r} are invalid")
        graph.add_node(node_id, node_type, observed_at=aware_time)
        included.add(node_id)

    for edge in sorted(store.edges.values(), key=lambda item: item.edge_id):
        if edge.source not in included or edge.target not in included:
            continue
        if moment is not None:
            if edge.first_seen > moment or edge.last_seen < moment:
                continue
        edge_time = min(edge.last_seen, moment) if moment is not None else edge.last_seen
        graph.add_edge(
            edge.rel_type,
            edge.source,
            edge.target,
            observed_at=edge_time,
        )

    if not graph.edges:
        raise ValueError("graph snapshot contains no usable edges")

    for node_type in sorted({node.node_type for node in graph.nodes}, key=lambda item: item.value):
        nodes = [node for node in graph.nodes if node.node_type is node_type]
        widths = {
            len(
                features[node.node_id]
                if node.node_id in features
                else (extra_nodes or {})[node.node_id][2]
            )
            for node in nodes
        }
        if len(widths) != 1:
            raise ValueError(f"feature width must be constant within node type {node_type.value}")
        graph.set_features(
            node_type,
            np.asarray(
                [
                    features[node.node_id]
                    if node.node_id in features
                    else (extra_nodes or {})[node.node_id][2]
                    for node in nodes
                ],
                dtype=np.float64,
            ),
        )

    graph.compile()
    return graph


def _node_type(label: NodeLabel) -> GnnNodeType:
    mapping = {
        NodeLabel.ACTOR: GnnNodeType.ACTOR,
        NodeLabel.HANDLE: GnnNodeType.HANDLE,
        NodeLabel.PGP: GnnNodeType.PGP,
        NodeLabel.WALLET: GnnNodeType.WALLET,
        NodeLabel.MARKETPLACE: GnnNodeType.MARKETPLACE,
        NodeLabel.FORUM: GnnNodeType.FORUM,
        NodeLabel.INFRASTRUCTURE: GnnNodeType.INFRASTRUCTURE,
        NodeLabel.POST: GnnNodeType.POST,
        NodeLabel.EVIDENCE: GnnNodeType.EVIDENCE,
    }
    return mapping[label]
