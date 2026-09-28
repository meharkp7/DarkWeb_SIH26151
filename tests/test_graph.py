"""Phase 08 temporal graph tests: schema validation, the six required
queries (two-hop, common identifiers, historical, time-filtered,
evidence path, candidate-pair similarity), ledger import, and Cypher
generation for the Neo4j adapter.
"""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aegis.collection.corpus import SyntheticCorpusBuilder
from aegis.extraction import extractors, ner
from aegis.graph import (
    CypherBuilder,
    CypherQuery,
    GraphValidationError,
    InMemoryGraphStore,
    MissingNodeError,
    Neo4jGraphAdapter,
    NodeLabel,
    active_at,
    ensure_aware,
    label_for_entity_type,
    overlaps,
)
from aegis.ontology import ENTITY_CATEGORIES, EntityCategory, EntityType, RelationshipType
from aegis.resolution.evaluate import build_interaction_graph
from aegis.schemas.entity import Entity, Relationship
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.graph import EvidenceGraphBuilder

JAN = datetime(2026, 1, 1, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)
JUN = datetime(2026, 6, 1, tzinfo=UTC)
JUL = datetime(2026, 7, 1, tzinfo=UTC)
DEC = datetime(2026, 12, 31, tzinfo=UTC)
APR = datetime(2026, 4, 15, tzinfo=UTC)
SEP = datetime(2026, 9, 15, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)

# bounds used by CypherBuilder when no temporal filter is requested
_MIN_TIME_SENTINEL = datetime(1, 1, 1, tzinfo=UTC)
_MAX_TIME_SENTINEL = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)


def _edge(
    store: InMemoryGraphStore,
    rel: RelationshipType,
    source: str,
    target: str,
    first: datetime,
    last: datetime,
    evidence: tuple[str, ...] = (),
    confidence: float = 0.9,
) -> None:
    store.add_edge(
        rel,
        source,
        target,
        first_seen=first,
        last_seen=last,
        confidence=confidence,
        evidence_ids=evidence,
    )


def _fixture_store() -> InMemoryGraphStore:
    """a-b [Jan..Jun], b-c [Mar..Dec], a-d [Jul..Dec], c-d [Jan..Dec]."""
    store = InMemoryGraphStore()
    for node in ("a", "b", "c", "d", "x", "y", "z"):
        store.add_node(node, NodeLabel.ACTOR)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "a", "b", JAN, JUN, ("ev1",))
    _edge(store, RelationshipType.ASSOCIATED_WITH, "b", "c", MAR, DEC, ("ev2",))
    _edge(store, RelationshipType.ASSOCIATED_WITH, "a", "d", JUL, DEC, ("ev3",))
    _edge(store, RelationshipType.ASSOCIATED_WITH, "c", "d", JAN, DEC, ("ev4",))
    return store


# ----------------------------------------------------------------- schema


def test_label_mapping_and_analytical_exclusion() -> None:
    assert label_for_entity_type(EntityType.HANDLE) is NodeLabel.HANDLE
    assert label_for_entity_type(EntityType.ONION_SERVICE) is NodeLabel.INFRASTRUCTURE
    assert label_for_entity_type(EntityType.WALLET_ADDRESS) is NodeLabel.WALLET
    # analytical objects are not graph nodes
    assert label_for_entity_type(EntityType.HYPOTHESIS) is None
    assert label_for_entity_type(EntityType.STYLOMETRIC_PROFILE) is None


# ------------------------------------------------- node-label coverage
#
# The enum must cover every node the codebase actually emits. These are
# contract tests: a builder emitting a label (or entity type) the enum
# lacks would either fail type checks silently at runtime or be dropped
# by ``from_entities`` — both are regressions this section forbids.

#: The plan's Phase 08 node vocabulary — every member must exist.
PLAN_NODE_VOCABULARY = frozenset(
    {
        "Actor",
        "Handle",
        "PGP",
        "Wallet",
        "Marketplace",
        "Forum",
        "Infrastructure",
        "Post",
        "Evidence",
    }
)

