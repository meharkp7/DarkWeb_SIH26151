"""Phase 18 attribution score calibration utilities."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationResult:
    raw_score: float
    calibrated_confidence: float
    calibration_method: str
    calibration_version: str


class Calibrator:
    name: str
    version = "calibration-0.1"

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> Calibrator:
        if len(scores) != len(labels) or len(scores) < 2:
            raise ValueError("scores and labels must have equal length and at least 2 samples")
        if any(label not in (0, 1) for label in labels):
            raise ValueError("labels must be binary")
        if len(set(labels)) < 2:
            raise ValueError("calibration requires both positive and negative labels")
        self._fit(scores, labels)
        return self

    def _fit(self, scores: Sequence[float], labels: Sequence[int]) -> None:
        raise NotImplementedError

    def transform(self, score: float) -> float:
        raise NotImplementedError

    def calibrate(self, score: float) -> CalibrationResult:
        if not 0.0 <= score <= 1.0 or not math.isfinite(score):
            raise ValueError("score must be finite and in [0, 1]")
        return CalibrationResult(
            raw_score=score,
            calibrated_confidence=round(self.transform(score), 6),
            calibration_method=self.name,
            calibration_version=self.version,
        )


class PlattCalibrator(Calibrator):
    name = "platt"

    def _fit(self, scores: Sequence[float], labels: Sequence[int]) -> None:
        # Deterministic full-batch logistic regression on logit(raw_score).
        xs = [
            math.log(min(max(s, 1e-6), 1.0 - 1e-6) / (1.0 - min(max(s, 1e-6), 1.0 - 1e-6)))
            for s in scores
        ]
        a = 1.0
        b = 0.0
        for _ in range(500):
            ga = gb = 0.0
            for x, y in zip(xs, labels, strict=True):
                p = 1.0 / (1.0 + math.exp(-(a * x + b)))
                ga += (p - y) * x
                gb += p - y
            lr = 0.05 / max(len(xs), 1)
            a -= lr * ga
            b -= lr * gb
        self._a = a
        self._b = b

    def transform(self, score: float) -> float:
        if not hasattr(self, "_a"):
            raise RuntimeError("calibrator must be fit before transform")
        x = math.log(min(max(score, 1e-6), 1.0 - 1e-6) / (1.0 - min(max(score, 1e-6), 1.0 - 1e-6)))
        return 1.0 / (1.0 + math.exp(-(self._a * x + self._b)))


class IsotonicCalibrator(Calibrator):
    name = "isotonic"

    def _fit(self, scores: Sequence[float], labels: Sequence[int]) -> None:
        pairs = sorted(zip(scores, labels, strict=True), key=lambda item: item[0])
        blocks: list[list[float]] = []
        for score, label in pairs:
            blocks.append([score, float(label), 1.0])
            while len(blocks) >= 2:
                left, right = blocks[-2], blocks[-1]
                if left[1] / left[2] <= right[1] / right[2]:
                    break
                merged = [right[0], left[1] + right[1], left[2] + right[2]]
                blocks[-2:] = [merged]
        self._blocks = blocks

    def transform(self, score: float) -> float:
        if not hasattr(self, "_blocks"):
            raise RuntimeError("calibrator must be fit before transform")
        for block in self._blocks:
            if score <= block[0]:
                return block[1] / block[2]
        block = self._blocks[-1]
        return block[1] / block[2]


class TemperatureCalibrator(Calibrator):
    name = "temperature"

    def _fit(self, scores: Sequence[float], labels: Sequence[int]) -> None:
        logits = [
            math.log(min(max(s, 1e-6), 1.0 - 1e-6) / (1.0 - min(max(s, 1e-6), 1.0 - 1e-6)))
            for s in scores
        ]
        best_t = 1.0
        best_loss = float("inf")
        for i in range(1, 201):
            t = 0.1 + i * 0.01
            loss = 0.0
            for z, y in zip(logits, labels, strict=True):
                p = 1.0 / (1.0 + math.exp(-z / t))
                loss -= y * math.log(max(p, 1e-12)) + (1 - y) * math.log(max(1 - p, 1e-12))
            if loss < best_loss:
                best_loss, best_t = loss, t
        self._temperature = best_t

    def transform(self, score: float) -> float:
        if not hasattr(self, "_temperature"):
            raise RuntimeError("calibrator must be fit before transform")
        z = math.log(min(max(score, 1e-6), 1.0 - 1e-6) / (1.0 - min(max(score, 1e-6), 1.0 - 1e-6)))
        return 1.0 / (1.0 + math.exp(-z / self._temperature))


def brier_score(scores: Sequence[float], labels: Sequence[int]) -> float:
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must have equal non-zero length")
    return sum((s - y) ** 2 for s, y in zip(scores, labels, strict=True)) / len(scores)


def expected_calibration_error(
    scores: Sequence[float], labels: Sequence[int], bins: int = 10
) -> float:
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must have equal non-zero length")
    if bins < 1:
        raise ValueError("bins must be positive")
    total = len(scores)
    ece = 0.0
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        members = [
            j
            for j, score in enumerate(scores)
            if (lo <= score < hi) or (i == bins - 1 and score == hi)
        ]
        if members:
            confidence = sum(scores[j] for j in members) / len(members)
            accuracy = sum(labels[j] for j in members) / len(members)
            ece += len(members) / total * abs(confidence - accuracy)
    return ece


def calibrator_suite() -> tuple[Calibrator, ...]:
    return (PlattCalibrator(), IsotonicCalibrator(), TemperatureCalibrator())
