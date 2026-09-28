"""Pairwise identity verification model (Phase 11, step 4).

Turns two texts into a similarity feature vector (eight interpretable
signals spanning n-gram overlap, template-centered overlap, idiolect
lexicon overlap, embedding similarity, classical stylometry, and
shingle Jaccard) and trains a **logistic regression in-process** on
those features with plain gradient descent — no ML dependencies, fully
deterministic under a fixed seed, per the phase policy.

The training data is (features, label) pairs supplied by the caller
(identity links confirmed elsewhere); see :mod:`aegis.stylometry.evaluation`
for how the synthetic corpus is split into train/test pairs for the
benchmark.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Self

from aegis.normalization.fingerprints import jaccard_sets, shingles
from aegis.stylometry.embeddings import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    embed_cosine,
)
from aegis.stylometry.features import StylometricFeatures, stylometric_similarity
from aegis.stylometry.ngrams import (
    NGramConfig,
    NGramVectorizer,
    cosine_similarity,
    tokenize_words,
)

#: Ordered names of the eight similarity features.
FEATURE_NAMES: tuple[str, ...] = (
    "char_tfidf_cosine",
    "word_tfidf_cosine",
    "centered_tfidf_cosine",
    "distinctive_token_jaccard",
    "embedding_cosine",
    "stylometric_similarity",
    "shingle_jaccard",
    "token_jaccard",
)

DEFAULT_SEED = 26151

#: Hard limit on standardized feature values (out-of-distribution guard).
MAX_ZSCORE = 4.0


@dataclass(frozen=True)
class PairFeatures:
    """Similarity features for one (left, right) text pair."""

    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.values) != len(FEATURE_NAMES):
            raise ValueError(
                f"expected {len(FEATURE_NAMES)} features {FEATURE_NAMES}, got {len(self.values)}"
            )
        for name, value in zip(FEATURE_NAMES, self.values, strict=True):
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"feature {name} outside [-1, 1]: {value}")

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, float]) -> PairFeatures:
        """Build from a name -> value mapping (missing names are an error)."""
        return cls(tuple(mapping[name] for name in FEATURE_NAMES))


@dataclass(frozen=True)
class _DocumentSummary:
    """Everything precomputable once per document (not per pair)."""

    char_vector: tuple[float, ...]
    word_vector: tuple[float, ...]
    centered_char_vector: tuple[float, ...]
    embedding: tuple[float, ...]
    stylometric: StylometricFeatures
    tokens: frozenset[str]
    distinctive_tokens: frozenset[str]
    shingle_set: frozenset[str]


class PairFeatureExtractor:
    """Computes the eight verification features for arbitrary text pairs.

    Per-document state (TF-IDF vectors, embedding, stylometric
    features, shingle/token sets) is computed once and cached, so
    scoring *n* pairs costs roughly *n* cheap dot products after an
    initial pass. :meth:`fit` must be called first: the TF-IDF
    vocabularies, the corpus mean vector, and the distinctive-token
    vocabulary are all learned from the training texts, which keeps
    evaluation leakage-free.

    Two features deserve a note:

    ``centered_tfidf_cosine``
        TF-IDF vectors minus their corpus mean before the cosine. The
        shared boilerplate present in nearly every document cancels
        out, so the score is driven by *deviations* (idiosyncratic
        markers) rather than by the common template.
    ``distinctive_token_jaccard``
        Jaccard restricted to tokens seen in at most
        ``distinctive_max_df`` of the training documents — a
        corpus-derived idiolect lexicon. Common vocabulary and rare
        content words drop out; genuinely characteristic markers stay.
        Two documents with *no* distinctive tokens score 0.0 (absence
        of evidence, not evidence of sameness).
    """

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        config: NGramConfig | None = None,
        distinctive_max_df: float = 0.4,
    ) -> None:
        if not 0.0 < distinctive_max_df <= 1.0:
            raise ValueError(f"distinctive_max_df must be within (0, 1], got {distinctive_max_df}")
        base = config if config is not None else NGramConfig()
        self.char_vectorizer = NGramVectorizer(
            NGramConfig(
                char_min=base.char_min,
                char_max=base.char_max,
                lowercase=base.lowercase,
                max_features=base.max_features,
                include_chars=True,
                include_words=False,
                exclude_numeric=base.exclude_numeric,
            )
        )
        self.word_vectorizer = NGramVectorizer(
            NGramConfig(
                word_min=base.word_min,
                word_max=base.word_max,
                lowercase=base.lowercase,
                max_features=base.max_features,
                include_chars=False,
                include_words=True,
                exclude_numeric=base.exclude_numeric,
            )
        )
        self.embedding_provider: EmbeddingProvider = (
            embedding_provider if embedding_provider is not None else HashingEmbeddingProvider()
        )
        self.distinctive_max_df = distinctive_max_df
        self._cache: dict[str, _DocumentSummary] = {}
        self._mean_char_vector: tuple[float, ...] = ()
        self._distinctive_tokens: frozenset[str] = frozenset()

    @property
    def fitted(self) -> bool:
        return self.char_vectorizer.fitted and self.word_vectorizer.fitted

    @property
    def distinctive_vocabulary(self) -> frozenset[str]:
        """The corpus-derived idiolect lexicon learned by :meth:`fit`."""
        return self._distinctive_tokens

    def fit(self, texts: Iterable[str]) -> Self:
        """Learn the TF-IDF vocabularies, mean vector, and idiolect lexicon.

        The document cache is cleared because cached TF-IDF vectors
        depend on the fitted vocabularies.
        """
        materialized = list(texts)
        self.char_vectorizer.fit(materialized)
        self.word_vectorizer.fit(materialized)

        vectors = [self.char_vectorizer.transform(text) for text in materialized]
        if vectors:
            width = len(vectors[0])
            self._mean_char_vector = tuple(
                sum(vector[column] for vector in vectors) / len(vectors) for column in range(width)
            )
        else:  # pragma: no cover - defensive: empty training set
            self._mean_char_vector = ()

        document_frequency: Counter[str] = Counter()
        for text in materialized:
            for token in set(tokenize_words(text, exclude_numeric=True)):
                document_frequency[token] += 1
        cutoff = max(2, int(self.distinctive_max_df * len(materialized)))
        self._distinctive_tokens = frozenset(
            token for token, count in document_frequency.items() if count <= cutoff
        )

        self._cache.clear()
        return self

    def _summary(self, text: str) -> _DocumentSummary:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        char_vector = self.char_vectorizer.transform(text)
        tokens = frozenset(tokenize_words(text, exclude_numeric=True))
        if self._mean_char_vector and len(self._mean_char_vector) == len(char_vector):
            centered = tuple(
                value - mean
                for value, mean in zip(char_vector, self._mean_char_vector, strict=True)
            )
        else:  # pragma: no cover - defensive: unfitted mean
            centered = ()
        summary = _DocumentSummary(
            char_vector=char_vector,
            word_vector=self.word_vectorizer.transform(text),
            centered_char_vector=centered,
            embedding=self.embedding_provider.embed(text),
            stylometric=StylometricFeatures.from_text(text),
            tokens=tokens,
            distinctive_tokens=tokens & self._distinctive_tokens,
            shingle_set=frozenset(shingles(text)),
        )
        self._cache[text] = summary
        return summary

    def features(self, left_text: str, right_text: str) -> PairFeatures:
        """Similarity features for one pair of texts.

        Raises:
            RuntimeError: If :meth:`fit` has not been called.
        """
        if not self.fitted:
            raise RuntimeError("PairFeatureExtractor.fit() must be called before features()")
        left = self._summary(left_text)
        right = self._summary(right_text)
        values = (
            _safe_cosine_vectors(left.char_vector, right.char_vector),
            _safe_cosine_vectors(left.word_vector, right.word_vector),
            _safe_cosine_vectors(left.centered_char_vector, right.centered_char_vector),
            _distinctive_jaccard(left.distinctive_tokens, right.distinctive_tokens),
            embed_cosine(left.embedding, right.embedding),
            stylometric_similarity(left.stylometric, right.stylometric),
            jaccard_sets(left.shingle_set, right.shingle_set),
            jaccard_sets(left.tokens, right.tokens),
        )
        return PairFeatures(tuple(_clamp(value) for value in values))


def _distinctive_jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard over distinctive tokens; 0.0 when either side has none."""
    if not left or not right:
        return 0.0
    return jaccard_sets(left, right)