#: Entity types documented as non-graph (analysis store / bookkeeping):
#: analytical objects live outside the graph by design, and source /
#: collection-job rows are ledger plumbing, not entities.
DOCUMENTED_NON_GRAPH_TYPES = frozenset(
    {
        EntityType.SOURCE,
        EntityType.COLLECTION_JOB,
        EntityType.BEHAVIORAL_PROFILE,
        EntityType.STYLOMETRIC_PROFILE,
        EntityType.HYPOTHESIS,
        EntityType.ATTRIBUTION_ASSESSMENT,
        EntityType.TIMELINE_EVENT,
        EntityType.CHANGE_POINT,
        EntityType.MIGRATION_ASSESSMENT,
    }
)


def _extracted_entity_types() -> frozenset[EntityType]:
    """Every ``EntityType`` the extraction pipeline can put on an ``Entity``."""
    found: set[EntityType] = set()
    for module in (extractors, ner):
        for candidate in vars(module).values():
            entity_types = getattr(candidate, "entity_types", None)
            if inspect.isclass(candidate) and isinstance(entity_types, frozenset):
                found |= set(entity_types)
    return frozenset(found)


def test_node_label_covers_the_plan_node_vocabulary() -> None:
    assert PLAN_NODE_VOCABULARY <= {label.value for label in NodeLabel}
    # StrEnum aliases would silently collapse distinct labels
    assert len(set(NodeLabel)) == len(list(NodeLabel))


def test_every_extracted_entity_type_has_a_node_label() -> None:
    """An extracted type missing from the enum would be silently skipped
    by ``from_entities`` — extracted entities must always become nodes."""
    extracted = _extracted_entity_types()
    assert extracted, "expected the extraction registry to expose entity types"
    assert {t.value for t in extracted if label_for_entity_type(t) is None} == set()

    # Phase 13 infrastructure extraction may emit any infrastructure type.
    infrastructure = {
        entity_type
        for entity_type, category in ENTITY_CATEGORIES.items()
        if category is EntityCategory.INFRASTRUCTURE
    }
    assert {t.value for t in infrastructure if label_for_entity_type(t) is None} == set()


def test_from_entities_skips_exactly_the_documented_non_graph_types() -> None:
    entities = [
        Entity(
            entity_id=uuid4(),
            entity_type=entity_type,
            surface_form="x",
            normalized_form="x",
            confidence=0.5,
            evidence_id=uuid4(),
        )
        for entity_type in EntityType
    ]

    store = InMemoryGraphStore.from_entities(entities, [])

    unmapped = {
        entity_type for entity_type in EntityType if label_for_entity_type(entity_type) is None
    }
    assert unmapped == set(DOCUMENTED_NON_GRAPH_TYPES)
    assert store.skipped_entities == len(DOCUMENTED_NON_GRAPH_TYPES)
    # everything that became a node carries a real enum label (not a raw string)
    assert all(isinstance(node.label, NodeLabel) for node in store.nodes.values())


def test_builders_emit_only_labels_covered_by_the_enum() -> None:
    # synthetic evidence graph (untyped string node types by design)
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, relationships = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    graph = EvidenceGraphBuilder().build(evidence, relationships)
    label_vocabulary = {label.value.casefold() for label in NodeLabel}
    assert {node.node_type.casefold() for node in graph.nodes} <= label_vocabulary

    # resolution's alias interaction graph (typed NodeLabel nodes)
    corpus = SyntheticCorpusBuilder(seed=26151, actor_count=4, post_count=40).build()
    interaction = build_interaction_graph(corpus)
    assert interaction.nodes
    assert all(isinstance(node.label, NodeLabel) for node in interaction.nodes.values())


