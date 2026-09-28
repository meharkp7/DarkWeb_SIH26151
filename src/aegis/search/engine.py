"""In-process search engine (Phase 10).

Latency target (stated first, before any optimization discussion, as the
implementation plan requires: *"Set an explicit p95 latency target before
optimization"*):

    ``P95_LATENCY_TARGET_MS = 100.0``

A single :meth:`InProcessSearchEngine.search` call on a warm index must
complete within 100 ms at the 95th percentile. Rationale: interactive
analyst retrieval should stay inside the ~100 ms "feels instant" budget;
on the 400-document benchmark corpus used by the test suite a query
measures roughly 1-10 ms in CPython, so the target keeps about an order
of magnitude of headroom for slow CI runners while still failing any
genuine algorithmic regression (an accidental full-corpus n-gram rebuild
or a quadratic phrase scan lands well above it).
``tests/test_search.py::test_p95_latency_within_target`` enforces the
target; :data:`P95_LATENCY_TARGET_MS` is the named constant other
phases should reuse rather than restate.

Implementation and optimization notes
-------------------------------------

-   Index-time precomputation: per-field token lists and term counts,
    per-field normalized text (for exact whole-field equality), and the
    character n-gram signature of each document are all computed once in
    :func:`_build_entry`; a query only touches the postings of its own
    tokens.
-   Candidate generation goes through a per-index inverted index
    (:class:`_Corpus`): union for BM25 ``TERMS`` matching, intersection
    for ``EXACT``/``PHRASE``, so filtering and scoring never scan the
    whole corpus in lexical mode.
-   Hybrid retrieval intentionally relaxes the last point: in the
    default ``TERMS`` mode it scores the whole (already filtered) index
    so documents sharing no exact token but high character-ngram
    similarity can still be retrieved. That linear scan is the
    trade-off behind the 100 ms budget and the 400-document benchmark;
    if outgrowing it becomes necessary, move to the lazy OpenSearch
    adapter (``aegis.search.opensearch``), which issues equivalent
    Query DSL for a production cluster.
-   Scoring is standard BM25 (k1=1.2, b=0.75) with optional per-field
    weights, plus flat bonuses for whole-field exact matches and phrase
    hits. Determinism is guaranteed: ties break on ``doc_id``, and
    fields are always iterated in sorted order.
-   Query-level hoisting: everything that depends only on the query and
    the corpus snapshot (de-duplicated token order, per-token IDF from
    postings document frequencies, average document length, the exact
    query string for field-equality bonuses, and the query n-gram set)
    is computed once in :meth:`InProcessSearchEngine.search` and passed
    down to per-candidate scoring, so the inner loop never rebuilds
    query sets or re-derives corpus statistics.
-   Top-k selection uses :func:`heapq.nsmallest` over the same
    ``(-score, doc_id)`` key the full sort used, giving O(n log k)
    selection instead of O(n log n) while producing a byte-identical
    ranking (the key is a total order because ``doc_id`` values are
    unique within an index). ``tests/test_search_ranking_regression.py``
    pins the output to a pre-optimization golden fixture.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Final

from aegis.schemas import Entity, Evidence, Observation
from aegis.search.types import (
    IndexedDocument,
    IndexName,
    InvalidDocumentError,
    MatchMode,
    RetrievalMode,
    ScoreBreakdown,
    SearchError,
    SearchHit,
    SearchQuery,
    SearchResult,
    character_ngrams,
    query_tokens,
    tokenize,
)

P95_LATENCY_TARGET_MS: Final = 100.0
"""Explicit p95 latency budget for one ``search()`` call (see module docstring)."""

_BM25_K1: Final = 1.2
_BM25_B: Final = 0.75
_PHRASE_BONUS: Final = 3.0
_FIELD_EXACT_BONUS: Final = 2.0
_NGRAM_SIZE: Final = 3
_DEFAULT_LEXICAL_WEIGHT: Final = 0.7
_DEFAULT_SEMANTIC_WEIGHT: Final = 0.3


@dataclass
class _DocEntry:
    """Everything a query needs about one document, computed at index time."""

    document: IndexedDocument
    field_tokens: dict[str, list[str]]
    field_counts: dict[str, dict[str, int]]
    field_norms: dict[str, str]
    token_counts: dict[str, int]
    term_set: frozenset[str]
    ngrams: frozenset[str]
    length: int


def _build_entry(document: IndexedDocument) -> _DocEntry:
    field_tokens: dict[str, list[str]] = {}
    field_counts: dict[str, dict[str, int]] = {}
    field_norms: dict[str, str] = {}
    token_counts: Counter[str] = Counter()
    ngrams: set[str] = set()
    # Sorted iteration keeps float summation and dict order deterministic
    # regardless of how the caller ordered its mapping.
    for name, text in sorted(document.fields.items()):
        tokens = tokenize(text)
        field_tokens[name] = tokens
        field_counts[name] = dict(Counter(tokens))
        field_norms[name] = " ".join(tokens)
        token_counts.update(tokens)
        ngrams.update(character_ngrams(text, _NGRAM_SIZE))
    return _DocEntry(
        document=document,
        field_tokens=field_tokens,
        field_counts=field_counts,
        field_norms=field_norms,
        token_counts=dict(token_counts),
        term_set=frozenset(token_counts),
        ngrams=frozenset(ngrams),
        length=sum(token_counts.values()),
    )


class _Corpus:
    """Inverted index for a single :class:`IndexName`."""

    def __init__(self) -> None:
        self.entries: dict[str, _DocEntry] = {}
        self.postings: dict[str, set[str]] = {}
        self.total_length = 0

    @property
    def doc_count(self) -> int:
        return len(self.entries)

    @property
    def avg_length(self) -> float:
        return self.total_length / len(self.entries) if self.entries else 1.0

    def add(self, entry: _DocEntry) -> None:
        doc_id = entry.document.doc_id
        self.entries[doc_id] = entry
        for token in entry.token_counts:
            self.postings.setdefault(token, set()).add(doc_id)
        self.total_length += entry.length

    def remove(self, doc_id: str) -> bool:
        entry = self.entries.pop(doc_id, None)
        if entry is None:
            return False
        for token in entry.token_counts:
            holders = self.postings.get(token)
            if holders is not None:
                holders.discard(doc_id)
                if not holders:
                    del self.postings[token]
        self.total_length -= entry.length
        return True


@dataclass
class _Prepared:
    """A scored candidate before ranking and slicing."""

    entry: _DocEntry
    lexical: float
    semantic: float
    final: float
    matched_fields: tuple[str, ...]
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class _QueryStats:
    """Per-query BM25 constants, computed once and shared by all candidates.

    Every value here depends only on the query and the corpus snapshot
    taken when the query starts, never on an individual document, so
    hoisting them out of the candidate loop keeps the hot path free of
    ``dict.fromkeys`` rebuilds, ``math.log`` IDF recomputation, and
    repeated corpus property evaluation.
    """

    unique_tokens: tuple[str, ...]
    """Query tokens de-duplicated, preserving first-seen order."""

    idf: dict[str, float]
    """IDF per query token; tokens absent from the index are omitted."""

    avg_length: float
    """Corpus average document length (``1.0`` fallback, as before)."""


def _ranking_key(item: _Prepared) -> tuple[float, str]:
    """Sort key for final ranking: score descending, then ``doc_id`` ascending.

    ``-score`` rather than ``reverse=True`` because the two components
    rank in opposite directions; a single ascending sort on this key is
    exactly the order the previous full sort produced, which is what
    keeps :func:`heapq.nsmallest` output identical.
    """
    return (-item.final, item.entry.document.doc_id)


def _posting_union(corpus: _Corpus, tokens: Sequence[str]) -> set[str]:
    doc_ids: set[str] = set()
    for token in tokens:
        doc_ids.update(corpus.postings.get(token, ()))
    return doc_ids


def _posting_intersection(corpus: _Corpus, tokens: Sequence[str]) -> set[str]:
    doc_ids = set(corpus.postings.get(tokens[0], ()))
    for token in tokens[1:]:
        doc_ids &= corpus.postings.get(token, set())
        if not doc_ids:
            break
    return doc_ids


def _phrase_fields(entry: _DocEntry, tokens: Sequence[str]) -> tuple[str, ...]:
    """Fields where *tokens* occur contiguously and in order."""
    span = len(tokens)
    wanted = list(tokens)
    matched: list[str] = []
    for name, sequence in entry.field_tokens.items():
        for start in range(len(sequence) - span + 1):
            if sequence[start] == wanted[0] and sequence[start : start + span] == wanted:
                matched.append(name)
                break
    return tuple(sorted(matched))


def _fields_with_terms(entry: _DocEntry, tokens: Sequence[str]) -> tuple[str, ...]:
    """Fields containing any of *tokens*; callers pass pre-deduplicated tokens."""
    return tuple(
        sorted(
            name
            for name, counts in entry.field_counts.items()
            if any(token in counts for token in tokens)
        )
    )


def _passes_filters(
    document: IndexedDocument,
    since: datetime | None,
    until: datetime | None,
    sources: frozenset[str],
    entity_ids: frozenset[str],
) -> bool:
    """Time / source / entity filtering.

    A document without a timestamp fails any time filter (mirroring how
    a missing field fails an OpenSearch ``range`` clause); source and
    entity filters are any-of intersections and exclude documents that
    carry no such anchor.
    """
    timestamp = document.timestamp
    if since is not None and (timestamp is None or timestamp < since):
        return False
    if until is not None and (timestamp is None or timestamp > until):
        return False
    if sources and (document.source is None or document.source not in sources):
        return False
    if entity_ids and not entity_ids & document.entity_ids:
        return False
    return True


def _semantic_similarity(
    tokens: Sequence[str], query_ngrams: frozenset[str], entry: _DocEntry
) -> float:
    """Lightweight semantic signal in ``[0, 1]``: half character n-gram
    Dice coefficient, half token-set Jaccard. No ML dependencies."""
    if query_ngrams and entry.ngrams:
        dice = 2.0 * len(query_ngrams & entry.ngrams) / (len(query_ngrams) + len(entry.ngrams))
    else:
        dice = 0.0
    query_set = set(tokens)
    union = len(query_set | entry.term_set)
    jaccard = len(query_set & entry.term_set) / union if union else 0.0
    return 0.5 * dice + 0.5 * jaccard


class InProcessSearchEngine:
    """Fully in-process, deterministic search engine.

    Implements the :class:`~aegis.search.types.SearchEngine` protocol
    over the plan's five indexes and all six required features: exact
    search, phrase search, time filtering, source filtering, entity
    filtering, and hybrid retrieval (BM25 lexical + n-gram/token-overlap
    semantic). Every hit reports matched fields, matched terms, and a
    :class:`~aegis.search.types.ScoreBreakdown`.
    """

    def __init__(
        self,
        *,
        field_weights: Mapping[str, float] | None = None,
        lexical_weight: float = _DEFAULT_LEXICAL_WEIGHT,
        semantic_weight: float = _DEFAULT_SEMANTIC_WEIGHT,
    ) -> None:
        self._field_weights: dict[str, float] = dict(field_weights or {})
        for name, weight in self._field_weights.items():
            if not math.isfinite(weight) or weight <= 0.0:
                raise SearchError(f"field weight for {name!r} must be finite and > 0")
        total = lexical_weight + semantic_weight
        if (
            not math.isfinite(lexical_weight)
            or not math.isfinite(semantic_weight)
            or lexical_weight < 0.0
            or semantic_weight < 0.0
            or total <= 0.0
        ):
            raise SearchError(
                "lexical/semantic weights must be finite, non-negative, and sum to > 0"
            )
        self.lexical_weight = lexical_weight / total
        self.semantic_weight = semantic_weight / total
        self._corpora: dict[IndexName, _Corpus] = {}

    # ------------------------------------------------------------- indexing

    @staticmethod
    def _validate(document: IndexedDocument) -> None:
        payload = document.payload
        if isinstance(payload, (Evidence, Observation)) and (
            document.index is not IndexName.EVIDENCE
        ):
            raise InvalidDocumentError(
                f"{type(payload).__name__} payloads belong in the 'evidence' index, "
                f"not {document.index.value!r}"
            )
        if isinstance(payload, Entity) and document.index is not IndexName.ENTITIES:
            raise InvalidDocumentError(
                f"Entity payloads belong in the 'entities' index, not {document.index.value!r}"
            )

    def index(self, document: IndexedDocument) -> None:
        """Add *document*, replacing any previous version of its ``doc_id``."""
        self._validate(document)
        corpus = self._corpora.setdefault(document.index, _Corpus())
        corpus.remove(document.doc_id)
        corpus.add(_build_entry(document))

    def index_many(self, documents: Iterable[IndexedDocument]) -> None:
        """Convenience batch wrapper around :meth:`index`."""
        for document in documents:
            self.index(document)

    def remove(self, index: IndexName, doc_id: str) -> bool:
        """Delete ``doc_id`` from *index*; ``False`` when it was absent."""
        corpus = self._corpora.get(index)
        return corpus.remove(doc_id) if corpus is not None else False

    def get(self, index: IndexName, doc_id: str) -> IndexedDocument | None:
        """Return the stored document, or ``None``."""
        corpus = self._corpora.get(index)
        if corpus is None:
            return None
        entry = corpus.entries.get(doc_id)
        return entry.document if entry is not None else None

    def count(self, index: IndexName | None = None) -> int:
        """Document count for one index, or for all indexes when ``None``."""
        if index is not None:
            corpus = self._corpora.get(index)
            return corpus.doc_count if corpus is not None else 0
        return sum(corpus.doc_count for corpus in self._corpora.values())

    def clear(self, index: IndexName | None = None) -> None:
        """Drop one index (or everything when ``None``)."""
        if index is None:
            self._corpora.clear()
        else:
            self._corpora.pop(index, None)

    # -------------------------------------------------------------- querying

    @staticmethod
    def _build_query_stats(corpus: _Corpus, tokens: Sequence[str]) -> _QueryStats:
        """Derive per-query BM25 constants once, before scoring candidates.

        IDF depends only on each token's postings frequency and the corpus
        document count, so it is safe (and much cheaper) to evaluate it a
        single time per query rather than once per candidate document.
        """
        unique_tokens = tuple(dict.fromkeys(tokens))
        doc_count = corpus.doc_count
        idf: dict[str, float] = {}
        for token in unique_tokens:
            postings = corpus.postings.get(token)
            if postings:
                df = len(postings)
                idf[token] = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
        avg_length = corpus.avg_length or 1.0
        return _QueryStats(unique_tokens=unique_tokens, idf=idf, avg_length=avg_length)

    def _bm25(self, entry: _DocEntry, stats: _QueryStats) -> float:
        """BM25 over unique query tokens with optional per-field weights.

        All query-level constants (token order, IDF, average length) come
        from *stats*, so this method only touches per-document state.
        """
        if not entry.token_counts:
            return 0.0
        field_weights = self._field_weights
        length_norm = 1.0 - _BM25_B + _BM25_B * (entry.length / stats.avg_length)
        score = 0.0
        for token in stats.unique_tokens:
            token_idf = stats.idf.get(token)
            if token_idf is None:
                continue
            frequency = 0.0
            for name, counts in entry.field_counts.items():
                count = counts.get(token, 0)
                if count:
                    frequency += count * field_weights.get(name, 1.0)
            if frequency <= 0.0:
                continue
            saturation = frequency + _BM25_K1 * length_norm
            score += token_idf * (frequency * (_BM25_K1 + 1.0)) / saturation
        return score

    def search(self, query: SearchQuery) -> SearchResult:
        """Execute *query* against its index; see the module docstring for
        semantics, provenance guarantees, and the p95 latency target."""
        started = perf_counter()
        tokens = query_tokens(query)  # validates; [] for filter-only queries
        corpus = self._corpora.get(query.index)
        if corpus is None or corpus.doc_count == 0:
            took = (perf_counter() - started) * 1000.0
            return SearchResult(query=query, hits=(), total=0, took_ms=took)

        entries = corpus.entries
        phrase_fields: dict[str, tuple[str, ...]] = {}
        hybrid = query.retrieval_mode is RetrievalMode.HYBRID
        if not tokens:
            candidate_ids = list(entries)
        elif query.match_mode is MatchMode.PHRASE:
            for doc_id in _posting_intersection(corpus, tokens):
                fields = _phrase_fields(entries[doc_id], tokens)
                if fields:
                    phrase_fields[doc_id] = fields
            candidate_ids = list(phrase_fields)
        elif query.match_mode is MatchMode.EXACT:
            # Strict AND of exact tokens; hybrid never broadens this.
            candidate_ids = list(_posting_intersection(corpus, tokens))
        elif hybrid:
            # Documented trade-off: hybrid TERMS scans the (filtered)
            # corpus so semantically similar, lexically disjoint docs
            # can rank. See "optimization notes" in the module docstring.
            candidate_ids = list(entries)
        else:
            candidate_ids = list(_posting_union(corpus, tokens))

        since, until = query.since, query.until
        sources = frozenset(query.sources)
        entity_filter = frozenset(query.entity_ids)
        query_norm = " ".join(tokens)
        query_ngrams = (
            character_ngrams(query.text, _NGRAM_SIZE) if hybrid and tokens else frozenset()
        )
        # Query-level BM25 constants (IDF, unique token order, average length)
        # are derived once here instead of once per candidate document.
        stats = self._build_query_stats(corpus, tokens)

        prepared: list[_Prepared] = []
        for doc_id in candidate_ids:
            entry = entries[doc_id]
            if not _passes_filters(entry.document, since, until, sources, entity_filter):
                continue
            if not tokens:
                prepared.append(_Prepared(entry, 0.0, 0.0, 0.0, (), ()))
                continue
            matched_terms = tuple(
                token for token in dict.fromkeys(tokens) if token in entry.token_counts
            )
            if query.match_mode is MatchMode.PHRASE:
                matched_fields = phrase_fields[doc_id]
                lexical = self._bm25(entry, stats) + _PHRASE_BONUS
            else:
                matched_fields = _fields_with_terms(entry, tokens)
                lexical = self._bm25(entry, stats)
                if query.match_mode is MatchMode.EXACT and query_norm in entry.field_norms.values():
                    lexical += _FIELD_EXACT_BONUS
                if not hybrid and not matched_terms:
                    continue
            semantic = _semantic_similarity(tokens, query_ngrams, entry) if hybrid else 0.0
            if hybrid and lexical <= 0.0 and semantic <= 0.0:
                continue
            prepared.append(_Prepared(entry, lexical, semantic, 0.0, matched_fields, matched_terms))

        if hybrid and tokens:
            best_lexical = max((item.lexical for item in prepared), default=0.0)
            for item in prepared:
                normalized = item.lexical / best_lexical if best_lexical > 0.0 else 0.0
                item.final = self.lexical_weight * normalized + self.semantic_weight * item.semantic
        else:
            for item in prepared:
                item.final = item.lexical

        # Deterministic ranking: score desc, then doc_id asc. Only the top
        # ``query.limit`` survive, so select them with a bounded heap over
        # the same key a full sort would have used.
        top = heapq.nsmallest(query.limit, prepared, key=_ranking_key)
        hits = tuple(
            SearchHit(
                index=query.index,
                doc_id=item.entry.document.doc_id,
                score=item.final,
                breakdown=ScoreBreakdown(
                    lexical=item.lexical, semantic=item.semantic, final=item.final
                ),
                matched_fields=item.matched_fields,
                matched_terms=item.matched_terms,
                document=item.entry.document,
            )
            for item in top
        )
        took_ms = (perf_counter() - started) * 1000.0
        return SearchResult(query=query, hits=hits, total=len(prepared), took_ms=took_ms)
