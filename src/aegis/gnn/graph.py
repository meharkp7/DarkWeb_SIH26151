"""Heterogeneous temporal graph container for the Phase 19 GNN models.

Why this module exists: the Phase 08 store (:class:`aegis.graph.store`)
answers analyst queries over string-keyed nodes, while the Phase 19
models need typed, fixed-width NumPy feature matrices and compiled edge
arrays for message passing.  This container is the bridge — it keeps the
plan's node-type vocabulary, records a per-node observation time and a
per-edge observation time, and compiles everything into the layout the
R-GCN/HGT layers consume exactly once.

Node types are :class:`GnnNodeType`.  Nine of the ten members map 1:1
onto :class:`aegis.graph.NodeLabel` (the source of truth for graph
labels); the tenth — ``BEHAVIOR_PROFILE`` — is required by the Phase 19
plan but deliberately absent from ``NodeLabel`` because the Phase 08
schema treats behavioural profiles as analytical objects that live
outside the property graph.  Rather than edit the frozen schema, the GNN
declares its own enum that *extends* the label set losslessly
(:func:`node_type_for_label` / :func:`label_for_node_type`).

Edge relations are the ontology's :class:`aegis.ontology.RelationshipType`
members — no parallel relation vocabulary is invented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from aegis.graph import MissingNodeError, NodeLabel, ensure_aware
from aegis.ontology import EntityType, RelationshipType

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


class GnnNodeType(StrEnum):
    """Node-type vocabulary of the Phase 19 heterogeneous graph.

    Declaration order mirrors :class:`aegis.graph.NodeLabel` (the nine
    property-graph labels) plus the plan-mandated ``BEHAVIOR_PROFILE``
    analytical node type, so the enum can be used directly as a stable
    parameter index in the model layers.
    """

    ACTOR = "Actor"
    HANDLE = "Handle"
    PGP = "PGP"
    WALLET = "Wallet"
    MARKETPLACE = "Marketplace"
    FORUM = "Forum"
    INFRASTRUCTURE = "Infrastructure"
    POST = "Post"
    EVIDENCE = "Evidence"
    BEHAVIOR_PROFILE = "BehaviorProfile"


#: Node labels that exist in the frozen Phase 08 schema.
_NODE_TYPE_FROM_LABEL: dict[NodeLabel, GnnNodeType] = {
    label: GnnNodeType(label.value) for label in NodeLabel
}
_LABEL_FROM_NODE_TYPE: dict[GnnNodeType, NodeLabel] = {
    node_type: label for label, node_type in _NODE_TYPE_FROM_LABEL.items()
}
#: The analytical entity type whose GNN node type has no ``NodeLabel``.
_BEHAVIOR_PROFILE_BY_ENTITY: dict[EntityType, GnnNodeType] = {
    EntityType.BEHAVIORAL_PROFILE: GnnNodeType.BEHAVIOR_PROFILE
}


def node_type_for_label(label: NodeLabel) -> GnnNodeType:
    """Lossless mapping from a Phase 08 node label to a GNN node type."""
    return _NODE_TYPE_FROM_LABEL[label]


def label_for_node_type(node_type: GnnNodeType) -> NodeLabel | None:
    """The Phase 08 label for a GNN node type, or ``None`` for analytical
    types (``BehaviorProfile``) that the property graph does not model."""
    return _LABEL_FROM_NODE_TYPE.get(node_type)


def node_type_for_entity_type(entity_type: EntityType) -> GnnNodeType | None:
    """GNN node type for an ontology entity type, or ``None`` when the
    entity type is not a graph node (hypotheses, collection jobs, raw
    sources)."""
    behavior = _BEHAVIOR_PROFILE_BY_ENTITY.get(entity_type)
    if behavior is not None:
        return behavior
    from aegis.graph import label_for_entity_type  # local: avoids import cycle at module top

    label = label_for_entity_type(entity_type)
    return node_type_for_label(label) if label is not None else None


@dataclass(frozen=True)
class GraphNode:
    """One typed node with the time it was observed."""

    node_id: str
    node_type: GnnNodeType
    observed_at: datetime


@dataclass(frozen=True)
class GraphEdge:
    """One directed, typed, temporal edge between existing nodes."""

    source: str
    target: str
    relation: RelationshipType
    observed_at: datetime


@dataclass(frozen=True)
class SegmentLayout:
    """Edge indices grouped by target node, sorted ascending.

    Segment-softmax (attention pooling over each target's neighbours)
    and mean aggregation both need "edges of node i contiguously"; the
    layout is computed once at compile time so the per-epoch forward
    pass is a handful of ``reduceat`` calls instead of a Python loop
    over nodes.
    """

    order: IntArray
    starts: IntArray
    counts: IntArray


def as_float_array(values: npt.ArrayLike) -> FloatArray:
    """Coerce to a contiguous ``float64`` array (single typing funnel)."""
    return np.ascontiguousarray(np.asarray(values, dtype=np.float64))


def as_index_array(values: npt.ArrayLike) -> IntArray:
    """Coerce to a contiguous ``int64`` index array (typing funnel —
    NumPy returns ``intp`` for permutations, which is a distinct stub
    type on some platforms)."""
    return np.ascontiguousarray(np.asarray(values, dtype=np.int64))


def day_number(value: datetime) -> float:
    """Timezone-aware datetime expressed as fractional days since the
    Unix epoch — the time unit every layer and encoding shares."""
    aware = ensure_aware(value, field_name="observed_at")
    return aware.timestamp() / 86400.0


class HeteroGraph:
    """Typed, temporal multigraph compiled into NumPy arrays.

    Nodes are added with :meth:`add_node`, edges with :meth:`add_edge`
    (both directions are *aggregated* by the message-passing layers —
    association scoring is direction-agnostic, so the compiler expands
    every stored edge into two message slots instead of forcing callers
    to invent inverse-relation constants that the ontology does not
    define), and per-type feature matrices with :meth:`set_features`.
    :meth:`compile` freezes the structure and derives every array the
    layers read.  Mutation after compilation raises, so a model can
    never train against a graph that changes underneath it.
    """

    def __init__(self) -> None:
        self._nodes: list[GraphNode] = []
        self._index_by_id: dict[str, int] = {}
        self._edges: list[GraphEdge] = []
        self._features: dict[GnnNodeType, FloatArray] = {}
        self._compiled: _CompiledGraph | None = None

    # ------------------------------------------------------------ building

    def add_node(self, node_id: str, node_type: GnnNodeType, *, observed_at: datetime) -> None:
        """Register a node; duplicate ids raise (they would silently
        merge two entities and corrupt every index-based lookup)."""
        self._require_mutable()
        if not node_id:
            raise ValueError("node_id must be non-empty")
        if node_id in self._index_by_id:
            raise ValueError(f"duplicate node id {node_id!r}")
        aware = ensure_aware(observed_at, field_name="observed_at")
        self._index_by_id[node_id] = len(self._nodes)
        self._nodes.append(GraphNode(node_id=node_id, node_type=node_type, observed_at=aware))

    def add_edge(
        self,
        relation: RelationshipType,
        source: str,
        target: str,
        *,
        observed_at: datetime,
    ) -> None:
        """Register a directed edge between two existing nodes.

        Raises:
            MissingNodeError: If either endpoint has not been added —
                a dangling edge would index out of range during
                compilation instead of failing where it was built.
        """
        self._require_mutable()
        if source not in self._index_by_id:
            raise MissingNodeError(f"edge source {source!r} is not in the graph")
        if target not in self._index_by_id:
            raise MissingNodeError(f"edge target {target!r} is not in the graph")
        if source == target:
            raise ValueError("self-loops are not used; the layers carry a self transform")
        aware = ensure_aware(observed_at, field_name="observed_at")
        self._edges.append(
            GraphEdge(
                source=source,
                target=target,
                relation=relation,
                observed_at=aware,
            )
        )

    def set_features(self, node_type: GnnNodeType, matrix: npt.ArrayLike) -> None:
        """Attach the feature matrix for every node of ``node_type``.

        Rows follow that type's :meth:`add_node` order; columns define
        the input width the model's per-type projection expects.
        """
        self._require_mutable()
        array = as_float_array(matrix)
        if array.ndim != 2:
            raise ValueError(f"{node_type} features must be a 2-D matrix, got {array.ndim}-D")
        expected = sum(1 for node in self._nodes if node.node_type == node_type)
        if expected and array.shape[0] != expected:
            raise ValueError(
                f"{node_type} features have {array.shape[0]} rows but the graph has "
                f"{expected} nodes of that type"
            )
        if not np.all(np.isfinite(array)):
            raise ValueError(f"{node_type} features contain non-finite values")
        self._features[node_type] = array

    def compile(self) -> None:
        """Freeze the graph and derive the arrays the layers consume.

        Idempotent; called automatically by the models, so callers may
        simply build and hand the graph over.

        Raises:
            ValueError: On an empty graph, an empty edge set, or a node
                type without (or with mis-sized) features.
        """
        if self._compiled is not None:
            return
        if not self._nodes:
            raise ValueError("cannot compile a graph without nodes")
        if not self._edges:
            raise ValueError("cannot compile a graph without edges")

        node_types = tuple(sorted({node.node_type for node in self._nodes}, key=lambda t: t.value))
        features: dict[GnnNodeType, FloatArray] = {}
        for node_type in node_types:
            matrix = self._features.get(node_type)
            if matrix is None:
                raise ValueError(f"missing feature matrix for node type {node_type.value}")
            expected = sum(1 for node in self._nodes if node.node_type == node_type)
            if matrix.shape[0] != expected:
                raise ValueError(
                    f"{node_type} features have {matrix.shape[0]} rows, expected {expected}"
                )
            features[node_type] = matrix
        for node_type in self._features:
            if node_type not in node_types:
                raise ValueError(f"features supplied for absent node type {node_type.value}")

        relations = tuple(sorted({edge.relation for edge in self._edges}, key=lambda r: r.value))
        relation_index = {relation: index for index, relation in enumerate(relations)}

        sources = as_index_array([self._index_by_id[edge.source] for edge in self._edges])
        targets = as_index_array([self._index_by_id[edge.target] for edge in self._edges])
        relation_ids = as_index_array([relation_index[edge.relation] for edge in self._edges])
        edge_days = as_float_array([day_number(edge.observed_at) for edge in self._edges])

        # symmetrise: message j -> i for every stored (i, j) and (j, i)
        message_sources = np.concatenate([sources, targets])
        message_targets = np.concatenate([targets, sources])
        message_relation_ids = np.concatenate([relation_ids, relation_ids])
        message_days = np.concatenate([edge_days, edge_days])

        relation_groups = tuple(
            as_index_array(np.flatnonzero(message_relation_ids == index))
            for index in range(len(relations))
        )
        layout = _segment_layout(message_targets)
        node_days = as_float_array([day_number(node.observed_at) for node in self._nodes])
        type_ids = as_index_array([node_types.index(node.node_type) for node in self._nodes])

        self._compiled = _CompiledGraph(
            node_types=node_types,
            type_ids=type_ids,
            features=features,
            relations=relations,
            sources=sources,
            targets=targets,
            relation_ids=relation_ids,
            edge_days=edge_days,
            message_sources=message_sources,
            message_targets=message_targets,
            message_relation_ids=message_relation_ids,
            message_days=message_days,
            relation_groups=relation_groups,
            layout=layout,
            node_days=node_days,
            reference_day=float(node_days.min()),
        )
        self._edges = list(self._edges)  # keep introspection copies stable

    # ---------------------------------------------------------- accessors

    @property
    def compiled(self) -> bool:
        return self._compiled is not None

    @property
    def nodes(self) -> tuple[GraphNode, ...]:
        return tuple(self._nodes)

    @property
    def edges(self) -> tuple[GraphEdge, ...]:
        return tuple(self._edges)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def node_index(self, node_id: str) -> int:
        """Global row index of a node id (raises ``KeyError`` if absent)."""
        return self._index_by_id[node_id]

    def has_node(self, node_id: str) -> bool:
        return node_id in self._index_by_id

    @property
    def node_types(self) -> tuple[GnnNodeType, ...]:
        return self._require_compiled().node_types

    @property
    def relations(self) -> tuple[RelationshipType, ...]:
        return self._require_compiled().relations

    @property
    def input_dims(self) -> dict[GnnNodeType, int]:
        """Per-type feature width, as read by the input projections."""
        compiled = self._require_compiled()
        return {node_type: matrix.shape[1] for node_type, matrix in compiled.features.items()}

    def features(self, node_type: GnnNodeType) -> FloatArray:
        return self._require_compiled().features[node_type]

    def rows_for(self, node_type: GnnNodeType) -> IntArray:
        """Global indices of every node of ``node_type`` (ascending)."""
        compiled = self._require_compiled()
        return as_index_array(
            np.flatnonzero(compiled.type_ids == compiled.node_types.index(node_type))
        )

    @property
    def node_type_ids(self) -> IntArray:
        return self._require_compiled().type_ids

    @property
    def node_days(self) -> FloatArray:
        return self._require_compiled().node_days

    @property
    def reference_day(self) -> float:
        """Earliest node observation time — the temporal encoding origin."""
        return self._require_compiled().reference_day

    @property
    def message_sources(self) -> IntArray:
        return self._require_compiled().message_sources

    @property
    def message_targets(self) -> IntArray:
        return self._require_compiled().message_targets

    @property
    def message_relation_ids(self) -> IntArray:
        return self._require_compiled().message_relation_ids

    @property
    def message_days(self) -> FloatArray:
        return self._require_compiled().message_days

    @property
    def relation_groups(self) -> tuple[IntArray, ...]:
        """Edge indices (into the message arrays) per relation, aligned
        with :attr:`relations`."""
        return self._require_compiled().relation_groups

    @property
    def segment_layout(self) -> SegmentLayout:
        """Target-grouped edge layout for attention pooling."""
        return self._require_compiled().layout

    # ------------------------------------------------------------ internal

    def _require_mutable(self) -> None:
        if self._compiled is not None:
            raise RuntimeError("HeteroGraph is immutable once compiled")

    def _require_compiled(self) -> _CompiledGraph:
        if self._compiled is None:
            raise RuntimeError("HeteroGraph.compile() must run before arrays are read")
        return self._compiled


@dataclass(frozen=True)
class _CompiledGraph:
    node_types: tuple[GnnNodeType, ...]
    type_ids: IntArray
    features: dict[GnnNodeType, FloatArray]
    relations: tuple[RelationshipType, ...]
    sources: IntArray
    targets: IntArray
    relation_ids: IntArray
    edge_days: FloatArray
    message_sources: IntArray
    message_targets: IntArray
    message_relation_ids: IntArray
    message_days: FloatArray
    relation_groups: tuple[IntArray, ...]
    layout: SegmentLayout
    node_days: FloatArray
    reference_day: float


def _segment_layout(targets: IntArray) -> SegmentLayout:
    """Sort message edges by target node and record segment boundaries."""
    order = as_index_array(np.argsort(targets, kind="stable"))
    sorted_targets = targets[order]
    if sorted_targets.size:
        boundaries = as_index_array(np.flatnonzero(np.diff(sorted_targets) != 0) + 1)
        starts = as_index_array(np.concatenate([np.zeros(1, dtype=np.int64), boundaries]))
    else:  # pragma: no cover - compile() rejects edge-less graphs first
        starts = as_index_array([])
    counts = as_index_array(np.diff(np.append(starts, sorted_targets.size)))
    return SegmentLayout(order=order, starts=starts, counts=counts)