def test_common_identifiers_cypher_labels_stay_in_sync_with_the_enum() -> None:
    """The Neo4j adapter hard-codes ``shared:Handle OR shared:PGP OR
    shared:Wallet``; drift from :class:`NodeLabel` would silently return
    nothing for a renamed label."""
    query = CypherBuilder.common_identifiers("l", "r").text
    cypher_labels = set(re.findall(r"shared:(\w+)", query))
    assert cypher_labels == {"Handle", "PGP", "Wallet"}
    for value in cypher_labels:
        assert NodeLabel(value) is not None  # unknown label raises ValueError


def test_temporal_helpers() -> None:
    assert active_at(JAN, JUN, APR)
    assert not active_at(JAN, JUN, SEP)
    assert overlaps(JAN, JUN, FEB, APR)
    assert not overlaps(JAN, JUN, JUL, DEC)
    assert overlaps(JAN, JUN, None, None)
    assert ensure_aware(JAN, field_name="x").tzinfo is not None
    with pytest.raises(GraphValidationError, match="timezone-aware"):
        ensure_aware(datetime(2026, 1, 1), field_name="naive")


def test_node_and_edge_validation() -> None:
    store = InMemoryGraphStore()
    store.add_node("n1", NodeLabel.HANDLE, entity_type=EntityType.HANDLE)

    with pytest.raises(GraphValidationError, match="belongs to label"):
        store.add_node("bad", NodeLabel.WALLET, entity_type=EntityType.HANDLE)
    with pytest.raises(GraphValidationError, match="non-empty"):
        store.add_node("", NodeLabel.HANDLE)
    with pytest.raises(MissingNodeError):
        _edge(store, RelationshipType.ASSOCIATED_WITH, "n1", "ghost", JAN, JUN)
    with pytest.raises(GraphValidationError, match="self-edges"):
        _edge(store, RelationshipType.ASSOCIATED_WITH, "n1", "n1", JAN, JUN)

    store.add_node("n2", NodeLabel.FORUM)
    with pytest.raises(GraphValidationError, match="timezone-aware"):
        store.add_edge(
            RelationshipType.ASSOCIATED_WITH,
            "n1",
            "n2",
            first_seen=datetime(2026, 1, 1),
            last_seen=JUN,
            confidence=0.5,
        )
    with pytest.raises(GraphValidationError, match="last_seen"):
        _edge(store, RelationshipType.ASSOCIATED_WITH, "n1", "n2", JUN, JAN)
    with pytest.raises(GraphValidationError, match="confidence"):
        _edge(store, RelationshipType.ASSOCIATED_WITH, "n1", "n2", JAN, JUN, confidence=1.5)


def test_ontology_category_constraints_enforced() -> None:
    store = InMemoryGraphStore()
    store.add_node("m", NodeLabel.MARKETPLACE, entity_type=EntityType.MARKETPLACE)
    store.add_node("h", NodeLabel.HANDLE, entity_type=EntityType.HANDLE)
    # USES_HANDLE only allows identity/analytical subjects
    with pytest.raises(GraphValidationError, match="not allowed"):
        _edge(store, RelationshipType.USES_HANDLE, "m", "h", JAN, JUN)


def test_duplicate_edges_merge_window_and_evidence() -> None:
    store = _fixture_store()
    before = len(store.edges)
    merged = _edge(
        store,
        RelationshipType.ASSOCIATED_WITH,
        "a",
        "b",
        FEB,
        DEC,
        ("ev9",),
        confidence=0.95,
    )
    del merged
    assert len(store.edges) == before  # merged, not duplicated
    edge = next(e for e in store.edges.values() if set(e.endpoints) == {"a", "b"})
    assert edge.first_seen == JAN  # window union keeps the earlier start
    assert edge.last_seen == DEC
    assert set(edge.evidence_ids) == {"ev1", "ev9"}
    assert edge.confidence == 0.95


