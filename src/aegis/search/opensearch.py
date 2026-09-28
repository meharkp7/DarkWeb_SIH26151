"""OpenSearch adapter for search and retrieval (Phase 10).

The in-process engine (``aegis.search.engine``) is the source of truth
for tests and single-node deployments; this module builds the
*equivalent OpenSearch Query DSL* for production clusters, mirroring the
lazy optional-dependency pattern of ``aegis.graph.neo4j`` and
``aegis.storage.s3``: ``opensearch-py`` is imported only inside the
``client`` property, never at module import time, so the base install
and all tests stay free of the dependency.

Both implementations satisfy the :class:`~aegis.search.types.SearchEngine`
protocol and are therefore interchangeable. Query-semantics mapping:

=================  =========================================================
In-process          OpenSearch Query DSL
=================  =========================================================
filter-only         ``bool`` with ``match_all`` core + ``bool.filter``
(blank text)
``TERMS``           ``multi_match`` ``best_fields`` ``operator: or`` (BM25
                    ranking is OpenSearch's default ``lucene`` similarity)
``EXACT``           ``bool.must`` of one ``multi_match`` per query token:
                    every token must be present in at least one text
                    field, with no fuzzy/prefix expansion
``PHRASE``          ``multi_match`` ``type: phrase`` (contiguous, in order,
                    within one field)
``since``/``until``  ``range`` on ``timestamp`` — a missing timestamp fails
                    the clause, exactly as the in-process filter does
``sources``         ``terms`` on ``source``
``entity_ids``      ``terms`` on ``entity_ids`` (any-of intersection)
``HYBRID``          ``bool.should`` of the lexical clause plus a fuzzy
                    (``fuzziness: AUTO``) clause with engine-default
                    boosts — approximates the in-process
                    n-gram/token-overlap signal without an ML runtime.
                    Score parity is not promised; ranking intent and all
                    filters are interchangeable behind the protocol.
=================  =========================================================

Provenance: hits parsed from a remote response carry recomputed
``matched_fields``/``matched_terms`` (same tokenizer as the in-process
engine) and a :class:`~aegis.search.types.ScoreBreakdown` whose
``final`` is the engine-reported score; component attribution (lexical
vs semantic) is only available from the in-process engine, which is why
the remote breakdown reports ``lexical == final`` in lexical retrieval
and zeroes both components in hybrid retrieval (the cluster combined
them server-side; use OpenSearch ``explain`` for a server-side
breakdown).

Expected index mapping: ``fields`` is a text object (dynamic mapping is
fine), ``timestamp`` is ``date``, ``source``/``entity_ids``/``doc_id``
are ``keyword``. Canonical ``Evidence``/``Observation``/``Entity``
payloads round-trip through ``payload`` + ``payload_type``; other
payloads are deliberately not persisted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from aegis.schemas import Entity, Evidence, Observation
from aegis.search.types import (
    IndexedDocument,
    IndexName,
    MatchMode,
    RetrievalMode,
    ScoreBreakdown,
    SearchError,
    SearchHit,
    SearchQuery,
    SearchResult,
    query_tokens,
    tokenize,
)

DEFAULT_TEXT_FIELDS: Final[tuple[str, ...]] = ("fields.*",)
"""Default ``multi_match`` field patterns; ``fields.*`` expands to the
document's text fields while excluding ``timestamp``/``source``/
``entity_ids``/``doc_id``, matching what the in-process engine searches."""

_HYBRID_LEXICAL_BOOST: Final = 0.7
_HYBRID_SEMANTIC_BOOST: Final = 0.3

_PAYLOAD_MODELS: Final[dict[str, type[BaseModel]]] = {
    "Evidence": Evidence,
    "Observation": Observation,
    "Entity": Entity,
}


def index_name(prefix: str, index: IndexName) -> str:
    """Physical index name: sanitized prefix + ``-`` + plan index name.

    An empty prefix addresses the bare index name (used in tests and by
    deployments that manage index names themselves).
    """
    sanitized = re.sub(r"[^a-z0-9_-]+", "-", prefix.strip().lower()).strip("-_")
    return f"{sanitized}-{index.value}" if sanitized else index.value


def _filter_clauses(query: SearchQuery) -> list[dict[str, Any]]:
    """``bool.filter`` clauses (non-scoring, cacheable in OpenSearch)."""
    clauses: list[dict[str, Any]] = []
    if query.since is not None or query.until is not None:
        bounds: dict[str, str] = {}
        if query.since is not None:
            bounds["gte"] = query.since.isoformat()
        if query.until is not None:
            bounds["lte"] = query.until.isoformat()
        clauses.append({"range": {"timestamp": bounds}})
    if query.sources:
        clauses.append({"terms": {"source": list(query.sources)}})
    if query.entity_ids:
        clauses.append({"terms": {"entity_ids": list(query.entity_ids)}})
    return clauses


def _lexical_clause(query: SearchQuery, text_fields: Sequence[str]) -> dict[str, Any]:
    """Core matching clause for the query's :class:`MatchMode`."""
    fields = list(text_fields)
    if query.match_mode is MatchMode.EXACT:
        # One clause per token, ANDed: every token must be present in at
        # least one field — the exact counterpart of the in-process
        # posting intersection.
        return {
            "bool": {
                "must": [
                    {"multi_match": {"query": token, "fields": fields}}
                    for token in query_tokens(query)
                ]
            }
        }
    if query.match_mode is MatchMode.PHRASE:
        return {"multi_match": {"query": query.text, "type": "phrase", "fields": fields}}
    return {
        "multi_match": {
            "query": query.text,
            "type": "best_fields",
            "operator": "or",
            "fields": fields,
        }
    }


