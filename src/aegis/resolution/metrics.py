"""Evaluation metrics for entity-resolution baselines (Phase 09).

The plan requires exactly these metrics for the frozen baselines:

* precision
* recall
* F1
* PR-AUC (average precision over the ranked candidate pairs)
* MRR (mean reciprocal rank of the first true link per query alias)
* Recall@K

Everything here is pure Python, deterministic, and unit-testable against
hand-computed examples.  A zero-denominator case returns ``0.0`` rather
than raising, matching :class:`aegis.evaluation.metrics.SyntheticEvaluator`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: Default K for Recall@K when the caller does not choose one.
DEFAULT_RECALL_K = 10


@dataclass(frozen=True)
class ClassificationMetrics:
    """Thresholded binary metrics over scored candidate pairs."""

    precision: float
    recall: float
    f1: float
    pr_auc: float


@dataclass(frozen=True)
class RankingMetrics:
    """Ranking metrics over per-query candidate rankings."""

    mrr: float
    recall_at_k: float
    k: int
    query_count: int


@dataclass(frozen=True)
class BaselineMetrics:
    """The full plan metric set for one baseline."""

    precision: float
    recall: float
    f1: float
    pr_auc: float
    mrr: float
    recall_at_k: float
    k: int


def _divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _validate_scored_inputs(scores: Sequence[float], labels: Sequence[int]) -> None:
    """Shared input guards for the scored binary metrics.

    The domain and range checks double as an argument-order trap: a
    caller that swaps ``(scores, labels)`` passes float scores as
    labels (values outside ``{0, 1}``) or raw 0/1 labels as scores, so
    the swap raises a clear ``ValueError`` instead of silently
    producing wrong numbers.

    Raises:
        ValueError: On misaligned lengths, labels outside ``{0, 1}``,
            or scores that are non-finite or outside ``[0.0, 1.0]``.
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must align")
    for label in labels:
        if label not in (0, 1):
            raise ValueError(
                f"labels must be 0 or 1, got {label!r} — "
                "the signature is (scores, labels); swapped arguments fail here"
            )
    for score in scores:
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError(f"scores must be finite and within [0.0, 1.0], got {score!r}")


def precision_recall_f1(
    predicted: Iterable[bool], actual: Iterable[bool]
) -> tuple[float, float, float]:
    """Binary precision, recall and F1 from paired boolean iterables."""
    true_positives = false_positives = false_negatives = 0
    for predicted_positive, actual_positive in zip(predicted, actual, strict=True):
        if predicted_positive and actual_positive:
            true_positives += 1
        elif predicted_positive:
            false_positives += 1
        elif actual_positive:
            false_negatives += 1
    precision = _divide(true_positives, true_positives + false_positives)
    recall = _divide(true_positives, true_positives + false_negatives)
    f1 = _divide(2.0 * precision * recall, precision + recall)
    return precision, recall, f1


def average_precision(scores: Sequence[float], labels: Sequence[int]) -> float:
    """PR-AUC as average precision over scores ranked best-first.

    This is the single canonical implementation of the metric in the
    codebase; :func:`aegis.stylometry.evaluation.average_precision`
    delegates here, so both public entry points accept the canonical
    ``(scores, labels)`` argument order and return identical values.

    Ties are broken by input order so the value is reproducible for a
    fixed candidate enumeration.  A pair set without positives yields 0.0.

    Raises:
        ValueError: On misaligned inputs, labels outside ``{0, 1}``, or
            non-finite/out-of-range scores (see
            :func:`_validate_scored_inputs` — the guards also catch a
            swapped ``(scores, labels)`` call).
    """
    _validate_scored_inputs(scores, labels)
    positives = sum(labels)
    if positives == 0:
        return 0.0
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    hits = 0
    precision_sum = 0.0
    for rank, index in enumerate(order, start=1):
        if labels[index]:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / positives


def precision_recall_f1_at_threshold(
    scores: Sequence[float],
    labels: Sequence[int],
    threshold: float,
) -> tuple[float, float, float]:
    """Precision/recall/F1 for ``score >= threshold``."""
    if len(scores) != len(labels):
        raise ValueError("scores and labels must align")
    predicted = [score >= threshold for score in scores]
    actual = [bool(label) for label in labels]
    return precision_recall_f1(predicted, actual)