def test_symmetric_edges_collapse_regardless_of_order() -> None:
    store = InMemoryGraphStore()
    store.add_node("p1", NodeLabel.POST)
    store.add_node("p2", NodeLabel.POST)
    _edge(store, RelationshipType.SIMILAR_TO, "p1", "p2", JAN, JUN, ("e1",))
    _edge(store, RelationshipType.SIMILAR_TO, "p2", "p1", JAN, JUN, ("e2",))
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert set(edge.evidence_ids) == {"e1", "e2"}


# ------------------------------------------ required query 1: two-hop


def test_two_hop_neighborhood_distances_and_dedup() -> None:
    store = _fixture_store()
    hood = store.two_hop_neighborhood("a")
    assert hood.node_ids_at(0) == ["a"]
    assert hood.node_ids_at(1) == ["b", "d"]
    assert hood.node_ids_at(2) == ["c"]
    # c reached only once even though two paths exist (a-b-c, a-d-c)
    assert len(hood.nodes) == len(hood.hops)
    assert len(hood.edges) >= 3


def test_two_hop_respects_direction() -> None:
    store = InMemoryGraphStore()
    store.add_node("s", NodeLabel.ACTOR)
    store.add_node("t", NodeLabel.ACTOR)
    # MENTIONS is a directed type; symmetric types would ignore direction.
    _edge(store, RelationshipType.MENTIONS, "s", "t", JAN, DEC)
    assert [n.node_id for n in store.two_hop_neighborhood("s", direction="out").nodes] == ["s", "t"]
    assert [n.node_id for n in store.two_hop_neighborhood("t", direction="out").nodes] == ["t"]
    assert len(store.two_hop_neighborhood("t", direction="in").nodes) == 2
    with pytest.raises(GraphValidationError, match="direction"):
        store.two_hop_neighborhood("s", direction="sideways")


def test_two_hop_time_travel() -> None:
    store = _fixture_store()
    # April: a-b and b-c active, a-d not yet
    april = store.two_hop_neighborhood("a", at_time=APR)
    assert set(april.hops) == {"a", "b", "c"}
    assert april.hops["c"] == 2
    # September: direct a-b link lapsed (Jan-Jun); b is only reachable
    # beyond two hops, while a-d-c remains active.
    september = store.two_hop_neighborhood("a", at_time=SEP)
    assert set(september.hops) == {"a", "c", "d"}
    assert september.hops["c"] == 2  # via a-d-c, not the lapsed a-b-c
    assert "b" not in september.hops


# --------------------------------- required query 2: common identifiers


def test_common_identifiers() -> None:
    store = InMemoryGraphStore()
    store.add_node("actor1", NodeLabel.ACTOR)
    store.add_node("actor2", NodeLabel.ACTOR)
    store.add_node("wallet_shared", NodeLabel.WALLET)
    store.add_node("handle_only_1", NodeLabel.HANDLE)
    store.add_node("handle_only_2", NodeLabel.HANDLE)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "actor1", "wallet_shared", JAN, DEC)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "actor2", "wallet_shared", JAN, DEC)
    _edge(store, RelationshipType.USES_HANDLE, "actor1", "handle_only_1", JAN, DEC)
    _edge(store, RelationshipType.USES_HANDLE, "actor2", "handle_only_2", JAN, DEC)

    shared = store.common_identifiers("actor1", "actor2")
    assert shared == {NodeLabel.WALLET: ["wallet_shared"]}

    # time machine: wallet link for actor2 starts in March
    store2 = InMemoryGraphStore()
    store2.add_node("actor1", NodeLabel.ACTOR)
    store2.add_node("actor2", NodeLabel.ACTOR)
    store2.add_node("wallet", NodeLabel.WALLET)
    _edge(store2, RelationshipType.ASSOCIATED_WITH, "actor1", "wallet", JAN, DEC)
    _edge(store2, RelationshipType.ASSOCIATED_WITH, "actor2", "wallet", MAR, DEC)
    assert store2.common_identifiers("actor1", "actor2", at_time=FEB) == {}
    assert store2.common_identifiers("actor1", "actor2", at_time=APR) == {
        NodeLabel.WALLET: ["wallet"]
    }


