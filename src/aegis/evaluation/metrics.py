"""Candidate-link evaluation metrics against synthetic ground truth."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationMetrics:
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1: float
    false_positive_rate: float


class SyntheticEvaluator:
    """Evaluate candidate-link predictions against synthetic ground truth."""

    def evaluate(
        self,
        predicted_pairs: set[tuple[str, str]],
        ground_truth_pairs: set[tuple[str, str]],
        all_actor_ids: set[str],
    ) -> EvaluationMetrics:
        normalized_predictions = {self._normalize_pair(*pair) for pair in predicted_pairs}
        normalized_truth = {self._normalize_pair(*pair) for pair in ground_truth_pairs}

        true_positives = len(normalized_predictions & normalized_truth)
        false_positives = len(normalized_predictions - normalized_truth)
        false_negatives = len(normalized_truth - normalized_predictions)

        possible_pairs = {
            self._normalize_pair(source, target)
            for source in all_actor_ids
            for target in all_actor_ids
            if source != target
        }

        true_negatives = len((possible_pairs - normalized_truth) - normalized_predictions)

        precision = self._safe_divide(
            true_positives,
            true_positives + false_positives,
        )
        recall = self._safe_divide(
            true_positives,
            true_positives + false_negatives,
        )
        f1 = self._safe_divide(
            2 * precision * recall,
            precision + recall,
        )
        false_positive_rate = self._safe_divide(
            false_positives,
            false_positives + true_negatives,
        )

        return EvaluationMetrics(
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            true_negatives=true_negatives,
            precision=round(precision, 3),
            recall=round(recall, 3),
            f1=round(f1, 3),
            false_positive_rate=round(false_positive_rate, 3),
        )

    @staticmethod
    def _normalize_pair(source: str, target: str) -> tuple[str, str]:
        return (min(source, target), max(source, target))

    @staticmethod
    def _safe_divide(numerator: float, denominator: float) -> float:
        if denominator == 0:
            return 0.0
        return numerator / denominator
