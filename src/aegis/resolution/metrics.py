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

    Ties are broken by input order so the value is reproducible for a
    fixed candidate enumeration.  A pair set without positives yields 0.0.
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must align")
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
    """Threshold on ``scores`` maximizing F1 (ties -> highest threshold)."""
    if not scores:
        raise ValueError("cannot choose a threshold without scores")
    candidates = sorted({*scores})
    best_threshold = candidates[-1]
    best_f1 = -1.0
    for threshold in candidates:
        _, _, f1 = precision_recall_f1_at_threshold(scores, labels, threshold)
        # >= best: later (higher) thresholds win ties, keeping predictions strict
        if f1 >= best_f1:
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
