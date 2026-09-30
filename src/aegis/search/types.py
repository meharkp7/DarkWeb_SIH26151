"""Search and retrieval domain types (Phase 10).

This module defines the vocabulary of the search layer:

-   the five indexes named by the implementation plan
    (``evidence``, ``posts``, ``documents``, ``entities``, ``reports``),
-   the query / result value objects, each search hit carrying explicit
    provenance (matched fields, matched terms, score breakdown),
-   :class:`IndexedDocument`, the wrapper that carries *canonical*
    pydantic schemas (``Evidence``, ``Observation``, ``Entity``) into an
    index so no parallel evidence schema is ever invented, and
-   :class:`SearchEngine`, the protocol behind which the in-process
    engine (``aegis.search.engine``) and the lazy OpenSearch adapter
    (``aegis.search.opensearch``) are interchangeable.

Text analysis is deliberately minimal and deterministic: case-fold the
text and split on runs of ``\\w+`` (:func:`tokenize`). The same
tokenizer is used by the in-process engine and by the OpenSearch
adapter's response parser so both produce identical match provenance.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from aegis.schemas import Entity, Evidence, Observation

#: Upper bound accepted for ``SearchQuery.limit`` (defensive DoS guard).
MAX_QUERY_LIMIT: Final = 1000

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class SearchError(RuntimeError):
    """Base class for search-layer failures (adapter boundary included)."""


class InvalidQueryError(SearchError):
    """The query is malformed (inverted time window, unknown index, tokenless text)."""


class InvalidDocumentError(SearchError):
    """A document cannot be indexed (empty id, naive timestamp, payload/index mismatch)."""


class IndexName(StrEnum):
    """The five indexes required by Implementation Plan Phase 10."""

    EVIDENCE = "evidence"
    POSTS = "posts"
    DOCUMENTS = "documents"
    ENTITIES = "entities"
    REPORTS = "reports"


class MatchMode(StrEnum):
    """How ``SearchQuery.text`` is matched against documents."""

    TERMS = "terms"
    """Full-text BM25 over the query tokens with OR semantics: documents
    missing some query tokens may still match and rank."""

    EXACT = "exact"
    """Every query token must be present as a whole token (AND
    semantics). No prefix, fuzzy, or partial matching is performed, and
    a bonus is awarded when the query equals an entire field value."""

    PHRASE = "phrase"
    """The query tokens must appear contiguously and in order inside a
    single field."""


class RetrievalMode(StrEnum):
    """Lexical-only scoring or hybrid lexical + semantic retrieval."""

    LEXICAL = "lexical"
    HYBRID = "hybrid"


def tokenize(text: str) -> list[str]:
    """Case-folded ``\\w+`` tokens of *text* (deterministic, locale-free)."""
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text)]


def character_ngrams(text: str, size: int = 3) -> frozenset[str]:
    """Character *size*-grams over ``#``-padded tokens.

    Padding mirrors the Phase 06 fingerprint features so word-boundary
    transitions participate in the similarity signal. Used as the
    lightweight (dependency-free) semantic signal of hybrid retrieval.
    """
    if size < 1:
        raise InvalidQueryError("n-gram size must be >= 1")
    pad = "#" * (size - 1)
    grams: set[str] = set()
    for token in tokenize(text):
        padded = f"{pad}{token}{pad}"
        for index in range(len(padded) - size + 1):
            grams.add(padded[index : index + size])
    return frozenset(grams)


def _coerce_enum[E: StrEnum](
    enum_cls: type[E], value: object, *, error_cls: type[SearchError]
) -> E:
    """Coerce runtime input (e.g. a bare string from an API layer) to *enum_cls*."""
    try:
        if not isinstance(value, str):
            raise ValueError(f"{type(value).__name__} input is not a string")
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(repr(member.value) for member in enum_cls)
        message = f"unknown {enum_cls.__name__} {value!r}; expected one of: {allowed}"
        raise error_cls(message) from exc


def _require_aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise InvalidQueryError(f"{name} must be timezone-aware (pass tzinfo=UTC)")
    return value


def _metadata_text(metadata: Mapping[str, object]) -> str:
    """Stable, searchable encoding of a schema ``metadata`` mapping."""
    return json.dumps(metadata, sort_keys=True, default=str)


@dataclass(frozen=True)
class IndexedDocument:
    """One searchable document bound to exactly one :class:`IndexName`.

    ``fields`` holds the text that is tokenized and searched
    (str field name -> str text). ``timestamp``, ``source``, and
    ``entity_ids`` power the time / source / entity filters and are
    *not* searched as text. ``payload`` optionally carries the canonical
    schema object the document was derived from, so hits can hand the
    caller back the original ``Evidence`` / ``Observation`` / ``Entity``
    instead of a parallel copy; the engine rejects canonical payloads in
    the wrong index.
    """

    index: IndexName
    doc_id: str
    fields: Mapping[str, str]
    timestamp: datetime | None = None
    source: str | None = None
    entity_ids: frozenset[str] = frozenset()
    payload: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "index", _coerce_enum(IndexName, self.index, error_cls=InvalidDocumentError)
        )
        if not isinstance(self.doc_id, str) or not self.doc_id.strip():
            raise InvalidDocumentError("doc_id must be a non-empty string")
        if not isinstance(self.fields, Mapping) or not self.fields:
            raise InvalidDocumentError(f"document {self.doc_id!r} has no searchable fields")
        for name, text in self.fields.items():
            if not isinstance(name, str) or not isinstance(text, str):
                raise InvalidDocumentError("searchable fields must map str -> str")
        if self.timestamp is not None and self.timestamp.tzinfo is None:
            raise InvalidDocumentError("timestamp must be timezone-aware (pass tzinfo=UTC)")
        if isinstance(self.entity_ids, str):
            raise InvalidDocumentError("entity_ids must be a collection of ids, not a bare string")
        object.__setattr__(self, "entity_ids", frozenset(str(eid) for eid in self.entity_ids))

    @classmethod
    def from_evidence(
        cls, evidence: Evidence, *, entity_ids: Iterable[str] = ()
    ) -> IndexedDocument:
        """Index a canonical :class:`~aegis.schemas.Evidence` record.

        The evidence index takes the ``Evidence`` object itself as its
        payload (no re-shaped copy). The timestamp prefers
        ``observed_at`` over ``collected_at``; ``source`` is the registry
        ``source_id`` so source filtering can address individual feeds.
        """
        fields = {
            "sha256": evidence.sha256,
            "artifact_uri": evidence.raw_artifact_uri,
            "collector": evidence.collector_name,
            "source_type": evidence.source_type.value,
            "entity_type": evidence.entity_type or "",
            "entity_value_hash": evidence.entity_value_hash or "",
            "case_id": str(evidence.case_id) if evidence.case_id else "",
            "metadata": _metadata_text(evidence.metadata),
        }
        return cls(
            index=IndexName.EVIDENCE,
            doc_id=str(evidence.evidence_id),
            fields=fields,
            timestamp=evidence.observed_at or evidence.collected_at,
            source=str(evidence.source_id),
            entity_ids=frozenset(entity_ids),
            payload=evidence,
        )

    @classmethod
    def from_observation(
        cls, observation: Observation, *, entity_ids: Iterable[str] = ()
    ) -> IndexedDocument:
        """Index a canonical :class:`~aegis.schemas.Observation`.

        Observations live in the evidence index (they are derived from
        evidence artifacts). ``source`` is the observation's
        independence group: it is the closest provenance anchor the
        schema carries and is what later stages use to discount
        non-independent corroboration.
        """
        fields = {
            "content_hash": observation.content_hash,
            "normalized_hash": observation.normalized_hash,
            "duplicate_cluster": observation.duplicate_cluster_id,
            "independence_group": observation.independence_group,
            "normalizer": observation.normalization_version,
            "evidence_id": str(observation.evidence_id),
            "metadata": _metadata_text(observation.metadata),
        }
        return cls(
            index=IndexName.EVIDENCE,
            doc_id=str(observation.observation_id),
            fields=fields,
            timestamp=observation.observed_at or observation.collected_at,
            source=observation.independence_group,
            entity_ids=frozenset(entity_ids),
            payload=observation,
        )

    @classmethod
    def from_entity(cls, entity: Entity, *, entity_ids: Iterable[str] = ()) -> IndexedDocument:
        """Index a canonical :class:`~aegis.schemas.Entity` record.

        The document links its own entity id so an entity-filtered
        search for *X* also returns the canonical entry for *X* itself.
        The timestamp prefers ``last_seen`` over ``first_seen``.
        """
        fields = {
            "surface_form": entity.surface_form,
            "normalized_form": entity.normalized_form,
            "entity_type": entity.entity_type.value,
            "evidence_id": str(entity.evidence_id),
            "case_id": str(entity.case_id) if entity.case_id else "",
            "metadata": _metadata_text(entity.metadata),
        }
        return cls(
            index=IndexName.ENTITIES,
            doc_id=str(entity.entity_id),
            fields=fields,
            timestamp=entity.last_seen or entity.first_seen,
            source=None,
            entity_ids=frozenset({str(entity.entity_id), *entity_ids}),
            payload=entity,
        )

    @classmethod
    def from_text(
        cls,
        index: IndexName,
        *,
        doc_id: str,
        body: str,
        title: str | None = None,
        timestamp: datetime | None = None,
        source: str | None = None,
        entity_ids: Iterable[str] = (),
        extra_fields: Mapping[str, str] | None = None,
        payload: object | None = None,
    ) -> IndexedDocument:
        """Index a free-form text document (post, document, report).

        The plan's ``posts``, ``documents``, and ``reports`` indexes have
        no canonical stored schema, so they take plain text plus the same
        timestamp / source / entity filter anchors as canonical documents.
        """
        fields: dict[str, str] = {"body": body}
        if title:
            fields["title"] = title
        if extra_fields:
            fields.update(extra_fields)
        return cls(
            index=_coerce_enum(IndexName, index, error_cls=InvalidDocumentError),
            doc_id=doc_id,
            fields=fields,
            timestamp=timestamp,
            source=source,
            entity_ids=frozenset(entity_ids),
            payload=payload,
        )


@dataclass(frozen=True)
class SearchQuery:
    """A search request against exactly one index.

    Blank ``text`` means filter-only browsing (every document passing
    the filters is returned, score 0, ordered by ``doc_id``). Text that
    is non-blank but contains no ``\\w+`` characters (e.g. ``\"...\"``)
    is rejected by :func:`query_tokens` as un-searchable.
    """

    text: str = ""
    index: IndexName = IndexName.EVIDENCE
    match_mode: MatchMode = MatchMode.TERMS
    retrieval_mode: RetrievalMode = RetrievalMode.LEXICAL
    since: datetime | None = None
    until: datetime | None = None
    sources: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    #: Restrict to these investigations.
    #:
    #: Separate from ``entity_ids`` on purpose. An entity filter asks "which
    #: artefacts mention this thing", which crosses case boundaries by
    #: design — that is how an analyst finds an artefact they did not know was
    #: filed elsewhere. A case filter asks "what happened *here*", and
    #: answering that with another investigation's records is not a weaker
    #: answer, it is a different one. The copilot needed the distinction: it
    #: had no way to say "this investigation", so "What changed in this
    #: investigation?" returned records from all of them.
    case_ids: tuple[str, ...] = ()
    limit: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise InvalidQueryError("query text must be a string")
        object.__setattr__(
            self, "index", _coerce_enum(IndexName, self.index, error_cls=InvalidQueryError)
        )
        object.__setattr__(
            self,
            "match_mode",
            _coerce_enum(MatchMode, self.match_mode, error_cls=InvalidQueryError),
        )
        object.__setattr__(
            self,
            "retrieval_mode",
            _coerce_enum(RetrievalMode, self.retrieval_mode, error_cls=InvalidQueryError),
        )
        for name in ("sources", "entity_ids", "case_ids"):
            value = getattr(self, name)
            if isinstance(value, str):
                raise InvalidQueryError(f"{name} must be a sequence of ids, not a bare string")
            object.__setattr__(self, name, tuple(str(item) for item in value))
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise InvalidQueryError("limit must be an integer")
        if not 1 <= self.limit <= MAX_QUERY_LIMIT:
            raise InvalidQueryError(f"limit must be within 1..{MAX_QUERY_LIMIT}")
        since = _require_aware(self.since, "since")
        until = _require_aware(self.until, "until")
        if since is not None and until is not None and until < since:
            raise InvalidQueryError("until must not precede since")


def query_tokens(query: SearchQuery) -> list[str]:
    """Tokens of *query.text*; ``[]`` for blank text (filter-only).

    Raises :class:`InvalidQueryError` when the text is non-blank yet
    yields no searchable tokens.
    """
    if not query.text.strip():
        return []
    tokens = tokenize(query.text)
    if not tokens:
        raise InvalidQueryError(
            f"query {query.text!r} contains no searchable tokens (letters, digits, or '_')"
        )
    return tokens


@dataclass(frozen=True)
class ScoreBreakdown:
    """Why a hit scored what it scored (per-hit provenance).

    ``lexical`` is the raw lexical component in BM25-like units (0.0 for
    filter-only hits). ``semantic`` is the dependency-free similarity
    signal in ``[0, 1]`` and is 0.0 outside hybrid retrieval. ``final``
    is the mode-dependent combination: in lexical retrieval
    ``final == lexical``; in hybrid retrieval the lexical component is
    normalized against the best candidate and combined as
    ``lexical_weight * normalized_lexical + semantic_weight * semantic``.
    """

    lexical: float
    semantic: float
    final: float


@dataclass(frozen=True)
class SearchHit:
    """One result with full match provenance."""

    index: IndexName
    doc_id: str
    score: float
    breakdown: ScoreBreakdown
    matched_fields: tuple[str, ...]
    matched_terms: tuple[str, ...]
    document: IndexedDocument


@dataclass(frozen=True)
class SearchResult:
    """Ordered hits plus totals and timing.

    ``total`` counts every document that matched the query *and* the
    filters before ``limit`` was applied; ``took_ms`` is the measured
    engine-side latency of the call.
    """

    query: SearchQuery
    hits: tuple[SearchHit, ...]
    total: int
    took_ms: float


@runtime_checkable
class SearchEngine(Protocol):
    """The interchangeable search backend contract.

    Both the in-process engine and the lazy OpenSearch adapter satisfy
    this protocol, so callers (API layer, evaluation runners) can swap
    implementations without touching query code.
    """

    def index(self, document: IndexedDocument) -> None:
        """Add or replace *document* in its index."""
        ...

    def remove(self, index: IndexName, doc_id: str) -> bool:
        """Delete ``doc_id``; return ``False`` when it was absent."""
        ...

    def search(self, query: SearchQuery) -> SearchResult:
        """Execute *query* and return provenance-carrying hits."""
        ...
