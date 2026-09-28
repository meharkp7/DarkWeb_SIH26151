"""Candidate-pair features for entity resolution (Phase 09).

The implementation plan fixes nine features for every resolution baseline:

=== ============================= =========================================
#   feature                       signal source
=== ============================= =========================================
1   handle similarity             normalized Levenshtein similarity of handles
2   character n-gram similarity   cosine over char 3-5-gram counts of handles
3   text similarity               TF-IDF cosine over each alias's documents
4   temporal overlap              overlap of the aliases' activity windows
5   shared identifier             Jaccard of injected identifier sets
6   marketplace overlap           Jaccard of observed platforms
7   behavior similarity           cosine of 24-bin hour-of-day histograms
8   graph neighborhood similarity Jaccard from the Phase 08 graph store
9   source reliability            mean injected per-alias source reliability
=== ============================= =========================================

Every feature is deterministic, computed only from *observable* activity
(never from ground-truth actor identity), and clamped to ``[0, 1]`` so
learned models consume a uniform scale.  Features whose signal is
unavailable fall back to neutral, documented defaults:

* shared identifier   -> ``0.0`` (no shared identifiers observed)
* graph neighborhood  -> ``0.0`` (no graph supplied)
* source reliability  -> ``0.5`` (uninformative prior)
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime

from aegis.graph import InMemoryGraphStore, ensure_aware

#: Ordered feature names — index order matches :meth:`CandidatePairFeatures.as_vector`.
FEATURE_NAMES: tuple[str, ...] = (
    "handle_similarity",
    "char_ngram_similarity",
    "text_similarity",
    "temporal_overlap",
    "shared_identifier",
    "marketplace_overlap",
    "behavior_similarity",
    "graph_neighborhood_similarity",
    "source_reliability",
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_SEPARATOR_RE = re.compile(r"[\s._\-]+")
_NGRAM_SIZES = (3, 4, 5)


def _clamp01(value: float) -> float:
    """Clamp floating-point noise back into the ``[0, 1]`` interval."""
    return min(1.0, max(0.0, value))


# ------------------------------------------------------------ text helpers


def normalize_handle(handle: str) -> str:
    """Canonical form used for handle comparison.

    NFKC-fold (merging full-width/compatibility variants), case-fold,
    strip leading ``@``/``#`` sigils, and collapse runs of separators so
    ``@Ghost.Broker`` and ``ghost_broker`` normalize identically.
    """
    text = unicodedata.normalize("NFKC", handle).casefold().strip()
    text = text.lstrip("@#")
    return _SEPARATOR_RE.sub("_", text).strip("_")


def levenshtein(left: str, right: str) -> int:
    """Classic Levenshtein edit distance (two-row dynamic program)."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for row, char_left in enumerate(left, start=1):
        current = [row]
        for column, char_right in enumerate(right, start=1):
            substitution = previous[column - 1] + (0 if char_left == char_right else 1)
            current.append(min(previous[column] + 1, current[column - 1] + 1, substitution))
        previous = current
    return previous[-1]


def handle_similarity(left: str, right: str) -> float:
    """``1 - normalized edit distance`` over two handles, in ``[0, 1]``."""
    normalized_left = normalize_handle(left)
    normalized_right = normalize_handle(right)
    longest = max(len(normalized_left), len(normalized_right))
    if longest == 0:
        return 1.0
    return _clamp01(1.0 - levenshtein(normalized_left, normalized_right) / longest)


def char_ngram_counts(text: str) -> dict[str, float]:
    """Character n-gram counts (n in 3..5) over normalized text."""
    normalized = normalize_handle(text)
    counts: dict[str, float] = {}
    for size in _NGRAM_SIZES:
        for index in range(max(0, len(normalized) - size + 1)):
            gram = normalized[index : index + size]
            counts[gram] = counts.get(gram, 0.0) + 1.0
    return counts


def cosine_counts[K](left: Mapping[K, float], right: Mapping[K, float]) -> float:
    """Cosine similarity between two sparse count/weight maps, in ``[0, 1]``."""
    if not left or not right:
        return 0.0
    small, large = (left, right) if len(left) <= len(right) else (right, left)
    dot = sum(value * large.get(key, 0.0) for key, value in small.items())
    norm_left = math.sqrt(sum(value * value for value in left.values()))
    norm_right = math.sqrt(sum(value * value for value in right.values()))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return _clamp01(dot / (norm_left * norm_right))


def hour_histogram(timestamps: Sequence[datetime]) -> tuple[int, ...]:
    """24-bin hour-of-day histogram over timezone-aware timestamps."""
    bins = [0] * 24
    for timestamp in timestamps:
        bins[timestamp.hour] += 1
    return tuple(bins)


# --------------------------------------------------------------- TF-IDF