def _safe_cosine_vectors(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine clamped into [-1, 1] (guards floating-point overshoot)."""
    return _clamp(cosine_similarity(left, right))


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def sigmoid(value: float) -> float:
    """Numerically stable logistic function."""
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


@dataclass(frozen=True)
class Standardizer:
    """Per-feature z-score standardization fitted on training rows."""

    means: tuple[float, ...]
    scales: tuple[float, ...]

    @classmethod
    def fit(cls, rows: Sequence[Sequence[float]]) -> Standardizer:
        """Compute per-column mean and (clamped) standard deviation."""
        if not rows or not rows[0]:
            raise ValueError("cannot standardize an empty feature matrix")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("ragged feature matrix")
        means = [sum(row[column] for row in rows) / len(rows) for column in range(width)]
        scales: list[float] = []
        for column in range(width):
            mean = means[column]
            variance = sum((row[column] - mean) ** 2 for row in rows) / len(rows)
            scales.append(max(math.sqrt(variance), 1e-9))
        return cls(means=tuple(means), scales=tuple(scales))

    def apply(self, row: Sequence[float]) -> tuple[float, ...]:
        """Standardize one row; length mismatch raises ``ValueError``.

        The z-scores are clamped to :data:`MAX_ZSCORE`: transformed or
        otherwise out-of-distribution inputs can sit many standard
        deviations away from the training mean, and unclamped values
        would let a single feature swamp the logit.
        """
        if len(row) != len(self.means):
            raise ValueError(f"expected {len(self.means)} features, got {len(row)}")
        return tuple(
            max(-MAX_ZSCORE, min(MAX_ZSCORE, (value - mean) / scale))
            for value, mean, scale in zip(row, self.means, self.scales, strict=True)
        )


@dataclass(frozen=True)
class VerificationModel:
    """Logistic-regression pairwise verifier trained by gradient descent.

    Deterministic by construction: weights start at zero and the only
    randomness is the seeded per-epoch shuffle, so the same training
    rows and seed always produce the identical model.
    """

    standardizer: Standardizer
    weights: tuple[float, ...]
    bias: float
    threshold: float = 0.5

    feature_names: ClassVar[tuple[str, ...]] = FEATURE_NAMES

    @property
    def feature_count(self) -> int:
        return len(self.weights)

    def predict_proba(self, values: Sequence[float]) -> float:
        """Probability that the pair is the same author."""
        standardized = self.standardizer.apply(values)
        logit = self.bias + sum(
            weight * value for weight, value in zip(self.weights, standardized, strict=True)
        )
        return sigmoid(logit)

    def predict(self, values: Sequence[float], *, threshold: float | None = None) -> bool:
        """Classify the pair at ``threshold`` (defaults to the model's)."""
        cutoff = self.threshold if threshold is None else threshold
        return self.predict_proba(values) >= cutoff

    @classmethod
    def train(
        cls,
        rows: Sequence[Sequence[float]],
        labels: Sequence[int],
        *,
        epochs: int = 300,
        learning_rate: float = 0.1,
        l2: float = 1e-3,
        seed: int = DEFAULT_SEED,
        threshold: float = 0.5,
        non_negative_weights: bool = True,
    ) -> VerificationModel:
        """Fit by seeded stochastic gradient descent on logistic loss.

        Args:
            rows: Feature rows (see :data:`FEATURE_NAMES`).
            labels: ``1`` for same-author, ``0`` otherwise.
            epochs: Passes over the (shuffled) training set.
            learning_rate: Step size.
            l2: L2 penalty on the weights (keeps them bounded).
            seed: Shuffle seed — the only source of randomness.
            threshold: Default decision cutoff.
            non_negative_weights: Project the weights onto the
                non-negative orthant after every step (projected GD).
                Every feature is a *similarity*, so more evidence can
                never mean "different author"; unconstrained fits let
                multicollinearity flip a weak feature's sign, which
                then misbehaves catastrophically on adversarially
                transformed inputs. Defaults to ``True``.

        Raises:
            ValueError: On empty/ragged input or a single-class label
                vector (training would be meaningless).
        """
        if not rows or len(rows) != len(labels):
            raise ValueError("rows and labels must be non-empty and the same length")
        if len({*labels}) < 2:
            raise ValueError("training requires both positive and negative labels")
        if epochs < 1 or learning_rate <= 0.0:
            raise ValueError("epochs must be >= 1 and learning_rate must be > 0")

        standardizer = Standardizer.fit(rows)
        standardized = [standardizer.apply(row) for row in rows]
        width = len(rows[0])
        weights = [0.0] * width
        bias = 0.0

        rng = random.Random(seed)
        indices = list(range(len(standardized)))
        for _ in range(epochs):
            rng.shuffle(indices)
            for index in indices:
                row = standardized[index]
                label = float(labels[index])
                logit = bias + sum(
                    weight * value for weight, value in zip(weights, row, strict=True)
                )
                error = sigmoid(logit) - label
                for position, value in enumerate(row):
                    gradient = error * value + l2 * weights[position]
                    weights[position] -= learning_rate * gradient
                    if non_negative_weights:
                        weights[position] = max(0.0, weights[position])
                bias -= learning_rate * error

        return cls(
            standardizer=standardizer,
            weights=tuple(weights),
            bias=bias,
            threshold=threshold,
        )
