"""Transformer-style embeddings without ML dependencies (Phase 11, step 3).

The plan requires embedding features but the project forbids new ML
dependencies, so this module defines an :class:`EmbeddingProvider`
protocol with two backends:

``HashingEmbeddingProvider`` (default)
    A deterministic, pure-Python feature-hashing embedding over word,
    bigram, and character 4-gram cues. It is documented explicitly as
    the *baseline stand-in* for a transformer: it produces the same
    kind of artifact (a fixed-length L2-normalized vector supporting
    cosine similarity) without pretraining, so every downstream stage
    can be built and evaluated today.

``SentenceTransformerEmbeddingProvider`` (optional hook)
    Mirrors the lazy-driver pattern of :mod:`aegis.graph.neo4j`: the
    heavyweight library is imported only on first use and only if the
    operator installed it, raising :class:`EmbeddingBackendUnavailable`
    otherwise. This is the seam where a real sentence-transformer can
    be plugged in later without touching any other module.
"""

from __future__ import annotations

import hashlib
import importlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aegis.stylometry.ngrams import (
    DEFAULT_EMBEDDING_SEED,
    _strip_digits,
    word_ngrams,
)


class EmbeddingBackendUnavailable(RuntimeError):
    """Raised when an optional embedding backend cannot be loaded."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Anything that maps text to a fixed-length dense vector."""

    @property
    def name(self) -> str:
        """Stable backend identifier (e.g. ``"hashing-baseline"``)."""
        ...

    @property
    def dimensions(self) -> int:
        """Length of every vector this provider returns."""
        ...

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed *text*; the result has length :attr:`dimensions`."""
        ...


def embed_cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two embedding vectors (0.0 on any mismatch)."""
    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        norm_left += a * a
        norm_right += b * b
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / math.sqrt(norm_left * norm_right)


def embed_many(provider: EmbeddingProvider, texts: Sequence[str]) -> list[tuple[float, ...]]:
    """Embed every text with *provider* (protocol-level ``embed_many``)."""
    return [provider.embed(text) for text in texts]


@dataclass(frozen=True)
class HashingEmbeddingProvider:
    """Deterministic feature-hashing embedding — the baseline stand-in.

    Features are word unigrams, word bigrams, and character 4-grams
    (case-folded). Each feature hashes to a bucket and a sign with
    blake2b keyed by ``seed``; weights are ``1 + log(count)`` and the
    result is L2-normalized, so cosine similarity behaves like a
    signed, length-normalized n-gram overlap. Because hashing removes
    the need for a vocabulary, the provider is stable across corpora —
    exactly what cross-marketplace evaluation needs.

    This is *not* a transformer and does not claim contextual
    semantics; it exists so the pipeline, its metrics, and its
    interfaces match what a real embedding backend would produce.
    """

    dimensions: int = 256
    seed: int = DEFAULT_EMBEDDING_SEED

    def __post_init__(self) -> None:
        if self.dimensions < 1:
            raise ValueError(f"dimensions must be >= 1, got {self.dimensions}")

    @property
    def name(self) -> str:
        return "hashing-baseline"

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed *text* as an L2-normalized hashed vector."""
        if not text:
            return tuple(0.0 for _ in range(self.dimensions))
        features: dict[str, int] = {}
        for gram, count in word_ngrams(text, 1, exclude_numeric=True).items():
            features[f"w1:{gram}"] = count
        for gram, count in word_ngrams(text, 2, exclude_numeric=True).items():
            features[f"w2:{gram}"] = count
        if len(text) >= 4:
            lowered = _strip_digits(text.lower())
            for index in range(len(lowered) - 3):
                gram = lowered[index : index + 4]
                features[f"c4:{gram}"] = features.get(f"c4:{gram}", 0) + 1
        if not features:
            features["w1:<empty>"] = 1

        vector = [0.0] * self.dimensions
        for feature, count in features.items():
            material = f"{self.seed}|{feature}".encode()
            digest = hashlib.blake2b(material, digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign * (1.0 + math.log(count))

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(value / norm for value in vector)

    def embed_many(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Embed every text (fast path sharing no per-call state)."""
        return [self.embed(text) for text in texts]


class SentenceTransformerEmbeddingProvider:
    """Lazy optional backend for a real sentence-transformer.

    Follows the lazy-import pattern of :class:`aegis.graph.neo4j`'s
    driver: nothing outside the standard library is imported until
    :meth:`embed` (or :attr:`dimensions`) is first used, and the
    missing optional dependency surfaces as a single, actionable
    exception instead of an import-time crash. The model itself is
    loaded once and cached.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: object | None = None
        self._dimensions: int | None = None

    @property
    def name(self) -> str:
        return f"sentence-transformer:{self.model_name}"

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            self._load()
        if self._dimensions is None:
            raise EmbeddingBackendUnavailable("backend did not report its embedding size")
        return self._dimensions

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            module: object = importlib.import_module("sentence_transformers")
        except ImportError as exc:
            raise EmbeddingBackendUnavailable(
                "sentence-transformers is not installed; install it to use "
                "SentenceTransformerEmbeddingProvider, or use "
                "HashingEmbeddingProvider (the pure-Python baseline)."
            ) from exc
        factory = getattr(module, "SentenceTransformer", None)
        if factory is None:
            raise EmbeddingBackendUnavailable(
                "sentence_transformers module has no SentenceTransformer entry point"
            )
        self._model = factory(self.model_name)
        raw_dimensions = getattr(self._model, "get_sentence_embedding_dimension", lambda: None)()
        self._dimensions = int(raw_dimensions) if raw_dimensions else None

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed *text* with the lazily loaded model."""
        if self._model is None:
            self._load()
        if self._model is None:  # pragma: no cover - _load always sets or raises
            raise EmbeddingBackendUnavailable("model failed to load")
        encode = getattr(self._model, "encode", None)
        if encode is None:
            raise EmbeddingBackendUnavailable("loaded model does not expose encode()")
        vector: Sequence[float] = encode(text)
        result = tuple(float(value) for value in vector)
        if self._dimensions is None:
            self._dimensions = len(result)
        return result

    def embed_many(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Embed every text with the lazily loaded model."""
        return [self.embed(text) for text in texts]
