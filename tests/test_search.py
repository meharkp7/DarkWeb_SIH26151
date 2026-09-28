"""Phase 10 search and retrieval tests.

Covers the five plan indexes, all six required features (exact search,
phrase search, time filtering, source filtering, entity filtering,
hybrid retrieval), hit provenance (matched fields/terms + score
breakdown), the in-process/OpenSearch DSL equivalence, the lazy
optional-dependency behaviour of the adapter, and the explicit p95
latency target (``P95_LATENCY_TARGET_MS``) on a 400-document corpus.
"""

from __future__ import annotations

import builtins
import inspect
import math
import random
import sys
from datetime import UTC, datetime, timedelta
from time import perf_counter

import pytest

from aegis.ontology import EntityType
from aegis.schemas import Entity, Evidence, Observation
from aegis.search import (
    P95_LATENCY_TARGET_MS,
    IndexedDocument,
    IndexName,
    InProcessSearchEngine,
    InvalidDocumentError,
    InvalidQueryError,
    MatchMode,
    OpenSearchAdapter,
    RetrievalMode,
    ScoreBreakdown,
    SearchEngine,
    SearchError,
    SearchQuery,
    build_search_body,
    character_ngrams,
    document_body,
    index_name,
    parse_search_response,
    query_tokens,
    tokenize,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
SINCE = datetime(2026, 3, 1, tzinfo=UTC)
UNTIL = datetime(2026, 9, 1, tzinfo=UTC)


def _text(
    doc_id: str,
    body: str,
    *,
    index: IndexName = IndexName.POSTS,
    title: str | None = None,
    timestamp: datetime | None = NOW,
    source: str | None = None,
    entity_ids: tuple[str, ...] = (),
    payload: object | None = None,
) -> IndexedDocument:
    return IndexedDocument.from_text(
        index,
        doc_id=doc_id,
        body=body,
        title=title,
        timestamp=timestamp,
        source=source,
        entity_ids=entity_ids,
        payload=payload,
    )


def _evidence(**updates: object) -> Evidence:
    return Evidence.example().model_copy(update=updates)


def _query(**kwargs: object) -> SearchQuery:
    """SearchQuery defaulting to the test corpus's index (POSTS)."""
    kwargs.setdefault("index", IndexName.POSTS)
    return SearchQuery(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def engine() -> InProcessSearchEngine:
    return InProcessSearchEngine()


# ------------------------------------------------------------------ types


def test_plan_indexes_are_the_five_required() -> None:
    assert [index.value for index in IndexName] == [
        "evidence",
        "posts",
        "documents",
        "entities",
        "reports",
    ]


def test_tokenize_casefolds_and_splits() -> None:
    assert tokenize("GhostBroker's Escrow — DEAL!") == ["ghostbroker", "s", "escrow", "deal"]


def test_character_ngrams_pad_word_boundaries() -> None:
    grams = character_ngrams("ab")
    # "ab" pads to "##ab##": boundary-aware 3-grams survive.
    assert "##a" in grams
    assert "ab#" in grams
    assert grams == character_ngrams("AB")


def test_from_evidence_carries_canonical_payload_and_anchors() -> None:
    evidence = Evidence.example()
    document = IndexedDocument.from_evidence(evidence, entity_ids={"entity-9"})

    assert document.index is IndexName.EVIDENCE
    assert document.doc_id == str(evidence.evidence_id)
    assert document.payload is evidence
    assert document.timestamp == evidence.collected_at  # observed_at is None here
    assert document.source == str(evidence.source_id)
    assert document.entity_ids == frozenset({"entity-9"})
    assert document.fields["sha256"] == evidence.sha256
    assert document.fields["source_type"] == "synthetic"


def test_from_evidence_timestamp_prefers_observed_at() -> None:
    observed = datetime(2026, 5, 5, 8, 30, tzinfo=UTC)
    document = IndexedDocument.from_evidence(_evidence(observed_at=observed))
    assert document.timestamp == observed


def test_from_observation_lives_in_evidence_index() -> None:
    observation = Observation.example()
    document = IndexedDocument.from_observation(observation)

    assert document.index is IndexName.EVIDENCE
    assert document.payload is observation
    assert document.doc_id == str(observation.observation_id)
    assert document.timestamp == observation.collected_at
    assert document.source == observation.independence_group
    assert document.fields["duplicate_cluster"] == observation.duplicate_cluster_id


def test_from_entity_links_its_own_id() -> None:
    entity = Entity.example()
    document = IndexedDocument.from_entity(entity)

    assert document.index is IndexName.ENTITIES
    assert document.payload is entity
    assert document.doc_id == str(entity.entity_id)
    assert document.entity_ids == frozenset({str(entity.entity_id)})
    assert document.fields["entity_type"] == EntityType.HANDLE.value
    assert document.fields["normalized_form"] == "ghostbroker"


def test_from_text_builds_body_title_and_extras() -> None:
    document = IndexedDocument.from_text(
        IndexName.REPORTS,
        doc_id="rep-1",
        body="stealer log sale",
        title="Weekly report",
        timestamp=NOW,
        source="analyst-1",
        entity_ids={"ent-1"},
        extra_fields={"classification": "malware"},
    )
    assert document.fields == {
        "body": "stealer log sale",
        "title": "Weekly report",
        "classification": "malware",
    }
    assert document.source == "analyst-1"


def test_document_rejects_naive_timestamp() -> None:
    with pytest.raises(InvalidDocumentError, match="timezone-aware"):
        _text("naive", "body", timestamp=datetime(2026, 1, 1))


def test_document_rejects_empty_doc_id() -> None:
    with pytest.raises(InvalidDocumentError, match="doc_id"):
        IndexedDocument.from_text(IndexName.POSTS, doc_id="  ", body="text")


def test_document_rejects_unknown_index() -> None:
    with pytest.raises(InvalidDocumentError, match="IndexName"):
        IndexedDocument(index="nope", doc_id="d", fields={"body": "text"})  # type: ignore[arg-type]


def test_query_rejects_inverted_window() -> None:
    with pytest.raises(InvalidQueryError, match="until must not precede since"):
        SearchQuery(since=UNTIL, until=SINCE)


def test_query_rejects_unaware_bounds() -> None:
    with pytest.raises(InvalidQueryError, match="timezone-aware"):
        SearchQuery(since=datetime(2026, 1, 1))


def test_query_rejects_bad_limit() -> None:
    with pytest.raises(InvalidQueryError, match="limit"):
        SearchQuery(limit=0)
    with pytest.raises(InvalidQueryError, match="limit"):
        SearchQuery(limit=10_000)


def test_query_rejects_unknown_index() -> None:
    with pytest.raises(InvalidQueryError, match="IndexName"):
        SearchQuery(index="nope")  # type: ignore[arg-type]
    assert SearchQuery(index="posts").index is IndexName.POSTS  # str input coerces


def test_query_rejects_bare_string_sources() -> None:
    with pytest.raises(InvalidQueryError, match="sources"):
        SearchQuery(sources="source-1")  # type: ignore[arg-type]


def test_query_tokens_blank_and_tokenless() -> None:
    assert query_tokens(SearchQuery(text="   ")) == []
    assert query_tokens(SearchQuery(text="")) == []
    with pytest.raises(InvalidQueryError, match="no searchable tokens"):
        query_tokens(SearchQuery(text="!!! ---"))


def test_engine_satisfies_search_protocol() -> None:
    assert isinstance(InProcessSearchEngine(), SearchEngine)
    assert isinstance(OpenSearchAdapter(client=object()), SearchEngine)


# ----------------------------------------------- canonical payload guards


def test_engine_rejects_evidence_payload_in_wrong_index() -> None:
    document = IndexedDocument(
        index=IndexName.POSTS, doc_id="d1", fields={"body": "text"}, payload=Evidence.example()
    )
    with pytest.raises(InvalidDocumentError, match="evidence"):
        InProcessSearchEngine().index(document)


def test_engine_rejects_entity_payload_outside_entities_index() -> None:
    document = IndexedDocument(
        index=IndexName.DOCUMENTS,
        doc_id="d1",
        fields={"body": "text"},
        payload=Entity.example(),
    )
    with pytest.raises(InvalidDocumentError, match="entities"):
        InProcessSearchEngine().index(document)


# ------------------------------------------------------------ exact search


def test_exact_search_matches_whole_tokens_only(engine: InProcessSearchEngine) -> None:
    engine.index(_text("a", "the ghostbroker vanished"))
    engine.index(_text("b", "a ghost in the shell"))

    prefix = engine.search(_query(text="ghostbroker", match_mode=MatchMode.EXACT))
    assert [hit.doc_id for hit in prefix.hits] == ["a"]

    cased = engine.search(_query(text="GhoSTBroKer", match_mode=MatchMode.EXACT))
    assert [hit.doc_id for hit in cased.hits] == ["a"]

    shorter = engine.search(_query(text="ghost", match_mode=MatchMode.EXACT))
    assert [hit.doc_id for hit in shorter.hits] == ["b"]


def test_exact_search_requires_every_token(engine: InProcessSearchEngine) -> None:
    engine.index(_text("both", "alpha beta gamma"))
    engine.index(_text("one", "alpha only"))
    engine.index(_text("none", "gamma delta"))

    result = engine.search(_query(text="alpha beta", match_mode=MatchMode.EXACT))
    assert [hit.doc_id for hit in result.hits] == ["both"]
    assert result.total == 1


def test_exact_search_whole_field_bonus_wins(engine: InProcessSearchEngine) -> None:
    # Without the whole-field bonus the far shorter document ranks first
    # (BM25 length normalization); the bonus must flip that ordering.
    filler = "cache ledger paste mirror " * 25
    engine.index(_text("field-equals", filler, title="ghostbroker"))
    engine.index(_text("short-contains", "ghostbroker cache ledger paste mirror", title="note"))

    result = engine.search(_query(text="ghostbroker", match_mode=MatchMode.EXACT))
    assert [hit.doc_id for hit in result.hits] == ["field-equals", "short-contains"]


# ----------------------------------------------------------- phrase search


def test_phrase_search_requires_contiguous_order(engine: InProcessSearchEngine) -> None:
    engine.index(_text("ok", "alpha beta gamma"))
    engine.index(_text("reversed", "gamma beta alpha"))

    result = engine.search(_query(text="alpha beta", match_mode=MatchMode.PHRASE))
    assert [hit.doc_id for hit in result.hits] == ["ok"]
    assert result.hits[0].matched_fields == ("body",)


def test_phrase_search_rejects_gapped_and_reordered(engine: InProcessSearchEngine) -> None:
    engine.index(_text("gapped", "alpha delta beta"))
    engine.index(_text("reordered", "beta alpha"))

    result = engine.search(_query(text="alpha beta", match_mode=MatchMode.PHRASE))
    assert result.hits == ()
    assert result.total == 0


def test_phrase_search_does_not_cross_field_boundaries(engine: InProcessSearchEngine) -> None:
    engine.index(_text("split", "beta gamma", title="alpha"))
    engine.index(_text("same-field", "gamma", title="alpha beta"))

    result = engine.search(_query(text="alpha beta", match_mode=MatchMode.PHRASE))
    assert [hit.doc_id for hit in result.hits] == ["same-field"]
    assert result.hits[0].matched_fields == ("title",)


# ------------------------------------------------------ BM25 / provenance


def test_terms_search_uses_bm25_rarity_ranking(engine: InProcessSearchEngine) -> None:
    for index in range(5):
        engine.index(_text(f"common-{index}", "common word filler"))
    engine.index(_text("rare", "rare word filler"))
    engine.index(_text("noise", "unrelated filler text"))

    result = engine.search(_query(text="common rare"))
    assert result.total == 6  # OR semantics; the noise document stays out
    assert result.hits[0].doc_id == "rare"  # rarer term outranks the common ones
    assert all(hit.doc_id != "noise" for hit in result.hits)


def test_search_reports_match_provenance(engine: InProcessSearchEngine) -> None:
    engine.index(_text("doc-1", "ransomware leak posted", title="leak report", source="forum-1"))
    result = engine.search(_query(text="ransomware leak", index=IndexName.POSTS))

    hit = result.hits[0]
    assert set(hit.matched_fields) == {"body", "title"}
    assert hit.matched_terms == ("ransomware", "leak")
    assert hit.breakdown.lexical > 0.0
    assert hit.breakdown.semantic == 0.0
    assert hit.score == hit.breakdown.final


def test_lexical_breakdown_final_equals_lexical(engine: InProcessSearchEngine) -> None:
    engine.index(_text("a", "escrow payment released"))
    hit = engine.search(_query(text="escrow")).hits[0]
    assert hit.breakdown.final == hit.breakdown.lexical
    assert hit.breakdown.semantic == 0.0


def test_filter_only_query_scores_zero(engine: InProcessSearchEngine) -> None:
    engine.index(_text("c", "gamma"))
    engine.index(_text("a", "alpha"))
    engine.index(_text("b", "beta"))

    result = engine.search(_query(sources=("missing",)))
    assert result.hits == ()
    assert result.total == 0

    browse = engine.search(_query())
    assert [hit.doc_id for hit in browse.hits] == ["a", "b", "c"]
    assert all(hit.score == 0.0 for hit in browse.hits)
    assert all(hit.breakdown == ScoreBreakdown(0.0, 0.0, 0.0) for hit in browse.hits)
    assert all(hit.matched_fields == () for hit in browse.hits)


# ------------------------------------------------------------- filters


def test_time_filter_is_inclusive_and_excludes_missing(engine: InProcessSearchEngine) -> None:
    engine.index(_text("at-since", "entry", timestamp=SINCE))
    engine.index(_text("mid", "entry", timestamp=datetime(2026, 6, 15, tzinfo=UTC)))
    engine.index(_text("at-until", "entry", timestamp=UNTIL))
    engine.index(_text("too-late", "entry", timestamp=datetime(2026, 10, 1, tzinfo=UTC)))
    engine.index(_text("too-early", "entry", timestamp=datetime(2026, 1, 1, tzinfo=UTC)))
    engine.index(_text("no-stamp", "entry", timestamp=None))

    result = engine.search(_query(since=SINCE, until=UNTIL))
    assert sorted(hit.doc_id for hit in result.hits) == ["at-since", "at-until", "mid"]


def test_source_filter(engine: InProcessSearchEngine) -> None:
    engine.index(_text("alpha", "entry", source="market-alpha"))
    engine.index(_text("beta", "entry", source="market-beta"))
    engine.index(_text("none", "entry"))

    one = engine.search(_query(sources=("market-alpha",)))
    assert [hit.doc_id for hit in one.hits] == ["alpha"]

    both = engine.search(_query(sources=("market-alpha", "market-beta")))
    assert sorted(hit.doc_id for hit in both.hits) == ["alpha", "beta"]


def test_entity_filter(engine: InProcessSearchEngine) -> None:
    engine.index(IndexedDocument.from_evidence(Evidence.example(), entity_ids={"entity-1"}))
    engine.index(IndexedDocument.from_evidence(Evidence.example(), entity_ids={"entity-2"}))
    engine.index(IndexedDocument.from_evidence(Evidence.example()))

    linked = engine.search(_query(index=IndexName.EVIDENCE, entity_ids=("entity-1",)))
    assert linked.total == 1

    entity = Entity.example()
    engine.index(IndexedDocument.from_entity(entity))
    on_entities = engine.search(
        SearchQuery(index=IndexName.ENTITIES, entity_ids=(str(entity.entity_id),))
    )
    assert [hit.doc_id for hit in on_entities.hits] == [str(entity.entity_id)]


# ------------------------------------------------------- ranking / limits


def test_limit_and_total(engine: InProcessSearchEngine) -> None:
    for index in range(5):
        engine.index(_text(f"doc-{index}", "shared content here"))

    result = engine.search(_query(text="shared content", limit=2))
    assert len(result.hits) == 2
    assert result.total == 5
    assert result.query.limit == 2
    assert result.took_ms >= 0.0


def test_ties_break_deterministically_by_doc_id(engine: InProcessSearchEngine) -> None:
    engine.index(_text("doc-z", "identical body text"))
    engine.index(_text("doc-a", "identical body text"))

    result = engine.search(_query(text="identical body"))
    assert [hit.doc_id for hit in result.hits] == ["doc-a", "doc-z"]


# ---------------------------------------------------------- hybrid retrieval


def test_hybrid_retrieves_lexically_disjoint_document(engine: InProcessSearchEngine) -> None:
    engine.index(_text("semantic", "phishers reuse credentials"))
    engine.index(_text("unrelated", "bitcoin escrow release"))

    lexical = engine.search(_query(text="phishing"))
    assert lexical.hits == ()

    hybrid = engine.search(_query(text="phishing", retrieval_mode=RetrievalMode.HYBRID))
    assert [hit.doc_id for hit in hybrid.hits] == ["semantic"]
    hit = hybrid.hits[0]
    assert hit.breakdown.lexical == 0.0  # no exact token overlap ...
    assert hit.breakdown.semantic > 0.0  # ... but the n-gram signal matched
    assert hit.breakdown.final == pytest.approx(0.3 * hit.breakdown.semantic)
    assert hit.matched_terms == ()


def test_hybrid_score_is_weighted_combination(engine: InProcessSearchEngine) -> None:
    engine.index(_text("a", "phishing kits sold"))
    result = engine.search(_query(text="phishing", retrieval_mode=RetrievalMode.HYBRID))
    hit = result.hits[0]
    assert hit.breakdown.lexical > 0.0
    assert 0.0 < hit.breakdown.semantic <= 1.0
    # Single candidate: normalized lexical is 1.0, weights default to 0.7/0.3.
    assert hit.breakdown.final == pytest.approx(0.7 * 1.0 + 0.3 * hit.breakdown.semantic)
    assert hit.score == hit.breakdown.final


def test_exact_hybrid_stays_strict(engine: InProcessSearchEngine) -> None:
    engine.index(_text("both", "alpha beta"))
    engine.index(_text("one", "alpha"))

    strict = engine.search(
        _query(text="alpha beta", match_mode=MatchMode.EXACT, retrieval_mode=RetrievalMode.HYBRID)
    )
    assert [hit.doc_id for hit in strict.hits] == ["both"]

    # The same corpus in default TERMS mode still allows partial matches.
    relaxed = engine.search(_query(text="alpha beta"))
    assert sorted(hit.doc_id for hit in relaxed.hits) == ["both", "one"]


# -------------------------------------------------------------- config


def test_field_weights_boost_title_matches() -> None:
    weighted = InProcessSearchEngine(field_weights={"title": 10.0})
    weighted.index(_text("title-hit", "cache ledger paste mirror", title="cache"))
    weighted.index(_text("body-hit", "cache ledger paste mirror", title="note"))

    result = weighted.search(_query(text="cache"))
    # Both documents match; the weighted title hit must outrank the body hit.
    assert [hit.doc_id for hit in result.hits] == ["title-hit", "body-hit"]


def test_invalid_field_weights_rejected() -> None:
    with pytest.raises(SearchError, match="field weight"):
        InProcessSearchEngine(field_weights={"title": 0.0})
    with pytest.raises(SearchError, match="field weight"):
        InProcessSearchEngine(field_weights={"title": math.inf})


def test_invalid_hybrid_weights_rejected() -> None:
    with pytest.raises(SearchError, match="weights"):
        InProcessSearchEngine(lexical_weight=-0.1, semantic_weight=1.0)
    with pytest.raises(SearchError, match="weights"):
        InProcessSearchEngine(lexical_weight=0.0, semantic_weight=0.0)


# ------------------------------------------------------------- lifecycle


def test_reindex_replaces_existing_document(engine: InProcessSearchEngine) -> None:
    engine.index(_text("doc-1", "first revision"))
    engine.index(_text("doc-1", "second revision"))

    assert engine.count(IndexName.POSTS) == 1
    assert engine.search(_query(text="first")).hits == ()
    assert [hit.doc_id for hit in engine.search(_query(text="second")).hits] == ["doc-1"]
    stored = engine.get(IndexName.POSTS, "doc-1")
    assert stored is not None and stored.fields["body"] == "second revision"


def test_remove_get_count_clear(engine: InProcessSearchEngine) -> None:
    engine.index(_text("a", "alpha"))
    assert engine.get(IndexName.POSTS, "a") is not None
    assert engine.remove(IndexName.POSTS, "a") is True
    assert engine.remove(IndexName.POSTS, "a") is False
    assert engine.get(IndexName.POSTS, "a") is None
    assert engine.count(IndexName.POSTS) == 0
    assert engine.count() == 0

    engine.index(_text("b", "beta"))
    assert engine.count() == 1
    engine.clear()
    assert engine.count() == 0


def test_search_on_untouched_index_returns_empty(engine: InProcessSearchEngine) -> None:
    result = engine.search(_query(text="anything", index=IndexName.REPORTS))
    assert result.hits == ()
    assert result.total == 0
    assert result.took_ms >= 0.0


def test_tokenless_text_query_raises(engine: InProcessSearchEngine) -> None:
    with pytest.raises(InvalidQueryError, match="no searchable tokens"):
        engine.search(_query(text="..."))


# ----------------------------------------------------------- performance

_VOCABULARY = (
    "ransomware",
    "marketplace",
    "vendor",
    "phishing",
    "bitcoin",
    "escrow",
    "forum",
    "leak",
    "credential",
    "handle",
    "mirror",
    "paste",
    "wallet",
    "listing",
    "buyer",
    "seller",
    "stealer",
    "dropper",
)


def _seed_performance_corpus(engine: InProcessSearchEngine, count: int = 400) -> None:
    """Deterministic 400-document corpus spread over all five indexes."""
    rng = random.Random(20260928)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    documents: list[IndexedDocument] = []
    for ordinal in range(count):
        body = " ".join(rng.choice(_VOCABULARY) for _ in range(40))
        title = " ".join(rng.choice(_VOCABULARY) for _ in range(4))
        timestamp = start + timedelta(minutes=rng.randrange(0, 365 * 24 * 60))
        source = f"source-{ordinal % 5}"
        entity_ids = (f"entity-{ordinal % 10}",)
        bucket = ordinal % 5
        if bucket == 0:
            documents.append(
                IndexedDocument.from_evidence(
                    _evidence(observed_at=timestamp), entity_ids=entity_ids
                )
            )
        elif bucket == 1:
            documents.append(IndexedDocument.from_entity(Entity.example()))
        else:
            target = (
                IndexName.POSTS
                if bucket == 2
                else IndexName.DOCUMENTS
                if bucket == 3
                else IndexName.REPORTS
            )
            documents.append(
                _text(
                    f"doc-{ordinal}",
                    body,
                    index=target,
                    title=title,
                    timestamp=timestamp,
                    source=source,
                    entity_ids=entity_ids,
                )
            )
    engine.index_many(documents)


_PERF_QUERIES = (
    SearchQuery(text="marketplace vendor", index=IndexName.POSTS),
    SearchQuery(text="vendor", index=IndexName.POSTS, match_mode=MatchMode.EXACT),
    SearchQuery(text="marketplace vendor", index=IndexName.DOCUMENTS, match_mode=MatchMode.PHRASE),
    SearchQuery(
        text="phishing credential",
        index=IndexName.POSTS,
        since=datetime(2026, 3, 1, tzinfo=UTC),
        until=datetime(2026, 10, 1, tzinfo=UTC),
    ),
    SearchQuery(index=IndexName.DOCUMENTS, sources=("source-2",)),
    SearchQuery(text="leak paste", index=IndexName.REPORTS, entity_ids=("entity-3",)),
    SearchQuery(
        text="stealer dropper", index=IndexName.DOCUMENTS, retrieval_mode=RetrievalMode.HYBRID
    ),
    SearchQuery(text="ghostbroker", index=IndexName.ENTITIES, match_mode=MatchMode.EXACT),
)


def test_p95_latency_within_target(engine: InProcessSearchEngine) -> None:
    _seed_performance_corpus(engine, count=400)
    assert engine.count() == 400

    latencies: list[float] = []
    for _ in range(3):  # 24 mixed queries across all six features
        for query in _PERF_QUERIES:
            started = perf_counter()
            engine.search(query)
            latencies.append((perf_counter() - started) * 1000.0)

    ordered = sorted(latencies)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    assert P95_LATENCY_TARGET_MS > 0
    assert p95 <= P95_LATENCY_TARGET_MS, (
        f"p95={p95:.2f}ms over {len(ordered)} queries exceeds the {P95_LATENCY_TARGET_MS}ms target"
    )


def test_p95_target_documented_before_optimization_notes() -> None:
    module = sys.modules["aegis.search.engine"]
    doc = inspect.getdoc(module) or ""
    notes = doc.index("Implementation and optimization notes")
    target = doc.index("P95_LATENCY_TARGET_MS")
    assert target < notes, "the p95 target must be declared before optimization notes"
    assert "100.0" in doc[:notes]


# ------------------------------------------------- OpenSearch Query DSL


def test_index_name_prefixing() -> None:
    assert index_name("aegis", IndexName.POSTS) == "aegis-posts"
    assert index_name("", IndexName.EVIDENCE) == "evidence"
    assert index_name("Weird Name!", IndexName.ENTITIES) == "weird-name-entities"


def test_build_body_terms_mode() -> None:
    body = build_search_body(SearchQuery(text="alpha beta", limit=5))

    clause = body["query"]["bool"]["must"][0]["multi_match"]
    assert clause["type"] == "best_fields"
    assert clause["operator"] == "or"
    assert clause["fields"] == ["fields.*"]
    assert body["size"] == 5
    assert body["track_total_hits"] is True
    assert body["sort"][0] == "_score"


def test_build_body_exact_mode_ands_every_token() -> None:
    body = build_search_body(SearchQuery(text="alpha beta", match_mode=MatchMode.EXACT))

    must = body["query"]["bool"]["must"][0]["bool"]["must"]
    assert [clause["multi_match"]["query"] for clause in must] == ["alpha", "beta"]


def test_build_body_phrase_mode() -> None:
    body = build_search_body(SearchQuery(text="alpha beta", match_mode=MatchMode.PHRASE))

    clause = body["query"]["bool"]["must"][0]["multi_match"]
    assert clause["type"] == "phrase"
    assert clause["query"] == "alpha beta"


def test_build_body_filters() -> None:
    query = SearchQuery(
        text="alpha",
        since=SINCE,
        until=UNTIL,
        sources=("source-1", "source-2"),
        entity_ids=("entity-7",),
    )
    filters = build_search_body(query)["query"]["bool"]["filter"]

    assert {"range": {"timestamp": {"gte": SINCE.isoformat(), "lte": UNTIL.isoformat()}}} in filters
    assert {"terms": {"source": ["source-1", "source-2"]}} in filters
    assert {"terms": {"entity_ids": ["entity-7"]}} in filters
    assert len(filters) == 3


def test_build_body_filter_only_uses_match_all() -> None:
    body = build_search_body(SearchQuery(sources=("source-1",)))
    assert body["query"]["bool"]["must"][0] == {"match_all": {}}
    assert body["query"]["bool"]["filter"] == [{"terms": {"source": ["source-1"]}}]


def test_build_body_hybrid_adds_fuzzy_should_clause() -> None:
    body = build_search_body(SearchQuery(text="alpha beta", retrieval_mode=RetrievalMode.HYBRID))

    hybrid = body["query"]["bool"]["must"][0]["bool"]
    assert hybrid["minimum_should_match"] == 1
    lexical, fuzzy = hybrid["should"]
    assert lexical["boost"] == pytest.approx(0.7)
    assert fuzzy["multi_match"]["fuzziness"] == "AUTO"
    assert fuzzy["boost"] == pytest.approx(0.3)


def test_build_body_rejects_tokenless_text() -> None:
    with pytest.raises(InvalidQueryError, match="no searchable tokens"):
        build_search_body(SearchQuery(text="!!!"))


def test_document_body_serializes_canonical_payload() -> None:
    evidence = _evidence(observed_at=NOW, metadata={"note": "ransomware leak"})
    document = IndexedDocument.from_evidence(evidence, entity_ids={"e-2", "e-1"})
    body = document_body(document)

    assert body["payload_type"] == "Evidence"
    assert body["payload"]["evidence_id"] == str(evidence.evidence_id)
    assert body["entity_ids"] == ["e-1", "e-2"]  # sorted for stability
    assert body["timestamp"] == NOW.isoformat()
    assert body["doc_id"] == str(evidence.evidence_id)


def test_document_body_drops_non_canonical_payload() -> None:
    document = _text("a", "body", payload={"arbitrary": "object"})
    body = document_body(document)
    assert body["payload"] is None
    assert body["payload_type"] is None


def test_parse_response_rehydrates_payload_and_provenance() -> None:
    evidence = _evidence(metadata={"note": "ransomware leak"})
    document = IndexedDocument.from_evidence(evidence)
    response = {
        "took": 7,
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [
                {"_id": "remote-1", "_score": 4.5, "_source": document_body(document)},
            ],
        },
    }

    result = parse_search_response(
        SearchQuery(text="ransomware", index=IndexName.EVIDENCE), response
    )
    assert result.total == 1
    assert result.took_ms == 7.0
    hit = result.hits[0]
    assert hit.doc_id == str(evidence.evidence_id)
    assert hit.score == 4.5
    assert isinstance(hit.document.payload, Evidence)
    assert hit.document.payload.evidence_id == evidence.evidence_id
    assert hit.matched_fields == ("metadata",)
    assert hit.matched_terms == ("ransomware",)
    assert hit.breakdown.final == 4.5
    assert hit.breakdown.lexical == 4.5  # lexical mode: score is the lexical component
    assert hit.breakdown.semantic == 0.0


# ------------------------------------------------- OpenSearch adapter


class _FakeClient:
    """Minimal stand-in for ``opensearchpy.OpenSearch``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.response: dict[str, object] = {}
        self.delete_error: Exception | None = None
        self.search_error: Exception | None = None

    def index(self, **kwargs: object) -> None:
        self.calls.append(("index", kwargs))

    def delete(self, **kwargs: object) -> None:
        self.calls.append(("delete", kwargs))
        if self.delete_error is not None:
            raise self.delete_error

    def search(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("search", kwargs))
        if self.search_error is not None:
            raise self.search_error
        return self.response


class _NotFound(Exception):
    status_code = 404


def test_adapter_indexes_with_fake_client() -> None:
    client = _FakeClient()
    adapter = OpenSearchAdapter(client=client)
    evidence = _evidence()
    document = IndexedDocument.from_evidence(evidence)

    adapter.index(document)

    verb, kwargs = client.calls[0]
    assert verb == "index"
    assert kwargs["index"] == "aegis-evidence"
    assert kwargs["id"] == str(evidence.evidence_id)
    assert kwargs["body"]["payload_type"] == "Evidence"  # type: ignore[index]


def test_adapter_search_parses_response() -> None:
    client = _FakeClient()
    document = _text("local-1", "marketplace listing", index=IndexName.DOCUMENTS)
    client.response = {
        "took": 3,
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [{"_id": "local-1", "_score": 2.0, "_source": document_body(document)}],
        },
    }
    adapter = OpenSearchAdapter(client=client, index_prefix="aegis")

    result = adapter.search(SearchQuery(text="marketplace", index=IndexName.DOCUMENTS))

    verb, kwargs = client.calls[0]
    assert verb == "search"
    assert kwargs["index"] == "aegis-documents"
    assert result.total == 1
    assert result.took_ms == 3.0
    assert result.hits[0].doc_id == "local-1"
    assert result.hits[0].matched_terms == ("marketplace",)
    assert result.hits[0].document.fields["body"] == "marketplace listing"


def test_adapter_remove_handles_404_and_errors() -> None:
    client = _FakeClient()
    adapter = OpenSearchAdapter(client=client)

    client.delete_error = _NotFound()
    assert adapter.remove(IndexName.POSTS, "gone") is False

    client.delete_error = RuntimeError("connection refused")
    with pytest.raises(SearchError, match="connection refused"):
        adapter.remove(IndexName.POSTS, "doc-1")

    client.delete_error = None
    assert adapter.remove(IndexName.POSTS, "doc-1") is True


def test_adapter_wraps_client_search_errors() -> None:
    client = _FakeClient()
    client.search_error = RuntimeError("cluster red")
    adapter = OpenSearchAdapter(client=client)

    with pytest.raises(SearchError, match="cluster red"):
        adapter.search(SearchQuery(text="anything"))


def test_adapter_client_import_is_lazy_and_helpful(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "opensearchpy":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    adapter = OpenSearchAdapter(hosts="http://localhost:9200")
    with pytest.raises(SearchError, match="opensearch-py"):
        _ = adapter.client


def test_opensearchpy_not_imported_at_module_import() -> None:
    assert "opensearchpy" not in sys.modules
    # Constructing the adapter (without touching .client) stays import-free.
    OpenSearchAdapter(hosts="http://localhost:9200")
    assert "opensearchpy" not in sys.modules
