"""Phase 16 transparent attribution baselines.

This module implements the three baselines required by the implementation plan:

1. transparent weighted-signal fusion;
2. logistic regression over the same six channel signals;
3. XGBoost over the same six channel signals.

Scores are deliberately called ``raw_score``. They are not probabilities until
Phase 18 calibration has been applied.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, cast

from aegis.attribution.signals import (
    DEFAULT_CHANNEL_WEIGHTS,
    ChannelSignals,
    ChannelWeights,
    sigmoid,
    weighted_logit,
)


@dataclass(frozen=True)
class AttributionExample:
    """One labeled candidate pair represented by the six attribution signals."""

    pair_id: str
    signals: ChannelSignals
    label: int
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.pair_id.strip():
            raise ValueError("pair_id must be non-empty")
        if self.label not in (0, 1):
            raise ValueError("label must be 0 or 1")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("evidence_ids must contain only non-empty strings")


@dataclass(frozen=True)
class AttributionScore:
    """One raw attribution score and its reproducibility metadata."""

    pair_id: str
    raw_score: float
    model_id: str
    model_version: str
    signals: dict[str, float]
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.pair_id.strip():
            raise ValueError("pair_id must be non-empty")
        if not math.isfinite(self.raw_score) or not 0.0 <= self.raw_score <= 1.0:
            raise ValueError("raw_score must be finite and within [0, 1]")
        if not self.model_id.strip() or not self.model_version.strip():
            raise ValueError("model_id and model_version must be non-empty")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("evidence_ids must contain only non-empty strings")


class AttributionBaseline(ABC):
    """Common interface for Phase 16 attribution baselines."""

    name: ClassVar[str]
    version: ClassVar[str]

    @property
    @abstractmethod
    def fitted(self) -> bool:
        """Whether a learned baseline has been fitted."""

    def fit(self, examples: list[AttributionExample]) -> None:
        """Fit a learned model; transparent fusion is already fitted."""
        if not examples:
            raise ValueError("cannot fit attribution baseline on an empty dataset")
        self._fit(examples)

    @abstractmethod
    def _fit(self, examples: list[AttributionExample]) -> None:
        """Fit implementation."""

    @abstractmethod
    def _raw_score(self, signals: ChannelSignals) -> float:
        """Score one signal vector."""

    def score(self, example: AttributionExample) -> AttributionScore:
        """Score an example without using its ground-truth label."""
        return AttributionScore(
            pair_id=example.pair_id,
            raw_score=self._raw_score(example.signals),
            model_id=self.name,
            model_version=self.version,
            signals=example.signals.as_dict(),
            evidence_ids=example.evidence_ids,
        )


class TransparentAttributionBaseline(AttributionBaseline):
    """Plan baseline 1: sigmoid of the declared weighted channel signals."""

    name = "transparent-fusion"
    version = "baseline-0.1"

    def __init__(self, weights: ChannelWeights = DEFAULT_CHANNEL_WEIGHTS) -> None:
        self.weights = weights

    @property
    def fitted(self) -> bool:
        return True

    def _fit(self, examples: list[AttributionExample]) -> None:
        # The transparent baseline has no learned parameters.  ``fit`` still
        # validates that callers do not accidentally pass an empty dataset.
        del examples

    def _raw_score(self, signals: ChannelSignals) -> float:
        return round(sigmoid(weighted_logit(signals, self.weights)), 6)


class LogisticAttributionBaseline(AttributionBaseline):
    """Plan baseline 2: deterministic class-balanced logistic regression.

    The implementation mirrors the project's existing resolution baseline:
    training-only standardization, L2 regularization, fixed full-batch gradient
    descent, and no stochastic optimizer. This keeps the baseline reproducible
    without introducing another ML framework dependency.
    """

    name = "logistic-regression"
    version = "baseline-0.1"

    def __init__(
        self,
        *,
        learning_rate: float = 0.25,
        epochs: int = 400,
        l2: float = 1e-3,
    ) -> None:
        if learning_rate <= 0.0 or epochs < 1 or l2 < 0.0:
            raise ValueError("learning_rate > 0, epochs >= 1 and l2 >= 0 are required")
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.l2 = l2
        self._weights: list[float] | None = None
        self._bias = 0.0
        self._mean: list[float] | None = None
        self._scale: list[float] | None = None

    @property
    def fitted(self) -> bool:
        return self._weights is not None

    def _fit(self, examples: list[AttributionExample]) -> None:
        import numpy as np  # noqa: PLC0415

        features = np.asarray([item.signals.as_vector() for item in examples], dtype=np.float64)
        labels = np.asarray([item.label for item in examples], dtype=np.float64)
        row_count, dimensions = features.shape
        positives = float(labels.sum())
        negatives = float(row_count) - positives
        if positives == 0.0 or negatives == 0.0:
            raise ValueError("logistic regression requires both positive and negative examples")

        mean = features.mean(axis=0)
        scale = features.std(axis=0)
        scale[scale == 0.0] = 1.0
        standardized = (features - mean) / scale

        class_weights = np.where(
            labels == 1.0,
            row_count / (2.0 * positives),
            row_count / (2.0 * negatives),
        )
        coefficients = np.zeros(dimensions, dtype=np.float64)
        bias = 0.0
        for _ in range(self.epochs):
            logits = standardized @ coefficients + bias
            predictions = 1.0 / (1.0 + np.exp(-np.clip(logits, -500.0, 500.0)))
            errors = (predictions - labels) * class_weights
            gradient = standardized.T @ errors / row_count + self.l2 * coefficients
            coefficients -= self.learning_rate * gradient
            bias -= self.learning_rate * float(errors.mean())

        self._weights = coefficients.tolist()
        self._bias = bias
        self._mean = mean.tolist()
        self._scale = scale.tolist()

    def _raw_score(self, signals: ChannelSignals) -> float:
        if self._weights is None or self._mean is None or self._scale is None:
            raise RuntimeError(f"{self.name} must be fit before scoring")
        standardized = [
            (value - mean) / scale
            for value, mean, scale in zip(signals.as_vector(), self._mean, self._scale, strict=True)
        ]
        logit = (
            sum(weight * value for weight, value in zip(self._weights, standardized, strict=True))
            + self._bias
        )
        return round(sigmoid(logit), 6)


class XgboostAttributionBaseline(AttributionBaseline):
    """Plan baseline 3: XGBoost over the same six channel signals."""

    name = "xgboost"
    version = "baseline-0.1"

    def __init__(
        self,
        *,
        estimators: int = 80,
        max_depth: int = 3,
        learning_rate: float = 0.15,
    ) -> None:
        if estimators < 1 or max_depth < 1 or learning_rate <= 0.0:
            raise ValueError("estimators/max_depth must be >= 1 and learning_rate > 0")
        self.estimators = estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self._model = None

    @property
    def fitted(self) -> bool:
        return self._model is not None

    def _fit(self, examples: list[AttributionExample]) -> None:
        import numpy as np  # noqa: PLC0415

        try:
            from xgboost import DMatrix, train  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("xgboost is required for XgboostAttributionBaseline") from exc

        labels = [item.label for item in examples]
        if len(set(labels)) < 2:
            raise ValueError("XGBoost requires both positive and negative examples")
        features = np.asarray([item.signals.as_vector() for item in examples], dtype=np.float64)
        # nthread=1 on DMatrix as well as in params: params only throttles the
        # booster, whereas DMatrix's own OpenMP team (SparsePage::Push) is
        # sized separately and is what crashes when another native library in
        # the process ships its own copy of libomp.
        dtrain = DMatrix(features, label=np.asarray(labels, dtype=np.float32), nthread=1)
        params: dict[str, object] = {
            "max_depth": self.max_depth,
            "eta": self.learning_rate,
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "seed": 26151,
            "nthread": 1,
            "verbosity": 0,
        }
        self._model = cast(Any, train(params, dtrain, num_boost_round=self.estimators))

    def _raw_score(self, signals: ChannelSignals) -> float:
        if self._model is None:
            raise RuntimeError(f"{self.name} must be fit before scoring")
        import numpy as np  # noqa: PLC0415
        from xgboost import DMatrix  # noqa: PLC0415

        values = np.asarray([signals.as_vector()], dtype=np.float64)
        return round(float(self._model.predict(DMatrix(values, nthread=1))[0]), 6)


def all_baselines() -> list[AttributionBaseline]:
    """Return the three Phase 16 baselines in plan order."""
    return [
        TransparentAttributionBaseline(),
        LogisticAttributionBaseline(),
        XgboostAttributionBaseline(),
    ]