def best_f1_threshold(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Threshold on ``scores`` maximizing F1 (ties -> highest threshold).

    The single canonical implementation: :func:`aegis.stylometry.evaluation.best_f1_threshold`
    delegates here, so both public entry points accept the canonical
    ``(scores, labels)`` argument order and return the identical cutoff.

    Complexity is **O(N log N)** by construction — one sort of the
    indices by score (descending) followed by a single pass that
    accumulates TP/FP as the effective threshold drops.  F1 is evaluated
    exactly once per *distinct* score: equal scores are consumed as one
    group because the prediction rule is ``score >= threshold``, so a
    group must be fully included before its cutoff is scored.  Because
    the sweep visits thresholds highest-first and only replaces the
    incumbent on a strict improvement, ties keep the first (highest)
    threshold seen — matching the historical
    ``precision_recall_f1_at_threshold``-per-candidate behaviour
    float-for-float, since F1 is computed from TP/FP/FN with the same
    arithmetic as :func:`precision_recall_f1`.  With no positives every
    candidate scores 0.0 F1, so the first (highest) score wins.

    Raises:
        ValueError: On empty input, misaligned inputs, labels outside
            ``{0, 1}``, or non-finite/out-of-range scores.
    """
    if not scores:
        raise ValueError("cannot choose a threshold without scores")
    _validate_scored_inputs(scores, labels)
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    total_positives = sum(labels)
    true_positives = 0
    false_positives = 0
    best_threshold = scores[order[0]]
    best_f1 = -1.0
    position = 0
    while position < len(order):
        threshold = scores[order[position]]
        while position < len(order) and scores[order[position]] == threshold:
            if labels[order[position]]:
                true_positives += 1
            else:
                false_positives += 1
            position += 1
        false_negatives = total_positives - true_positives
        precision = _divide(true_positives, true_positives + false_positives)
        recall = _divide(true_positives, true_positives + false_negatives)
        f1 = _divide(2.0 * precision * recall, precision + recall)
        if f1 > best_f1:  # strict: the first (highest) threshold wins ties
            best_f1 = f1
            best_threshold = threshold
    return best_threshold


def reciprocal_rank(ranked_labels: Sequence[int]) -> float:
    """Reciprocal rank of the first relevant item in a ranked list."""
    for rank, label in enumerate(ranked_labels, start=1):
        if label:
            return 1.0 / rank
    return 0.0


def recall_at_k(ranked_labels: Sequence[int], k: int) -> float:
    """Fraction of all relevant items present in the top ``k`` positions."""
    if k < 1:
        raise ValueError("k must be >= 1")
    total = sum(ranked_labels)
    if total == 0:
        return 0.0
    return sum(ranked_labels[:k]) / total


def ranking_metrics(
    rankings: Sequence[Sequence[int]],
    *,
    k: int = DEFAULT_RECALL_K,
) -> RankingMetrics:
    """MRR and Recall@K averaged over per-query ranked label lists."""
    if k < 1:
        raise ValueError("k must be >= 1")
    if not rankings:
        return RankingMetrics(mrr=0.0, recall_at_k=0.0, k=k, query_count=0)
    reciprocal_sum = 0.0
    recall_sum = 0.0
    for ranked in rankings:
        reciprocal_sum += reciprocal_rank(ranked)
        recall_sum += recall_at_k(ranked, k)
    count = len(rankings)
    return RankingMetrics(
        mrr=reciprocal_sum / count,
        recall_at_k=recall_sum / count,
        k=k,
        query_count=count,
    )


def classification_metrics(
    scores: Sequence[float],
    labels: Sequence[int],
    threshold: float,
) -> ClassificationMetrics:
    """Thresholded precision/recall/F1 plus PR-AUC for one baseline."""
    precision, recall, f1 = precision_recall_f1_at_threshold(scores, labels, threshold)
    return ClassificationMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        pr_auc=average_precision(scores, labels),
    )
