"""Neo4j adapter for the temporal graph (Phase 08).

The in-process store is the source of truth for tests and single-node
deployments; this module issues the *equivalent Cypher* for production
Neo4j. The driver is imported lazily (optional dependency), and every
query is parameterized — ids and timestamps never enter the Cypher
text; only enum-derived vocabularies are interpolated, and only after
validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aegis.graph.schema import GraphValidationError

_MIN_TIME = datetime(1, 1, 1, tzinfo=UTC)
_MAX_TIME = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)


@dataclass(frozen=True)
class CypherQuery:
    """A parameterized Cypher statement ready for execution."""

    query: str
    parameters: Mapping[str, Any]

    @property
    def text(self) -> str:
        return self.query


def _bounds(
    at_time: datetime | None, since: datetime | None, until: datetime | None
) -> tuple[datetime, datetime]:
    """Resolve the temporal window to inclusive bounds."""
    lower = _MIN_TIME
    upper = _MAX_TIME
    if at_time is not None:
        lower = upper = at_time
    if since is not None:
        lower = since
    if until is not None:
        upper = until
    return lower, upper


class CypherBuilder:
    """Builds the six required graph queries as parameterized Cypher."""

    # --------------------------------------------- two-hop neighborhood
    @classmethod
    def two_hop_neighborhood(
        cls,
        node_id: str,
        *,
        direction: str = "both",
        at_time: datetime | None = None,
        max_hops: int = 2,
    ) -> CypherQuery:
        if direction not in {"out", "in", "both"}:
            raise GraphValidationError("direction must be out|in|both")
        hops = int(max_hops)
        if not 1 <= hops <= 10:
            raise GraphValidationError("max_hops must be within 1..10")
        if direction == "out":
            pattern = f"(center)-[*1..{hops}]->(other)"
        elif direction == "in":
            pattern = f"(center)<-[*1..{hops}]-(other)"
        else:
            pattern = f"(center)-[*1..{hops}]-(other)"

        lower, upper = _bounds(at_time, None, None)
        query = f"""
        MATCH p = {pattern}
        WHERE ALL(edge IN relationships(p)
                  WHERE edge.first_seen <= $until_bound
                    AND edge.last_seen >= $since_bound)
        WITH other, min(length(p)) AS hops
        RETURN other.id AS node_id, hops
        ORDER BY hops, node_id
        """
        return CypherQuery(
            query=query,
            parameters={
                "node_id": node_id,
                "since_bound": lower,
                "until_bound": upper,
            },
        )

    # ------------------------------------------------ common identifiers
    @classmethod
    def common_identifiers(
        cls,
        left_id: str,
        right_id: str,
        *,
        at_time: datetime | None = None,
    ) -> CypherQuery:
        lower, upper = _bounds(at_time, None, None)
        query = """
        MATCH (left {id: $left_id})-[edge1]-(shared)
        WHERE (shared:Handle OR shared:PGP OR shared:Wallet)
          AND edge1.first_seen <= $until_bound
          AND edge1.last_seen >= $since_bound
        MATCH (right {id: $right_id})-[edge2]-(shared)
        WHERE edge2.first_seen <= $until_bound
          AND edge2.last_seen >= $since_bound
        RETURN labels(shared)[0] AS identifier_label,
               shared.id AS identifier_id
        ORDER BY identifier_label, identifier_id
        """
        return CypherQuery(
            query=query,
            parameters={
                "left_id": left_id,
                "right_id": right_id,
                "since_bound": lower,
                "until_bound": upper,
            },
        )

    # ----------------------------------------- historical associations
    @classmethod
    def historical_associations(cls, node_id: str, at_time: datetime) -> CypherQuery:
        query = """
        MATCH (center {id: $node_id})-[edge]-(other)
        WHERE edge.first_seen <= $at_time AND edge.last_seen >= $at_time
        RETURN other.id AS other_id, type(edge) AS rel_type,
               edge.first_seen AS first_seen, edge.last_seen AS last_seen,
               edge.confidence AS confidence,
               edge.evidence_ids AS evidence_ids
        ORDER BY edge.first_seen, other.id
        """
        return CypherQuery(query=query, parameters={"node_id": node_id, "at_time": at_time})

    # ------------------------------------- time-filtered neighborhood
    @classmethod
    def time_filtered_neighborhood(
        cls,
        node_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        max_hops: int = 2,
    ) -> CypherQuery:
        if since is not None and until is not None and until < since:
            raise GraphValidationError("until must not precede since")
        hops = int(max_hops)
        if not 1 <= hops <= 10:
            raise GraphValidationError("max_hops must be within 1..10")
        lower, upper = _bounds(None, since, until)
        query = f"""
        MATCH p = (center {{id: $node_id}})-[*1..{hops}]-(other)
        WHERE ALL(edge IN relationships(p)
                  WHERE edge.first_seen <= $until_bound
                    AND edge.last_seen >= $since_bound)
        RETURN other.id AS node_id,
               min(length(p)) AS hops
        ORDER BY hops, node_id
        """
        return CypherQuery(
            query=query,
            parameters={
                "node_id": node_id,
                "since_bound": lower,
                "until_bound": upper,
            },
        )

    # ------------------------------------------------- evidence path
    @classmethod
    def evidence_path(cls, left_id: str, right_id: str, *, max_hops: int = 6) -> CypherQuery:
        hops = int(max_hops)
        if not 1 <= hops <= 25:
            raise GraphValidationError("max_hops must be within 1..25")
        query = f"""
        MATCH path = shortestPath(
            (left {{id: $left_id}})-[*..{hops}]-(right {{id: $right_id}})
        )
        WHERE ALL(edge IN relationships(path)
                  WHERE size(coalesce(edge.evidence_ids, [])) > 0)
        RETURN [n IN nodes(path) | n.id] AS node_ids,
               [e IN relationships(path) |
                   {{id: e.id, type: type(e), evidence_ids: e.evidence_ids}}
               ] AS edges,
               reduce(acc = [], e IN relationships(path) |
                     acc + coalesce(e.evidence_ids, [])) AS evidence_ids
        """
        return CypherQuery(query=query, parameters={"left_id": left_id, "right_id": right_id})

    # ------------------------------ candidate pair neighborhood similarity
    @classmethod
    def neighborhood_similarity(
        cls,
        left_id: str,
        right_id: str,
        *,
        at_time: datetime | None = None,
    ) -> CypherQuery:
        lower, upper = _bounds(at_time, None, None)
        query = """
        MATCH (left {id: $left_id})-[edge1]-(ln)
        WHERE edge1.first_seen <= $until_bound
          AND edge1.last_seen >= $since_bound
        WITH left, collect(DISTINCT ln) AS left_neighbors
        MATCH (right {id: $right_id})-[edge2]-(rn)
        WHERE edge2.first_seen <= $until_bound
          AND edge2.last_seen >= $since_bound
        WITH left_neighbors, collect(DISTINCT rn) AS right_neighbors
        WITH left_neighbors, right_neighbors,
             [n IN left_neighbors WHERE n IN right_neighbors] AS common,
             left_neighbors
               + [n IN right_neighbors WHERE NOT n IN left_neighbors] AS union_set
        RETURN size(common) AS shared_count,
               CASE WHEN size(union_set) = 0 THEN 0.0
                    ELSE 1.0 * size(common) / size(union_set)
               END AS jaccard,
               CASE WHEN size(left_neighbors) + size(right_neighbors) = 0
                    THEN 0.0
                    ELSE 2.0 * size(common)
                         / (size(left_neighbors) + size(right_neighbors))
               END AS dice
        """
        return CypherQuery(
            query=query,
            parameters={
                "left_id": left_id,
                "right_id": right_id,
                "since_bound": lower,
                "until_bound": upper,
            },
        )


class Neo4jGraphAdapter:
    """Executes Cypher against a Neo4j instance (lazy driver import).

    The driver is only imported when the adapter is actually used, so
    the base install and all tests stay free of the Neo4j dependency.
    """

    def __init__(
        self,
        uri: str,
        auth: tuple[str, str],
        *,
        database: str = "neo4j",
        driver: Any | None = None,
    ) -> None:
        self.uri = uri
        self.auth = auth
        self.database = database
        self._driver = driver

    @property
    def driver(self) -> Any:
        if self._driver is None:
            try:
                from neo4j import (  # type: ignore[import-not-found]  # noqa: PLC0415
                    GraphDatabase,
                )
            except ImportError as exc:
                raise GraphValidationError(
                    "neo4j driver is required for Neo4jGraphAdapter; "
                    "install aegis-intelligence[graph]"
                ) from exc
            self._driver = GraphDatabase.driver(self.uri, auth=self.auth)
        return self._driver

    def run(self, cypher: CypherQuery, **extra: Any) -> list[dict[str, Any]]:
        """Execute one parameterized query, returning plain dicts."""
        parameters = {**cypher.parameters, **extra}
        with self.driver.session(database=self.database) as session:
            result = session.run(cypher.query, parameters)
            return [dict(record) for record in result]

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