def build_search_body(
    query: SearchQuery, *, text_fields: Sequence[str] = DEFAULT_TEXT_FIELDS
) -> dict[str, Any]:
    """Build the OpenSearch request body (pure; unit-testable offline).

    Raises :class:`~aegis.search.types.InvalidQueryError` for text with
    no searchable tokens, exactly like the in-process engine.
    """
    tokens = query_tokens(query)
    if not tokens:
        core: dict[str, Any] = {"match_all": {}}
    else:
        core = _lexical_clause(query, text_fields)
        if query.retrieval_mode is RetrievalMode.HYBRID:
            fuzzy: dict[str, Any] = {
                "multi_match": {
                    "query": query.text,
                    "type": "best_fields",
                    "operator": "or",
                    "fields": list(text_fields),
                    "fuzziness": "AUTO",
                }
            }
            core = {
                "bool": {
                    "should": [
                        {**core, "boost": _HYBRID_LEXICAL_BOOST},
                        {**fuzzy, "boost": _HYBRID_SEMANTIC_BOOST},
                    ],
                    "minimum_should_match": 1,
                }
            }
    return {
        "size": query.limit,
        "track_total_hits": True,
        "track_scores": True,
        "query": {"bool": {"must": [core], "filter": _filter_clauses(query)}},
        "sort": ["_score", {"doc_id": {"order": "asc", "unmapped_type": "keyword"}}],
    }


def _serialize_payload(payload: object | None) -> tuple[Any, str | None]:
    """Serialize a *canonical* payload; non-canonical payloads are dropped."""
    if isinstance(payload, BaseModel) and type(payload).__name__ in _PAYLOAD_MODELS:
        return payload.model_dump(mode="json"), type(payload).__name__
    return None, None


def _rehydrate_payload(type_name: object, data: object) -> object | None:
    if not type_name or data is None:
        return None
    model = _PAYLOAD_MODELS.get(str(type_name))
    if model is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise SearchError(f"stored {type_name} payload failed validation: {exc}") from exc


INDEX_MAPPING: Final[dict[str, Any]] = {
    "properties": {
        "doc_id": {"type": "keyword"},
        "index": {"type": "keyword"},
        "fields": {"type": "object"},
        "timestamp": {"type": "date"},
        "source": {"type": "keyword"},
        "entity_ids": {"type": "keyword"},
        "payload": {"type": "object", "enabled": True},
        "payload_type": {"type": "keyword"},
    }
}


def document_body(document: IndexedDocument) -> dict[str, Any]:
    """Serialize *document* into the OpenSearch ``_source`` body."""
    payload, payload_type = _serialize_payload(document.payload)
    return {
        "doc_id": document.doc_id,
        "index": document.index.value,
        "fields": dict(document.fields),
        "timestamp": document.timestamp.isoformat() if document.timestamp else None,
        "source": document.source,
        "entity_ids": sorted(document.entity_ids),
        "payload": payload,
        "payload_type": payload_type,
    }


def _document_from_source(
    index: IndexName, doc_id: str, source: Mapping[str, Any]
) -> IndexedDocument:
    raw_fields = dict(source.get("fields") or {})
    fields = {str(name): str(text) for name, text in raw_fields.items()}
    raw_timestamp = source.get("timestamp")
    timestamp = datetime.fromisoformat(str(raw_timestamp)) if raw_timestamp else None
    raw_source = source.get("source")
    entity_ids = frozenset(str(item) for item in (source.get("entity_ids") or ()))
    payload = _rehydrate_payload(source.get("payload_type"), source.get("payload"))
    return IndexedDocument(
        index=index,
        doc_id=doc_id,
        fields=fields,
        timestamp=timestamp,
        source=str(raw_source) if raw_source is not None else None,
        entity_ids=entity_ids,
        payload=payload,
    )


