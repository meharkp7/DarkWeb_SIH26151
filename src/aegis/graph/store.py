"""In-process temporal graph store (Phase 08).

Implements the plan's six required graph queries against an in-memory
store; the Neo4j adapter (:mod:`aegis.graph.neo4j`) issues the
equivalent Cypher for production deployments.

All edges are temporal (``first_seen``/``last_seen``) and
evidence-backed (``evidence_ids``); symmetric edge types are stored
canonically and traversed in both directions.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any

from aegis.graph.schema import (
    GraphValidationError,
    MissingNodeError,
    NodeLabel,
    active_at,
    ensure_aware,
    label_for_entity_type,
    overlaps,
)
from aegis.ontology import (
    RELATIONSHIP_DIRECTION,
    EntityType,
    RelationDirection,
    RelationshipType,
    category_of,
    relationship_allowed,
)

NodeKey = str


def edge_key(
    rel_type: RelationshipType, source: NodeKey, target: NodeKey, symmetric: bool
) -> str:
    """Stable identity for an edge (endpoint order folded for
    symmetric types)."""
    left, right = sorted((source, target)) if symmetric else (source, target)
    return sha256(f"{rel_type.value}|{left}|{right}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class GraphNode:
    node_id: NodeKey
    label: NodeLabel
    entity_type: EntityType | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source: NodeKey
    target: NodeKey
    rel_type: RelationshipType
    first_seen: datetime
    last_seen: datetime
    confidence: float
    evidence_ids: tuple[str, ...] = ()

    @property
    def endpoints(self) -> tuple[NodeKey, NodeKey]:
        return (self.source, self.target)


@dataclass(frozen=True)
class Neighborhood:
    center: NodeKey
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    hops: Mapping[NodeKey, int]

    def node_ids_at(self, hop: int) -> list[NodeKey]:
        return sorted(nid for nid, distance in self.hops.items() if distance == hop)


@dataclass(frozen=True)
class EvidencePath:
    """Shortest association path whose edges each carry evidence."""

    nodes: tuple[NodeKey, ...]
    edges: tuple[GraphEdge, ...]
    evidence_ids: tuple[str, ...]

    @property
    def length(self) -> int:
        return len(self.edges)


@dataclass(frozen=True)
class NeighborhoodSimilarity:
    left: NodeKey
    right: NodeKey
    common_neighbors: frozenset[NodeKey]
    jaccard: float
    dice: float

    @property
    def shared_count(self) -> int:
        return len(self.common_neighbors)


class InMemoryGraphStore:
    """Directed + symmetric temporal multigraph with evidence edges."""

    #: entities skipped by :meth:`from_entities` (no graph label)
    skipped_entities: int = 0

    def __init__(self) -> None:
        self._nodes: dict[NodeKey, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        # adjacency: node -> edge ids (out = as-subject for directed)
        self._out: dict[NodeKey, set[str]] = defaultdict(set)
        self._in: dict[NodeKey, set[str]] = defaultdict(set)
        self._undirected: dict[NodeKey, set[str]] = defaultdict(set)

    # ------------------------------------------------------------ schema

    @staticmethod
    def _direction(rel_type: RelationshipType) -> RelationDirection:
        return RELATIONSHIP_DIRECTION[rel_type]

    def add_node(
        self,
        node_id: NodeKey,
        label: NodeLabel,
        *,
        entity_type: EntityType | None = None,
        properties: dict[str, Any] | None = None,
    ) -> GraphNode:
        if not node_id:
            raise GraphValidationError("node_id must be non-empty")
        if entity_type is not None:
            expected = label_for_entity_type(entity_type)
            if expected is not None and expected is not label:
                raise GraphValidationError(
                    f"entity type {entity_type.value} belongs to label "
                    f"{expected.value}, not {label.value}"
                )
        node = GraphNode(
            node_id=node_id,
            label=label,
            entity_type=entity_type,
            properties=dict(properties or {}),
        )
        self._nodes[node_id] = node
        return node

    def get_node(self, node_id: NodeKey) -> GraphNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise MissingNodeError(f"unknown node {node_id!r}") from exc

    def has_node(self, node_id: NodeKey) -> bool:
        return node_id in self._nodes

    @property
    def nodes(self) -> dict[NodeKey, GraphNode]:
        return dict(self._nodes)

    @property
    def edges(self) -> dict[str, GraphEdge]:
        return dict(self._edges)

    def add_edge(
        self,
        rel_type: RelationshipType,
        source: NodeKey,
        target: NodeKey,
        *,
        first_seen: datetime,
        last_seen: datetime,
        confidence: float,
        evidence_ids: Sequence[str] = (),
    ) -> GraphEdge:
        if source not in self._nodes:
            raise MissingNodeError(f"unknown subject node {source!r}")
        if target not in self._nodes:
            raise MissingNodeError(f"unknown object node {target!r}")
        if source == target:
            raise GraphValidationError("self-edges are not allowed")

        first = ensure_aware(first_seen, field_name="first_seen")
        last = ensure_aware(last_seen, field_name="last_seen")
        if last < first:
            raise GraphValidationError("last_seen must not precede first_seen")
        if not 0.0 <= confidence <= 1.0:
            raise GraphValidationError("confidence must be within [0, 1]")

        # ontology category compatibility (default-deny where declared)
        subject_type = self._nodes[source].entity_type
        object_type = self._nodes[target].entity_type
        if subject_type is not None and object_type is not None:
            if not relationship_allowed(
                rel_type, category_of(subject_type), category_of(object_type)
            ):
                raise GraphValidationError(
                    f"edge {rel_type.value} not allowed between "
                    f"{subject_type.value} and {object_type.value}"
                )

        symmetric = self._direction(rel_type) is RelationDirection.SYMMETRIC
        key = edge_key(rel_type, source, target, symmetric)
        canonical_source, canonical_target = (
            sorted((source, target)) if symmetric else (source, target)
        )

        existing = self._edges.get(key)
        if existing is not None:
            # merge: window union, max confidence, evidence union
            merged = GraphEdge(
                edge_id=key,
                source=existing.source,
                target=existing.target,
                rel_type=rel_type,
                first_seen=min(existing.first_seen, first),
                last_seen=max(existing.last_seen, last),
                confidence=max(existing.confidence, confidence),
                evidence_ids=tuple(
                    dict.fromkeys((*existing.evidence_ids, *evidence_ids))
                ),
            )
            self._edges[key] = merged
            return merged

        edge = GraphEdge(
            edge_id=key,
            source=canonical_source,
            target=canonical_target,
            rel_type=rel_type,
            first_seen=first,
            last_seen=last,
            confidence=confidence,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        )
        self._edges[key] = edge
        if symmetric:
            self._undirected[source].add(key)
            self._undirected[target].add(key)
        else:
            self._out[source].add(key)
            self._in[target].add(key)
        return edge

    # ------------------------------------------------------- traversal

    def _incident(self, node_id: NodeKey, *, direction: str) -> list[GraphEdge]:
        edge_ids: set[str] = set()
        if direction in ("out", "both"):
            edge_ids |= self._out[node_id]
        if direction in ("in", "both"):
            edge_ids |= self._in[node_id]
        # symmetric edges have no direction; they are always incident
        edge_ids |= self._undirected[node_id]
        return [self._edges[eid] for eid in edge_ids]

    @staticmethod
    def _other_end(edge: GraphEdge, node_id: NodeKey) -> NodeKey:
        return edge.target if edge.source == node_id else edge.source

    def _neighbor(
        self,
        node_id: NodeKey,
        edge: GraphEdge,
        *,
        direction: str,
    ) -> NodeKey | None:
        symmetric = edge.rel_type in _SYMMETRIC_TYPES
        if symmetric:
            return self._other_end(edge, node_id)
        if direction in ("out", "both") and edge.source == node_id:
            return edge.target
        if direction in ("in", "both") and edge.target == node_id:
            return edge.source
        return None

    # --------------------------------------------- required query 1:
    #                                     two-hop neighborhood
    def two_hop_neighborhood(
        self,
        node_id: NodeKey,
        *,
        direction: str = "both",
        at_time: datetime | None = None,
        max_hops: int = 2,
    ) -> Neighborhood:
        self.get_node(node_id)
        if direction not in {"out", "in", "both"}:
            raise GraphValidationError("direction must be out|in|both")
        if at_time is not None:
            at_time = ensure_aware(at_time, field_name="at_time")

        hops: dict[NodeKey, int] = {node_id: 0}
        used_edges: dict[str, GraphEdge] = {}
        frontier: deque[NodeKey] = deque([node_id])

        while frontier:
            current = frontier.popleft()
            if hops[current] >= max_hops:
                continue
            for edge in self._incident(current, direction=direction):
                if at_time is not None and not active_at(
                    edge.first_seen, edge.last_seen, at_time
                ):
                    continue
                neighbor = self._neighbor(current, edge, direction=direction)
                if neighbor is None:
                    continue
                used_edges[edge.edge_id] = edge
                if neighbor not in hops:
                    hops[neighbor] = hops[current] + 1
                    frontier.append(neighbor)

        ordered = sorted(hops, key=lambda nid: (hops[nid], nid))
        return Neighborhood(
            center=node_id,
            nodes=tuple(self._nodes[nid] for nid in ordered),
            edges=tuple(sorted(used_edges.values(), key=lambda e: e.edge_id)),
            hops=dict(hops),
        )

    # --------------------------------------------- required query 2:
    #                                     common identifiers
    def common_identifiers(
        self, left: NodeKey, right: NodeKey, *, at_time: datetime | None = None
    ) -> dict[NodeLabel, list[NodeKey]]:
        """Identifier nodes (Handle/PGP/Wallet) both sides connect to."""
        identifier_labels = {NodeLabel.HANDLE, NodeLabel.PGP, NodeLabel.WALLET}
        left_ids = self._identifier_neighbors(left, at_time=at_time)
        right_ids = self._identifier_neighbors(right, at_time=at_time)
        shared = left_ids & right_ids

        grouped: dict[NodeLabel, list[NodeKey]] = {}
        for node_id in sorted(shared):
            label = self._nodes[node_id].label
            if label in identifier_labels:
                grouped.setdefault(label, []).append(node_id)
        return grouped

    def _identifier_neighbors(
        self, node_id: NodeKey, *, at_time: datetime | None
    ) -> set[NodeKey]:
        self.get_node(node_id)
        found: set[NodeKey] = set()
        for edge in self._incident(node_id, direction="both"):
            if at_time is not None and not active_at(
                edge.first_seen, edge.last_seen, at_time
            ):
                continue
            neighbor = self._other_end(edge, node_id)
            if neighbor != node_id:
                found.add(neighbor)
        return found

    # --------------------------------------------- required query 3:
    #                                     historical associations
    def historical_associations(
        self, node_id: NodeKey, at_time: datetime
    ) -> list[tuple[GraphNode, GraphEdge, GraphNode]]:
        """Edges that were active at a past instant (time-machine view)."""
        moment = ensure_aware(at_time, field_name="at_time")
        self.get_node(node_id)
        results: list[tuple[GraphNode, GraphEdge, GraphNode]] = []
        for edge in self._incident(node_id, direction="both"):
            if not active_at(edge.first_seen, edge.last_seen, moment):
                continue
            other = self._other_end(edge, node_id)
            results.append((self._nodes[node_id], edge, self._nodes[other]))
        results.sort(key=lambda item: (item[1].edge_id))
        return results

    # --------------------------------------------- required query 4:
    #                                     time-filtered neighborhood
    def time_filtered_neighborhood(
        self,
        node_id: NodeKey,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        max_hops: int = 2,
        direction: str = "both",
    ) -> Neighborhood:
        self.get_node(node_id)
        lower = ensure_aware(since, field_name="since") if since else None
        upper = ensure_aware(until, field_name="until") if until else None
        if lower is not None and upper is not None and upper < lower:
            raise GraphValidationError("until must not precede since")

        hops: dict[NodeKey, int] = {node_id: 0}
        used_edges: dict[str, GraphEdge] = {}
        frontier: deque[NodeKey] = deque([node_id])

        while frontier:
            current = frontier.popleft()
            if hops[current] >= max_hops:
                continue
            for edge in self._incident(current, direction=direction):
                if not overlaps(edge.first_seen, edge.last_seen, lower, upper):
                    continue
                neighbor = self._neighbor(current, edge, direction=direction)
                if neighbor is None:
                    continue
                used_edges[edge.edge_id] = edge
                if neighbor not in hops:
                    hops[neighbor] = hops[current] + 1
                    frontier.append(neighbor)

        ordered = sorted(hops, key=lambda nid: (hops[nid], nid))
        return Neighborhood(
            center=node_id,
            nodes=tuple(self._nodes[nid] for nid in ordered),
            edges=tuple(sorted(used_edges.values(), key=lambda e: e.edge_id)),
            hops=dict(hops),
        )

    # --------------------------------------------- required query 5:
    #                                     evidence path
    def evidence_path(
        self,
        left: NodeKey,
        right: NodeKey,
        *,
        max_hops: int = 6,
        require_evidence: bool = True,
    ) -> EvidencePath | None:
        """Shortest association path; edges without evidence are
        skipped when *require_evidence* (an unevidenced chain cannot
        support an attribution claim)."""
        self.get_node(left)
        self.get_node(right)
        if left == right:
            return EvidencePath(nodes=(left,), edges=(), evidence_ids=())

        predecessor: dict[NodeKey, tuple[NodeKey, GraphEdge]] = {}
        visited: set[NodeKey] = {left}
        frontier: deque[NodeKey] = deque([left])

        while frontier and len(visited) < len(self._nodes) + 1:
            current = frontier.popleft()
            if current == right:
                break
            depth = self._depth_of(predecessor, left, current)
            if depth >= max_hops:
                continue
            for edge in self._incident(current, direction="both"):
                if require_evidence and not edge.evidence_ids:
                    continue
                neighbor = self._other_end(edge, current)
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                predecessor[neighbor] = (current, edge)
                if neighbor == right:
                    frontier.clear()
                    break
                frontier.append(neighbor)

        if right not in predecessor:
            return None

        nodes: list[NodeKey] = [right]
        edges: list[GraphEdge] = []
        cursor = right
        while cursor != left:
            previous, edge = predecessor[cursor]
            edges.append(edge)
            nodes.append(previous)
            cursor = previous
        nodes.reverse()
        edges.reverse()
        evidence = tuple(
            dict.fromkeys(eid for edge in edges for eid in edge.evidence_ids)
        )
        return EvidencePath(
            nodes=tuple(nodes), edges=tuple(edges), evidence_ids=evidence
        )

    @staticmethod
    def _depth_of(
        predecessor: dict[NodeKey, tuple[NodeKey, GraphEdge]],
        origin: NodeKey,
        node_id: NodeKey,
    ) -> int:
        depth = 0
        cursor = node_id
        while cursor != origin:
            cursor = predecessor[cursor][0]
            depth += 1
            if depth > 10_000:  # cycle guard (should be unreachable)
                break
        return depth

    # --------------------------------------------- required query 6:
    #                       candidate pair neighborhood similarity
    def neighborhood_similarity(
        self, left: NodeKey, right: NodeKey, *, at_time: datetime | None = None
    ) -> NeighborhoodSimilarity:
        """Jaccard/Dice similarity of 1-hop neighbor sets — the
        candidate-pair feature reused by attribution scoring."""
        left_neighbors = self._open_neighborhood(left, at_time=at_time)
        right_neighbors = self._open_neighborhood(right, at_time=at_time)
        left_neighbors.discard(right)
        right_neighbors.discard(left)

        common = left_neighbors & right_neighbors
        union = left_neighbors | right_neighbors
        jaccard = len(common) / len(union) if union else 0.0
        total = len(left_neighbors) + len(right_neighbors)
        dice = (2 * len(common) / total) if total else 0.0
        return NeighborhoodSimilarity(
            left=left,
            right=right,
            common_neighbors=frozenset(common),
            jaccard=jaccard,
            dice=dice,
        )

    def _open_neighborhood(
        self, node_id: NodeKey, *, at_time: datetime | None
    ) -> set[NodeKey]:
        self.get_node(node_id)
        moment = ensure_aware(at_time, field_name="at_time") if at_time else None
        neighbors: set[NodeKey] = set()
        for edge in self._incident(node_id, direction="both"):
            if moment is not None and not active_at(
                edge.first_seen, edge.last_seen, moment
            ):
                continue
            neighbors.add(self._other_end(edge, node_id))
        return neighbors

    # ------------------------------------------------------- bulk import

    @classmethod
    def from_entities(
        cls,
        entities: Iterable[Any],
        relationships: Iterable[Any],
    ) -> InMemoryGraphStore:
        """Build from canonical ``Entity``/``Relationship`` schemas.

        Entities whose type has no graph label are skipped (they live
        in the analysis store); edges referencing skipped endpoints are
        skipped too, never silently mis-wired.
        """
        store = cls()
        skipped_entities = 0
        for entity in entities:
            label = label_for_entity_type(entity.entity_type)
            if label is None:
                skipped_entities += 1
                continue
            store.add_node(
                str(entity.entity_id),
                label,
                entity_type=entity.entity_type,
                properties={"surface_form": entity.surface_form,
                            "normalized_form": entity.normalized_form,
                            "confidence": entity.confidence},
            )

        for relationship in relationships:
            source = str(relationship.subject_entity_id)
            target = str(relationship.object_entity_id)
            if not store.has_node(source) or not store.has_node(target):
                continue
            store.add_edge(
                relationship.relationship_type,
                source,
                target,
                first_seen=relationship.first_seen,
                last_seen=relationship.last_seen,
                confidence=relationship.confidence,
                evidence_ids=[str(eid) for eid in relationship.evidence_ids],
            )
        store.skipped_entities = skipped_entities
        return store


_SYMMETRIC_TYPES: frozenset[RelationshipType] = frozenset(
    rel
    for rel, direction in RELATIONSHIP_DIRECTION.items()
    if direction is RelationDirection.SYMMETRIC
)