@dataclass(frozen=True)
class TfidfModel:
    """Deterministic bag-of-words TF-IDF model (unigrams + bigrams).

    Fitted on *training* documents only; :meth:`vectorize` ignores
    out-of-vocabulary terms and returns an L2-normalized sparse vector
    keyed by vocabulary index so pairwise text similarity is a dot
    product.
    """

    vocabulary: Mapping[str, int]
    idf: tuple[float, ...]
    document_count: int

    @classmethod
    def fit(
        cls,
        documents: Sequence[str],
        *,
        min_df: int = 2,
        max_features: int = 8000,
    ) -> TfidfModel:
        """Fit document frequencies over ``documents`` (deterministically ordered)."""
        if min_df < 1:
            raise ValueError("min_df must be >= 1")
        document_frequency: dict[str, int] = {}
        for document in documents:
            for term in set(cls.tokens(document)):
                document_frequency[term] = document_frequency.get(term, 0) + 1

        eligible = [
            (term, frequency)
            for term, frequency in document_frequency.items()
            if frequency >= min_df
        ]
        # deterministic order: most frequent first, ties broken alphabetically
        eligible.sort(key=lambda item: (-item[1], item[0]))
        kept = eligible[:max_features]
        vocabulary = {term: index for index, (term, _) in enumerate(kept)}
        total = len(documents)
        idf = tuple(
            math.log((1.0 + total) / (1.0 + document_frequency[term])) + 1.0 for term, _ in kept
        )
        return cls(vocabulary=vocabulary, idf=idf, document_count=total)

    @staticmethod
    def tokens(document: str) -> list[str]:
        """Word unigrams plus adjacent-word bigrams, case-folded."""
        words = _WORD_RE.findall(document.casefold())
        bigrams = [f"{left} {right}" for left, right in zip(words, words[1:], strict=False)]
        return words + bigrams

    def vectorize(self, document: str) -> dict[int, float]:
        """L2-normalized TF-IDF vector of ``document`` over the fitted vocabulary."""
        term_frequency: dict[int, float] = {}
        for term in self.tokens(document):
            index = self.vocabulary.get(term)
            if index is not None:
                term_frequency[index] = term_frequency.get(index, 0.0) + 1.0
        if not term_frequency:
            return {}
        weights = {
            index: frequency * self.idf[index] for index, frequency in term_frequency.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in weights.values()))
        if norm == 0.0:
            return {}
        return {index: weight / norm for index, weight in weights.items()}


# ------------------------------------------------------------- activities


@dataclass(frozen=True)
class AliasActivity:
    """Observable activity summary for one candidate alias.

    Carries *only* what an analyst could observe — handle, platforms,
    activity window, authored documents and their timestamps — never the
    ground-truth actor identity behind the alias.
    """

    alias_id: str
    handle: str
    platforms: frozenset[str]
    first_seen: datetime
    last_seen: datetime
    documents: tuple[str, ...]
    timestamps: tuple[datetime, ...]

    def __post_init__(self) -> None:
        if not self.alias_id:
            raise ValueError("alias_id must be non-empty")
        first = ensure_aware(self.first_seen, field_name="first_seen")
        last = ensure_aware(self.last_seen, field_name="last_seen")
        if last < first:
            raise ValueError("last_seen must not precede first_seen")
        if len(self.documents) != len(self.timestamps):
            raise ValueError("documents and timestamps must align")
        for timestamp in self.timestamps:
            ensure_aware(timestamp, field_name="timestamps")
        object.__setattr__(self, "first_seen", first)
        object.__setattr__(self, "last_seen", last)
        object.__setattr__(self, "timestamps", tuple(self.timestamps))


# ------------------------------------------------------------- extraction


@dataclass(frozen=True)
class CandidatePairFeatures:
    """The nine plan features for one candidate pair, each in ``[0, 1]``."""

    handle_similarity: float
    char_ngram_similarity: float
    text_similarity: float
    temporal_overlap: float
    shared_identifier: float
    marketplace_overlap: float
    behavior_similarity: float
    graph_neighborhood_similarity: float
    source_reliability: float

    def as_vector(self) -> tuple[float, ...]:
        """Feature vector in :data:`FEATURE_NAMES` order (what models consume)."""
        return tuple(getattr(self, name) for name in FEATURE_NAMES)

    @classmethod
    def feature_names(cls) -> tuple[str, ...]:
        """Declared field order — kept in lockstep with :data:`FEATURE_NAMES`."""
        return tuple(field.name for field in fields(cls))


@dataclass(frozen=True)
class _Prepared:
    """Per-alias precomputation shared across every pair involving it."""

    handle: str
    ngrams: Mapping[str, float]
    tfidf: Mapping[int, float]
    hours: tuple[int, ...]