def _match_provenance(
    query: SearchQuery, document: IndexedDocument
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Recompute matched fields/terms with the shared tokenizer."""
    tokens = query_tokens(query)
    if not tokens:
        return (), ()
    per_field = {name: set(tokenize(text)) for name, text in document.fields.items()}
    wanted = tuple(dict.fromkeys(tokens))
    matched_terms = tuple(
        token for token in wanted if any(token in terms for terms in per_field.values())
    )
    matched_fields = tuple(
        sorted(name for name, terms in per_field.items() if any(t in terms for t in wanted))
    )
    return matched_fields, matched_terms


def parse_search_response(query: SearchQuery, response: Mapping[str, Any]) -> SearchResult:
    """Map an OpenSearch response onto :class:`SearchResult` (pure)."""
    raw_hits = response.get("hits") or {}
    total_raw = raw_hits.get("total", 0)
    if isinstance(total_raw, Mapping):
        total = int(total_raw.get("value", 0))
    else:
        total = int(total_raw)
    lexical_only = query.retrieval_mode is RetrievalMode.LEXICAL
    hits: list[SearchHit] = []
    for raw in raw_hits.get("hits") or []:
        source = dict(raw.get("_source") or {})
        doc_id = str(source.get("doc_id") or raw.get("_id") or "")
        document = _document_from_source(query.index, doc_id, source)
        score = float(raw.get("_score") or 0.0)
        matched_fields, matched_terms = _match_provenance(query, document)
        # The cluster combines components server-side; see module docstring.
        breakdown = ScoreBreakdown(
            lexical=score if lexical_only else 0.0,
            semantic=0.0,
            final=score,
        )
        hits.append(
            SearchHit(
                index=query.index,
                doc_id=doc_id,
                score=score,
                breakdown=breakdown,
                matched_fields=matched_fields,
                matched_terms=matched_terms,
                document=document,
            )
        )
    return SearchResult(
        query=query,
        hits=tuple(hits),
        total=total,
        took_ms=float(response.get("took", 0) or 0),
    )


class OpenSearchAdapter:
    """SearchEngine implementation backed by an OpenSearch cluster.

    The ``opensearch-py`` client is created lazily on first use (or can
    be injected for tests); constructing the adapter never imports the
    optional dependency's module eagerly beyond that property, and never
    connects.
    """

    def __init__(
        self,
        hosts: str | Sequence[str] = "http://localhost:9200",
        *,
        index_prefix: str = "aegis",
        text_fields: Sequence[str] = DEFAULT_TEXT_FIELDS,
        http_auth: tuple[str, str] | None = None,
        client: Any | None = None,
        **client_options: Any,
    ) -> None:
        self.hosts = hosts
        self.index_prefix = index_prefix
        self.text_fields = tuple(text_fields)
        self.http_auth = http_auth
        self.client_options = client_options
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from opensearchpy import (  # noqa: PLC0415
                    OpenSearch,
                )
            except ImportError as exc:
                raise SearchError(
                    "opensearch-py is required for OpenSearchAdapter; "
                    "install aegis-intelligence[search]"
                ) from exc
            self._client = OpenSearch(
                hosts=self.hosts, http_auth=self.http_auth, **self.client_options
            )
        return self._client

    def index(self, document: IndexedDocument) -> None:
        """Index (or overwrite) one document."""
        physical_index = index_name(self.index_prefix, document.index)
        try:
            if not self.client.indices.exists(index=physical_index):
                self.client.indices.create(
                    index=physical_index,
                    body={"mappings": INDEX_MAPPING},
                )
            self.client.index(
                index=physical_index,
                id=document.doc_id,
                body=document_body(document),
                refresh="wait_for",
            )
        except SearchError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            raise SearchError(f"indexing {document.doc_id!r} failed: {exc}") from exc

    def remove(self, index: IndexName, doc_id: str) -> bool:
        """Delete ``doc_id``; ``False`` when the document is absent (404)."""
        try:
            self.client.delete(index=index_name(self.index_prefix, index), id=doc_id)
        except SearchError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            if getattr(exc, "status_code", None) == 404:
                return False
            raise SearchError(f"deleting {doc_id!r} failed: {exc}") from exc
        return True

    def search(self, query: SearchQuery) -> SearchResult:
        """Run *query* against the cluster and parse provenance-carrying hits."""
        body = build_search_body(query, text_fields=self.text_fields)
        try:
            response = self.client.search(
                index=index_name(self.index_prefix, query.index), body=body
            )
        except SearchError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            raise SearchError(f"search failed: {exc}") from exc
        if not isinstance(response, Mapping):
            raise SearchError(f"unexpected search response type: {type(response).__name__}")
        return parse_search_response(query, response)