# ----------------------------- required query 3: historical associations


def test_historical_associations_time_machine() -> None:
    store = _fixture_store()
    feb = store.historical_associations("b", FEB)
    assert [n.node_id for _, _, n in feb] == ["a"]  # b-c not yet active
    may = store.historical_associations("b", APR)
    assert {n.node_id for _, _, n in may} == {"a", "c"}
    september = store.historical_associations("b", SEP)
    assert [n.node_id for _, _, n in september] == ["c"]  # a-b lapsed


# ---------------------------- required query 4: time-filtered neighborhood


def test_time_filtered_neighborhood() -> None:
    store = _fixture_store()
    spring = store.time_filtered_neighborhood("a", since=FEB, until=APR)
    assert set(spring.hops) == {"a", "b", "c"}  # a-d window (Jul+) excluded

    late = store.time_filtered_neighborhood("a", since=JUL, max_hops=2)
    # direct a-b edge ended in June, so b drops out of the two-hop window
    assert set(late.hops) == {"a", "c", "d"}
    assert "b" not in late.hops
    # allow a third hop and b reappears, routed around the lapsed edge
    wide = store.time_filtered_neighborhood("a", since=JUL, max_hops=3)
    assert wide.hops["b"] == 3  # a-d-c-b

    everything = store.time_filtered_neighborhood("a")
    assert set(everything.hops) == {"a", "b", "c", "d"}

    with pytest.raises(GraphValidationError, match="until must not precede"):
        store.time_filtered_neighborhood("a", since=DEC, until=JAN)


# --------------------------------------------- required query 5: evidence path


def test_evidence_path_shortest_and_evidence_gated() -> None:
    store = InMemoryGraphStore()
    for node in ("p", "q", "r", "s"):
        store.add_node(node, NodeLabel.ACTOR)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "p", "q", JAN, DEC, ("ev-pq",))
    _edge(store, RelationshipType.ASSOCIATED_WITH, "q", "r", JAN, DEC, ())  # no evidence
    _edge(store, RelationshipType.ASSOCIATED_WITH, "r", "s", JAN, DEC, ("ev-rs",))
    _edge(store, RelationshipType.ASSOCIATED_WITH, "p", "s", JAN, DEC, ("ev-ps",))

    # unevidenced middle edge blocks the claim when evidence is required
    assert store.evidence_path("p", "s") is not None  # direct evidenced edge wins
    assert store.evidence_path("p", "s").length == 1  # type: ignore[union-attr]

    # without the direct edge, the only route crosses an unevidenced hop
    store2 = InMemoryGraphStore()
    for node in ("p", "q", "r", "s"):
        store2.add_node(node, NodeLabel.ACTOR)
    _edge(store2, RelationshipType.ASSOCIATED_WITH, "p", "q", JAN, DEC, ("ev-pq",))
    _edge(store2, RelationshipType.ASSOCIATED_WITH, "q", "r", JAN, DEC, ())
    _edge(store2, RelationshipType.ASSOCIATED_WITH, "r", "s", JAN, DEC, ("ev-rs",))
    assert store2.evidence_path("p", "s") is None
    relaxed = store2.evidence_path("p", "s", require_evidence=False)
    assert relaxed is not None
    assert relaxed.nodes == ("p", "q", "r", "s")
    assert relaxed.evidence_ids == ("ev-pq", "ev-rs")

    with pytest.raises(MissingNodeError):
        store.evidence_path("p", "ghost")


# ------------------------ required query 6: candidate pair similarity


