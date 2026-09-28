"""Classical stylometric features (Phase 11, step 2).

A dependency-free port of the measures authorship-analysis literature
settled on before neural methods: length statistics, lexical
diversity, punctuation/case/digit habits, function-word density, and
Shannon entropy of the word distribution. Features are computed from
raw text by :meth:`StylometricFeatures.from_text` and compared with a
scale-free similarity (:func:`stylometric_similarity`) so that raw
counts (document length) do not dominate ratio-like evidence.
"""

from __future__ import annotations

import math
import re
import string
import unicodedata
from collections import Counter
from dataclasses import dataclass

from aegis.stylometry.ngrams import tokenize_words

#: Closed-class English function words — the classical authorship cue.
FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "did",
        "do",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "out",
        "she",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "too",
        "up",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")

#: Feature order of :meth:`StylometricFeatures.as_vector`.
FEATURE_NAMES: tuple[str, ...] = (
    "char_count",
    "word_count",
    "sentence_count",
    "mean_word_length",
    "std_word_length",
    "mean_sentence_length",
    "std_sentence_length",
    "type_token_ratio",
    "hapax_ratio",
    "punctuation_ratio",
    "uppercase_ratio",
    "digit_ratio",
    "function_word_ratio",
    "word_entropy",
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _is_punctuation(char: str) -> bool:
    """True for Unicode punctuation *and* symbol characters.

    Symbol coverage matters: markers such as ``:-)`` or ``==>`` are
    symbol-category characters, not ASCII punctuation.
    """
    return char in string.punctuation or unicodedata.category(char).startswith(("P", "S"))


@dataclass(frozen=True)
class StylometricFeatures:
    """Classical stylometric feature vector for one text.

    All fields are plain floats so the record can be serialized,
    vectorized (:meth:`as_vector`), and compared feature-by-feature.
    """

    char_count: float
    word_count: float
    sentence_count: float
    mean_word_length: float
    std_word_length: float
    mean_sentence_length: float
    std_sentence_length: float
    type_token_ratio: float
    hapax_ratio: float
    punctuation_ratio: float
    uppercase_ratio: float
    digit_ratio: float
    function_word_ratio: float
    word_entropy: float

    @classmethod
    def from_text(cls, text: str) -> StylometricFeatures:
        """Compute every feature from *text*; the empty text yields zeros."""
        if not text:
            return cls(
                char_count=0.0,
                word_count=0.0,
                sentence_count=0.0,
                mean_word_length=0.0,
                std_word_length=0.0,
                mean_sentence_length=0.0,
                std_sentence_length=0.0,
                type_token_ratio=0.0,
                hapax_ratio=0.0,
                punctuation_ratio=0.0,
                uppercase_ratio=0.0,
                digit_ratio=0.0,
                function_word_ratio=0.0,
                word_entropy=0.0,
            )

        words = tokenize_words(text, lowercase=False)
        lowered = [word.lower() for word in words]
        word_lengths = [len(word) for word in lowered]

        sentences = [part for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]
        sentence_lengths = [float(len(tokenize_words(sentence))) for sentence in sentences]

        letters = [char for char in text if char.isalpha()]
        uppercase = sum(1 for char in letters if char.isupper())
        punctuation = sum(1 for char in text if _is_punctuation(char))
        digits = sum(1 for char in text if char.isdigit())

        token_counts = Counter(lowered)
        unique_tokens = len(token_counts)
        hapax = sum(1 for count in token_counts.values() if count == 1)
        total_tokens = len(lowered)
        entropy = 0.0
        if total_tokens:
            for count in token_counts.values():
                probability = count / total_tokens
                entropy -= probability * math.log2(probability)

        char_count = float(len(text))
        return cls(
            char_count=char_count,
            word_count=float(total_tokens),
            sentence_count=float(len(sentences)),
            mean_word_length=_mean([float(value) for value in word_lengths]),
            std_word_length=_std([float(value) for value in word_lengths]),
            mean_sentence_length=_mean(sentence_lengths),
            std_sentence_length=_std(sentence_lengths),
            type_token_ratio=unique_tokens / total_tokens if total_tokens else 0.0,
            hapax_ratio=hapax / unique_tokens if unique_tokens else 0.0,
            punctuation_ratio=punctuation / char_count,
            uppercase_ratio=uppercase / len(letters) if letters else 0.0,
            digit_ratio=digits / char_count,
            function_word_ratio=(
                sum(1 for token in lowered if token in FUNCTION_WORDS) / total_tokens
                if total_tokens
                else 0.0
            ),
            word_entropy=entropy,
        )

    def as_vector(self) -> tuple[float, ...]:
        """Features in :data:`FEATURE_NAMES` order."""
        return (
            self.char_count,
            self.word_count,
            self.sentence_count,
            self.mean_word_length,
            self.std_word_length,
            self.mean_sentence_length,
            self.std_sentence_length,
            self.type_token_ratio,
            self.hapax_ratio,
            self.punctuation_ratio,
            self.uppercase_ratio,
            self.digit_ratio,
            self.function_word_ratio,
            self.word_entropy,
        )


def stylometric_similarity(left: StylometricFeatures, right: StylometricFeatures) -> float:
    """Scale-free agreement between two feature vectors, in ``[0, 1]``.

    Each feature contributes ``1 - |a - b| / (|a| + |b|)`` (two all-zero
    features agree perfectly), and the per-feature agreements are
    averaged. Unlike raw cosine this treats a 10 % difference in
    ``punctuation_ratio`` the same regardless of document length, so
    short aliases are not penalised against long ones.
    """
    left_vector = left.as_vector()
    right_vector = right.as_vector()
    agreements: list[float] = []
    for a, b in zip(left_vector, right_vector, strict=True):
        if a == 0.0 and b == 0.0:
            agreements.append(1.0)
        else:
            agreements.append(1.0 - abs(a - b) / (abs(a) + abs(b)))
    return sum(agreements) / len(agreements)
