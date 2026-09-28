"""Search and retrieval layer (Phase 10).

Two interchangeable implementations behind the
:class:`~aegis.search.types.SearchEngine` protocol:

-   :class:`~aegis.search.engine.InProcessSearchEngine` — a fully
    in-process, deterministic engine (inverted index, BM25, positional
    phrase matching, dependency-free hybrid retrieval) that is the
    source of truth for tests and single-node deployments. Its explicit
    p95 latency budget is :data:`~aegis.search.engine.P95_LATENCY_TARGET_MS`
    (100 ms), declared before any optimization discussion in that
    module's docstring and enforced by ``tests/test_search.py``.
-   :class:`~aegis.search.opensearch.OpenSearchAdapter` — a lazy
    ``opensearch-py`` adapter that issues equivalent OpenSearch Query
    DSL for production clusters; the optional dependency is imported
    only inside the adapter's ``client`` property.

All six plan features are supported on both: exact search, phrase
search, time filtering, source filtering, entity filtering, and hybrid
retrieval. Canonical evidence shapes come from ``aegis.schemas``
(``Evidence``, ``Observation``, ``Entity``); search query/result types
are new domain types owned by this package. Every hit reports why it
matched: matched fields, matched terms, and a score breakdown.
"""

from aegis.search.engine import P95_LATENCY_TARGET_MS, InProcessSearchEngine
from aegis.search.opensearch import (
    DEFAULT_TEXT_FIELDS,
    OpenSearchAdapter,
    build_search_body,
    document_body,
    index_name,
    parse_search_response,
)
from aegis.search.types import (
    MAX_QUERY_LIMIT,
    IndexedDocument,
    IndexName,
    InvalidDocumentError,
    InvalidQueryError,
    MatchMode,
    RetrievalMode,
    ScoreBreakdown,
    SearchEngine,
    SearchError,
    SearchHit,
    SearchQuery,
    SearchResult,
    character_ngrams,
    query_tokens,
    tokenize,
)

__all__ = [
    "DEFAULT_TEXT_FIELDS",
    "MAX_QUERY_LIMIT",
    "P95_LATENCY_TARGET_MS",
    "IndexName",
    "IndexedDocument",
    "InProcessSearchEngine",
    "InvalidDocumentError",
    "InvalidQueryError",
    "MatchMode",
    "OpenSearchAdapter",
    "RetrievalMode",
    "ScoreBreakdown",
    "SearchEngine",
    "SearchError",
    "SearchHit",
    "SearchQuery",
    "SearchResult",
    "build_search_body",
    "character_ngrams",
    "document_body",
    "index_name",
    "parse_search_response",
    "query_tokens",
    "tokenize",
]