def test_candidate_pair_neighborhood_similarity() -> None:
    store = InMemoryGraphStore()
    for node in ("actor1", "actor2", "x", "y", "z"):
        store.add_node(node, NodeLabel.ACTOR)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "actor1", "x", JAN, DEC)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "actor1", "y", JAN, DEC)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "actor2", "x", JAN, DEC)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "actor2", "y", JAN, DEC)
    _edge(store, RelationshipType.ASSOCIATED_WITH, "actor2", "z", JAN, DEC)

    similarity = store.neighborhood_similarity("actor1", "actor2")
    assert similarity.shared_count == 2
    assert similarity.common_neighbors == frozenset({"x", "y"})
    assert similarity.jaccard == pytest.approx(2 / 3)
    assert similarity.dice == pytest.approx(0.8)

    # identical neighborhoods -> 1.0; disjoint -> 0.0
    assert store.neighborhood_similarity("actor1", "actor1").jaccard == 1.0


# ------------------------------------------------------------ ledger import


def test_from_entities_builds_graph_and_skips_analytical() -> None:
    actor_id, handle_id, hypothesis_id = uuid4(), uuid4(), uuid4()
    entities = [
        Entity(
            entity_id=actor_id,
            entity_type=EntityType.ACTOR_HYPOTHESIS,
            surface_form="ghostbroker",
            normalized_form="ghostbroker",
            confidence=0.9,
            evidence_id=uuid4(),
        ),
        Entity(
            entity_id=handle_id,
            entity_type=EntityType.HANDLE,
            surface_form="@ghostbroker",
            normalized_form="ghostbroker",
            confidence=0.95,
            evidence_id=uuid4(),
        ),
        Entity(
            entity_id=hypothesis_id,
            entity_type=EntityType.HYPOTHESIS,
            surface_form="H1",
            normalized_form="h1",
            confidence=0.5,
            evidence_id=uuid4(),
        ),
    ]
    relationships = [
        Relationship(
            subject_entity_id=actor_id,
            object_entity_id=handle_id,
            relationship_type=RelationshipType.USES_HANDLE,
            first_seen=JAN,
            last_seen=JUN,
            confidence=0.9,
            evidence_ids=(uuid4(),),
        ),
        # edge to a skipped analytical node: skipped, never mis-wired
        Relationship(
            subject_entity_id=actor_id,
            object_entity_id=hypothesis_id,
            relationship_type=RelationshipType.ASSOCIATED_WITH,
            first_seen=JAN,
            last_seen=JUN,
            confidence=0.9,
            evidence_ids=(uuid4(),),
        ),
    ]
    store = InMemoryGraphStore.from_entities(entities, relationships)
    assert store.skipped_entities == 1
    assert set(store.nodes) == {str(actor_id), str(handle_id)}
    assert len(store.edges) == 1
    # the imported edge is wired actor -> handle and answers queries
    hood = store.two_hop_neighborhood(str(actor_id))
    assert {n.node_id for n in hood.nodes} == {str(actor_id), str(handle_id)}


# ---------------------------------------------------------- Cypher builder


def test_all_six_cypher_queries_are_parameterized() -> None:
    marker = "un1que-node-1d"
    queries: list[CypherQuery] = [
        CypherBuilder.two_hop_neighborhood(marker),
        CypherBuilder.common_identifiers(marker, "other-2d"),
        CypherBuilder.historical_associations(marker, APR),
        CypherBuilder.time_filtered_neighborhood(marker, since=FEB, until=APR),
        CypherBuilder.evidence_path(marker, "other-2d"),
        CypherBuilder.neighborhood_similarity(marker, "other-2d"),
    ]
    for cypher in queries:
        assert cypher.text.strip()
        assert "WHERE" in cypher.text or "MATCH" in cypher.text
        # identifiers only ever travel as parameters
        assert marker not in cypher.text
        assert marker in cypher.parameters.values()