class PairFeatureExtractor:
    """Extracts the nine plan features for candidate alias pairs.

    Parameters
    ----------
    tfidf:
        A :class:`TfidfModel` fitted on *training* documents (caller
        keeps train/test separation honest).
    graph:
        Optional Phase 08 graph store.  Every alias must already be
        registered as a node; missing nodes raise ``MissingNodeError``
        rather than silently defaulting.
    shared_identifiers:
        Optional ``alias_id -> identifier set`` mapping (handles,
        wallets, PGP fingerprints...).  Missing aliases contribute an
        empty set.
    source_reliability:
        Optional ``alias_id -> [0, 1]`` reliability.  Missing aliases
        fall back to ``default_reliability``.
    """

    def __init__(
        self,
        *,
        tfidf: TfidfModel,
        graph: InMemoryGraphStore | None = None,
        shared_identifiers: Mapping[str, frozenset[str]] | None = None,
        source_reliability: Mapping[str, float] | None = None,
        default_reliability: float = 0.5,
    ) -> None:
        if not 0.0 <= default_reliability <= 1.0:
            raise ValueError("default_reliability must be within [0, 1]")
        for alias_id, reliability in (source_reliability or {}).items():
            if not 0.0 <= reliability <= 1.0:
                raise ValueError(f"source reliability for {alias_id!r} outside [0, 1]")
        self._tfidf = tfidf
        self._graph = graph
        self._shared = dict(shared_identifiers or {})
        self._reliability = dict(source_reliability or {})
        self._default_reliability = default_reliability
        self._cache: dict[str, _Prepared] = {}

    def _prepare(self, activity: AliasActivity) -> _Prepared:
        prepared = self._cache.get(activity.alias_id)
        if prepared is None:
            prepared = _Prepared(
                handle=normalize_handle(activity.handle),
                ngrams=char_ngram_counts(activity.handle),
                tfidf=self._tfidf.vectorize("\n".join(activity.documents)),
                hours=hour_histogram(activity.timestamps),
            )
            self._cache[activity.alias_id] = prepared
        return prepared

    def extract(self, left: AliasActivity, right: AliasActivity) -> CandidatePairFeatures:
        """Compute the nine features for one candidate pair."""
        prepared_left = self._prepare(left)
        prepared_right = self._prepare(right)

        # 1 — handle similarity (normalized edit distance)
        longest = max(len(prepared_left.handle), len(prepared_right.handle))
        if longest == 0:
            edit_similarity = 1.0
        else:
            distance = levenshtein(prepared_left.handle, prepared_right.handle)
            edit_similarity = _clamp01(1.0 - distance / longest)

        # 4 — temporal overlap of activity windows
        intersection_start = max(left.first_seen, right.first_seen)
        intersection_end = min(left.last_seen, right.last_seen)
        intersection = max(0.0, (intersection_end - intersection_start).total_seconds())
        union_start = min(left.first_seen, right.first_seen)
        union_end = max(left.last_seen, right.last_seen)
        union_seconds = max(0.0, (union_end - union_start).total_seconds())
        if union_seconds == 0.0:
            temporal_overlap = 1.0  # identical point windows fully coincide
        else:
            temporal_overlap = _clamp01(intersection / union_seconds)

        # 5 — shared identifiers (Jaccard; empty on both sides -> 0.0)
        identifiers_left = self._shared.get(left.alias_id, frozenset())
        identifiers_right = self._shared.get(right.alias_id, frozenset())
        identifier_union = identifiers_left | identifiers_right
        if identifier_union:
            shared_identifier = len(identifiers_left & identifiers_right) / len(identifier_union)
        else:
            shared_identifier = 0.0

        # 6 — marketplace overlap (Jaccard of platforms)
        platform_union = left.platforms | right.platforms
        if platform_union:
            marketplace_overlap = len(left.platforms & right.platforms) / len(platform_union)
        else:
            marketplace_overlap = 0.0

        # 7 — behavior similarity (hour-of-day cosine; no activity -> 0.0)
        behavior_similarity = cosine_hours(prepared_left.hours, prepared_right.hours)

        # 8 — graph neighborhood similarity (Phase 08 store)
        if self._graph is not None:
            graph_similarity = self._graph.neighborhood_similarity(
                left.alias_id, right.alias_id
            ).jaccard
        else:
            graph_similarity = 0.0

        # 9 — source reliability (mean of both sides)
        source_reliability = (
            self._reliability.get(left.alias_id, self._default_reliability)
            + self._reliability.get(right.alias_id, self._default_reliability)
        ) / 2.0

        return CandidatePairFeatures(
            handle_similarity=edit_similarity,
            char_ngram_similarity=cosine_counts(prepared_left.ngrams, prepared_right.ngrams),
            text_similarity=cosine_counts(prepared_left.tfidf, prepared_right.tfidf),
            temporal_overlap=temporal_overlap,
            shared_identifier=_clamp01(shared_identifier),
            marketplace_overlap=_clamp01(marketplace_overlap),
            behavior_similarity=behavior_similarity,
            graph_neighborhood_similarity=_clamp01(graph_similarity),
            source_reliability=_clamp01(source_reliability),
        )


def cosine_hours(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    """Cosine similarity of two 24-bin histograms; zero activity -> 0.0."""
    if not any(left) or not any(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return _clamp01(dot / (norm_left * norm_right))


def stable_hash_int(value: str, *, seed: int = 0) -> int:
    """Deterministic 64-bit hash — used for seeded splits, never for security."""
    material = f"{seed}|{value}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def validate_feature_registry() -> None:
    """Guard against field/order drift between dataclass and feature registry."""
    declared = CandidatePairFeatures.feature_names()
    if declared != FEATURE_NAMES:
        raise ValueError(
            f"CandidatePairFeatures fields out of sync with FEATURE_NAMES: "
            f"{declared!r} != {FEATURE_NAMES!r}"
        )
