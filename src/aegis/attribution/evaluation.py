"""Phase 16.3 actor-disjoint baseline evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aegis.attribution.baseline import (
    AttributionBaseline,
    AttributionExample,
    AttributionScore,
    all_baselines,
)


@dataclass(frozen=True)
class EvaluationExample:
    actor_id: str
    example: AttributionExample
    split: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id must be non-empty")
        if self.split not in {"train", "validation", "test"}:
            raise ValueError("split must be train, validation or test")


@dataclass(frozen=True)
class BaselineEvaluation:
    model_id: str
    model_version: str
    metrics: dict[str, float]
    scores: tuple[AttributionScore, ...]


def _auc_roc(labels: Sequence[int], scores: Sequence[float]) -> float:
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return 0.0
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    rank_sum = 0.0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        rank_sum += sum(avg_rank for k in range(i, j + 1) if labels[order[k]] == 1)
        i = j + 1
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _auc_pr(labels: Sequence[int], scores: Sequence[float]) -> float:
    positives = sum(labels)
    if not positives:
        return 0.0
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    tp = fp = 0
    previous_recall = 0.0
    area = 0.0
    for i in order:
        if labels[i]:
            tp += 1
        else:
            fp += 1
        recall = tp / positives
        precision = tp / (tp + fp)
        area += (recall - previous_recall) * precision
        previous_recall = recall
    return area


def _metrics(
    labels: Sequence[int], scores: Sequence[float], threshold: float = 0.5
) -> dict[str, float]:
    predicted = [int(s >= threshold) for s in scores]
    tp = sum(p == 1 and y == 1 for p, y in zip(predicted, labels, strict=True))
    tn = sum(p == 0 and y == 0 for p, y in zip(predicted, labels, strict=True))
    fp = sum(p == 1 and y == 0 for p, y in zip(predicted, labels, strict=True))
    fn = sum(p == 0 and y == 1 for p, y in zip(predicted, labels, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(labels) if labels else 0.0
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": _auc_roc(labels, scores),
        "pr_auc": _auc_pr(labels, scores),
        "tp": float(tp),
        "tn": float(tn),
        "fp": float(fp),
        "fn": float(fn),
    }


def actor_disjoint_split(
    examples: Sequence[EvaluationExample],
) -> dict[str, list[AttributionExample]]:
    actors: dict[str, list[AttributionExample]] = {}
    for item in examples:
        actors.setdefault(item.actor_id, []).append(item.example)
    result: dict[str, list[AttributionExample]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    for item in examples:
        result[item.split].append(item.example)
    seen: dict[str, set[str]] = {"train": set(), "validation": set(), "test": set()}
    for item in examples:
        seen[item.split].add(item.actor_id)
    if (
        seen["train"] & seen["validation"]
        or seen["train"] & seen["test"]
        or seen["validation"] & seen["test"]
    ):
        raise ValueError("actor-disjoint split violated")
    if not result["train"] or not result["validation"] or not result["test"]:
        raise ValueError("all three splits are required")
    return result


def evaluate_baselines(
    examples: Sequence[EvaluationExample], baselines: Sequence[AttributionBaseline] | None = None
) -> tuple[BaselineEvaluation, ...]:
    splits = actor_disjoint_split(examples)
    train = splits["train"]
    test = splits["test"]
    models = list(baselines) if baselines is not None else all_baselines()
    results = []
    for model in models:
        model.fit(train)
        scored = tuple(model.score(item) for item in test)
        labels = [item.label for item in test]
        scores = [item.raw_score for item in scored]
        results.append(
            BaselineEvaluation(model.name, model.version, _metrics(labels, scores), scored)
        )
    return tuple(results)