def test_cypher_direction_and_temporal_clauses() -> None:
    out = CypherBuilder.two_hop_neighborhood("n", direction="out")
    assert "->" in out.text and "ALL(edge IN relationships(p)" in out.text
    inn = CypherBuilder.two_hop_neighborhood("n", direction="in")
    assert "<-" in inn.text

    timed = CypherBuilder.two_hop_neighborhood("n", at_time=APR)
    assert timed.parameters["since_bound"] == APR
    assert timed.parameters["until_bound"] == APR

    historical = CypherBuilder.historical_associations("n", APR)
    assert "$at_time" in historical.text
    assert historical.parameters["at_time"] == APR

    # exactly one WHERE per MATCH segment (no double-WHERE bugs)
    common = CypherBuilder.common_identifiers("l", "r")
    assert common.text.count("WHERE") == 2

    similarity = CypherBuilder.neighborhood_similarity("l", "r")
    assert "jaccard" in similarity.text and "dice" in similarity.text

    path = CypherBuilder.evidence_path("l", "r", max_hops=5)
    assert "[*..5]" in path.text
    assert "MAX_HOPS" not in path.text


def test_cypher_builder_input_validation() -> None:
    with pytest.raises(GraphValidationError, match="direction"):
        CypherBuilder.two_hop_neighborhood("n", direction="sideways")
    with pytest.raises(GraphValidationError, match="max_hops"):
        CypherBuilder.two_hop_neighborhood("n", max_hops=99)
    with pytest.raises(GraphValidationError, match="max_hops"):
        CypherBuilder.evidence_path("a", "b", max_hops=0)
    with pytest.raises(GraphValidationError, match="until must not precede"):
        CypherBuilder.time_filtered_neighborhood("n", since=DEC, until=JAN)


def test_two_hop_binds_center_and_caps_results() -> None:
    """Regression: the two-hop query must bind ``$node_id`` on the centre
    node — an unbound centre matches every node in the graph. The result
    set is also capped so depth-bounded traversals cannot fan out without
    limit through hub nodes."""
    for direction in ("out", "in", "both"):
        query = CypherBuilder.two_hop_neighborhood("n1", direction=direction)
        assert "center {id: $node_id}" in query.text, direction
        assert "LIMIT $result_limit" in query.text
        assert query.parameters["node_id"] == "n1"
        assert query.parameters["result_limit"] == 1000


def test_adapter_runs_with_injected_driver_and_merges_parameters() -> None:
    captured: dict[str, object] = {}

    class _FakeResult:
        def __iter__(self) -> iter:  # type: ignore[type-arg]
            return iter([{"node_id": "x", "hops": 1}])

    class _FakeSession:
        def __enter__(self) -> _FakeSession:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def run(self, query: str, parameters: dict[str, object]) -> _FakeResult:
            captured["query"] = query
            captured["parameters"] = parameters
            return _FakeResult()

    class _FakeDriver:
        def session(self, *, database: str) -> _FakeSession:
            del database
            return _FakeSession()

        def close(self) -> None:
            captured["closed"] = True

    adapter = Neo4jGraphAdapter("bolt://localhost:7687", ("user", "pass"), driver=_FakeDriver())
    rows = adapter.run(CypherBuilder.two_hop_neighborhood("n1"), extra_param=1)
    assert rows == [{"node_id": "x", "hops": 1}]
    assert captured["parameters"] == {
        "node_id": "n1",
        "since_bound": _MIN_TIME_SENTINEL,
        "until_bound": _MAX_TIME_SENTINEL,
        "result_limit": 1000,
        "extra_param": 1,
    }
    adapter.close()
    assert captured["closed"] is True


def test_adapter_lazy_driver_error_without_dependency() -> None:
    adapter = Neo4jGraphAdapter("bolt://localhost:7687", ("u", "p"))
    try:
        import neo4j  # noqa: F401, S110 - probe optional dependency
    except ImportError:
        with pytest.raises(GraphValidationError, match="neo4j driver is required"):
            _ = adapter.driver
    else:  # pragma: no cover - only when optional dep present
        assert adapter.driver is not None
        adapter.close()
