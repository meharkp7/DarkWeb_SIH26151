"""Character and word n-grams (Phase 11, step 1).

Provides the tokenization primitives and the two vectorization
strategies used by the stylometry pipeline:

``NGramVectorizer``
    Vocabulary-based term-frequency / TF-IDF vectors with a
    deterministic vocabulary (frequency first, lexicographic
    tie-break), suitable when the analysis corpus is available up
    front.

``hashed_ngram_vector``
    Dependency-free feature hashing (the "hashing trick") with a
    blake2b-derived bucket and sign, suitable when no corpus-level
    vocabulary should be learned (cross-domain evaluation, streaming).

All functions are pure, deterministic, and dependency-free.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Self

_WORD_RE = re.compile(r"\w+", re.UNICODE)

DEFAULT_EMBEDDING_SEED = 26151


def tokenize_words(
    text: str, *, lowercase: bool = True, exclude_numeric: bool = False
) -> list[str]:
    """Split *text* into word tokens (Unicode word characters).

    Args:
        text: Raw input text.
        lowercase: When true (default) every token is case-folded.
        exclude_numeric: Drop tokens containing digits (per-post serial
            numbers are content, not style, and their document
            frequency is 1, which lets them dominate TF-IDF norms).

    Returns:
        The list of tokens, in order of appearance.
    """
    words = _WORD_RE.findall(text)
    if exclude_numeric:
        words = [word for word in words if not any(char.isdigit() for char in word)]
    return [word.lower() for word in words] if lowercase else words


def _strip_digits(text: str) -> str:
    """Replace digits with spaces so character n-grams cannot span them."""
    return "".join(" " if char.isdigit() else char for char in text)


def character_ngrams(
    text: str, n: int, *, lowercase: bool = True, exclude_numeric: bool = False
) -> Counter[str]:
    """Contiguous character *n*-grams of *text* as a multiset.

    Character n-grams capture orthographic habits (spelling of
    separators, emoticon shapes, abbreviation forms) that survive light
    rewriting, which makes them the classical stylometric workhorse.

    Args:
        text: Raw input text.
        n: Gram length in characters; must be >= 1.
        lowercase: Case-fold the text before slicing.
        exclude_numeric: Replace digits with spaces before slicing so
            serial numbers contribute no distinctive grams.

    Raises:
        ValueError: If ``n < 1``.
    """
    if n < 1:
        raise ValueError(f"n-gram size must be >= 1, got {n}")
    body = text.lower() if lowercase else text
    if exclude_numeric:
        body = _strip_digits(body)
    if len(body) < n:
        return Counter({body: 1}) if body else Counter()
    return Counter(body[index : index + n] for index in range(len(body) - n + 1))


def word_ngrams(
    text: str, n: int, *, lowercase: bool = True, exclude_numeric: bool = False
) -> Counter[str]:
    """Word *n*-grams of *text* as a multiset (joined with single spaces).

    Args:
        text: Raw input text.
        n: Gram length in words; must be >= 1.
        lowercase: Case-fold tokens before composing grams.
        exclude_numeric: Skip tokens containing digits.
    """
    if n < 1:
        raise ValueError(f"n-gram size must be >= 1, got {n}")
    tokens = tokenize_words(text, lowercase=lowercase, exclude_numeric=exclude_numeric)
    if len(tokens) < n:
        return Counter({" ".join(tokens): 1}) if tokens else Counter()
    return Counter(" ".join(tokens[index : index + n]) for index in range(len(tokens) - n + 1))


def counter_cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Cosine similarity between two sparse count/weight maps.

    Returns 0.0 when either side has no mass or the vectors are
    orthogonal.
    """
    if not left or not right:
        return 0.0
    dot = 0.0
    small, large = (left, right) if len(left) <= len(right) else (right, left)
    for key, value in small.items():
        other = large.get(key)
        if other is not None:
            dot += value * other
    if dot == 0.0:
        return 0.0
    norm_left = math.sqrt(sum(value * value for value in left.values()))
    norm_right = math.sqrt(sum(value * value for value in right.values()))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two dense vectors of equal length.

    Returns 0.0 for a length mismatch or a zero vector, so callers can
    compare untrusted vectors without exceptions.
    """
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


def _feature_digest(feature: str, seed: int) -> bytes:
    material = f"{seed}|{feature}".encode()
    return hashlib.blake2b(material, digest_size=8).digest()


def hashed_ngram_vector(
    text: str,
    dimensions: int = 256,
    *,
    seed: int = DEFAULT_EMBEDDING_SEED,
    char_range: tuple[int, int] = (3, 5),
    word_range: tuple[int, int] = (1, 2),
    lowercase: bool = True,
    exclude_numeric: bool = True,
) -> tuple[float, ...]:
    """Deterministic feature-hashed n-gram vector (the hashing trick).

    Every word and character n-gram is hashed with blake2b into one of
    *dimensions* buckets together with a +/- sign, weighted by
    ``1 + log(count)``, then L2-normalized. Two texts therefore always
    map to the same coordinate system without a fitted vocabulary, and
    cosine similarity on the result estimates weighted n-gram overlap
    with the shared-template mass largely cancelling out.

    Args:
        text: Raw input text.
        dimensions: Vector length; must be >= 1.
        seed: Hash seed; changing it re-randomizes buckets.
        char_range: Inclusive (min, max) character n-gram lengths.
        word_range: Inclusive (min, max) word n-gram lengths.
        lowercase: Case-fold before counting (default true, which makes
            the vector robust to case-change transforms).
        exclude_numeric: Skip numeric tokens and character grams
            (serial numbers are content, not style).

    Raises:
        ValueError: If any range or *dimensions* is invalid.
    """
    if dimensions < 1:
        raise ValueError(f"dimensions must be >= 1, got {dimensions}")
    if char_range[0] < 1 or word_range[0] < 1 or char_range[1] < char_range[0]:
        raise ValueError(f"invalid n-gram ranges: char={char_range} word={word_range}")

    counts: Counter[str] = Counter()
    counts.update(
        word_ngrams(text, word_range[0], lowercase=lowercase, exclude_numeric=exclude_numeric)
    )
    for size in range(word_range[0] + 1, word_range[1] + 1):
        counts.update(word_ngrams(text, size, lowercase=lowercase, exclude_numeric=exclude_numeric))
    for size in range(char_range[0], char_range[1] + 1):
        counts.update(
            character_ngrams(text, size, lowercase=lowercase, exclude_numeric=exclude_numeric)
        )

    vector = [0.0] * dimensions
    for feature, count in counts.items():
        digest = _feature_digest(feature, seed)
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


@dataclass(frozen=True)
class NGramConfig:
    """Which n-grams a :class:`NGramVectorizer` extracts."""

    char_min: int = 3
    char_max: int = 5
    word_min: int = 1
    word_max: int = 2
    lowercase: bool = True
    max_features: int = 4096
    include_chars: bool = True
    include_words: bool = True
    exclude_numeric: bool = True

    def __post_init__(self) -> None:
        if self.char_min < 1 or self.word_min < 1 or self.char_max < self.char_min:
            raise ValueError(f"invalid n-gram config: {self}")
        if self.word_max < self.word_min:
            raise ValueError(f"invalid n-gram config: {self}")
        if self.max_features < 1:
            raise ValueError("max_features must be >= 1")
        if not (self.include_chars or self.include_words):
            raise ValueError("NGramConfig must include character or word n-grams")

    def gram_counts(self, text: str) -> tuple[Counter[str], Counter[str]]:
        """Return (character gram counts, word gram counts) namespaced by prefix."""
        chars: Counter[str] = Counter()
        words: Counter[str] = Counter()
        if self.include_chars:
            for size in range(self.char_min, self.char_max + 1):
                for gram, count in character_ngrams(
                    text, size, lowercase=self.lowercase, exclude_numeric=self.exclude_numeric
                ).items():
                    chars[f"c:{gram}"] += count
        if self.include_words:
            for size in range(self.word_min, self.word_max + 1):
                for gram, count in word_ngrams(
                    text, size, lowercase=self.lowercase, exclude_numeric=self.exclude_numeric
                ).items():
                    words[f"w:{gram}"] += count
        return chars, words


class NGramVectorizer:
    """Vocabulary-based TF-IDF vectors over character and word n-grams.

    The vocabulary is built deterministically: grams are ranked by
    corpus frequency with a lexicographic tie-break, truncated to
    ``config.max_features``. Weights are ``(1 + log tf) * idf`` with
    smoothed IDF ``log(1 + N / (1 + df))``; each vector is
    L2-normalized so cosine similarity is a plain dot product.

    Fitting on training documents only keeps evaluation leakage-free
    (IDF is unsupervised but corpus-dependent).
    """

    def __init__(self, config: NGramConfig | None = None) -> None:
        self.config = config if config is not None else NGramConfig()
        self._index: dict[str, int] = {}
        self._idf: dict[str, float] = {}

    @property
    def fitted(self) -> bool:
        return bool(self._index)

    @property
    def vocabulary_size(self) -> int:
        return len(self._index)

    def fit(self, texts: Iterable[str]) -> Self:
        """Build the vocabulary and IDF table from *texts*.

        Args:
            texts: Training documents; consumed exactly once.

        Returns:
            ``self`` for chaining.
        """
        materialized = list(texts)
        document_frequency: Counter[str] = Counter()
        term_frequency: Counter[str] = Counter()
        for text in materialized:
            chars, words = self.config.gram_counts(text)
            for counts in (chars, words):
                for gram, count in counts.items():
                    term_frequency[gram] += count
                    document_frequency[gram] += 1

        ranked = sorted(term_frequency.items(), key=lambda kv: (-kv[1], kv[0]))
        selected = ranked[: self.config.max_features]
        self._index = {gram: position for position, (gram, _) in enumerate(selected)}

        total_documents = len(materialized)
        # Sklearn-style smoothed IDF: log((1 + N) / (1 + df)) + 1. Rare,
        # idiolect-bearing grams (informal markers) weigh far more than
        # ubiquitous template grams, which is where the separation lives.
        self._idf = {
            gram: math.log((1.0 + total_documents) / (1.0 + document_frequency[gram])) + 1.0
            for gram in self._index
        }
        return self

    def transform(self, text: str) -> tuple[float, ...]:
        """TF-IDF vector of *text* in the fitted vocabulary (L2-normalized).

        Raises:
            RuntimeError: If :meth:`fit` has not been called.
        """
        if not self._index:
            raise RuntimeError("NGramVectorizer.fit() must be called before transform()")
        chars, words = self.config.gram_counts(text)
        vector = [0.0] * len(self._index)
        for counts in (chars, words):
            for gram, count in counts.items():
                position = self._index.get(gram)
                if position is None:
                    continue
                vector[position] += (1.0 + math.log(count)) * self._idf[gram]
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(value / norm for value in vector)

    def similarity(self, left: str, right: str) -> float:
        """Cosine similarity between the TF-IDF vectors of two texts."""
        return cosine_similarity(self.transform(left), self.transform(right))
