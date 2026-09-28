"""Supervised pair head for training Phase 19 encoders against labeled links."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from aegis.attribution.signals import sigmoid
from aegis.gnn.models import PairPrediction, _BaseEncoder


@dataclass(frozen=True)
class LabeledNodePair:
    source_id: str
    target_id: str
    label: int

    def __post_init__(self) -> None:
        if (
            not self.source_id.strip()
            or not self.target_id.strip()
            or self.source_id == self.target_id
        ):
            raise ValueError("pairs require two distinct non-empty node ids")
        if self.label not in (0, 1):
            raise ValueError("label must be 0 or 1")


class GnnPairTrainer:
    """Fits a deterministic logistic pair head over fixed GNN embeddings.

    This is the first supervised training stage. For full end-to-end GNN
    learning, replace the NumPy reference encoder with a PyTorch/DGL trainer
    while retaining this labeled-pair, split, and calibration contract.
    """

    def __init__(
        self, encoder: _BaseEncoder, learning_rate: float = 0.2, epochs: int = 400
    ) -> None:
        if learning_rate <= 0.0 or epochs < 1:
            raise ValueError("learning_rate must be positive and epochs at least one")
        self.encoder = encoder
        self.learning_rate = learning_rate
        self.epochs = epochs
        self._weights: np.ndarray | None = None
        self._mean: np.ndarray | None = None
        self._scale: np.ndarray | None = None
        self._bias = 0.0

    def fit(self, pairs: list[LabeledNodePair]) -> GnnPairTrainer:
        if len(pairs) < 2 or len({pair.label for pair in pairs}) != 2:
            raise ValueError("training requires at least one positive and one negative pair")
        features = np.asarray([self._features(pair.source_id, pair.target_id) for pair in pairs])
        labels = np.asarray([pair.label for pair in pairs], dtype=np.float64)
        mean, scale = features.mean(axis=0), features.std(axis=0)
        scale[scale == 0.0] = 1.0
        standardized = (features - mean) / scale
        weights = np.zeros(standardized.shape[1], dtype=np.float64)
        bias = 0.0
        for _ in range(self.epochs):
            prediction = 1.0 / (
                1.0 + np.exp(-np.clip(standardized @ weights + bias, -500.0, 500.0))
            )
            error = prediction - labels
            weights -= self.learning_rate * (standardized.T @ error / len(pairs))
            bias -= self.learning_rate * float(error.mean())
        self._weights, self._mean, self._scale, self._bias = weights, mean, scale, bias
        return self

    def predict(self, source_id: str, target_id: str) -> PairPrediction:
        if self._weights is None or self._mean is None or self._scale is None:
            raise RuntimeError("fit must run before predict")
        feature = (self._features(source_id, target_id) - self._mean) / self._scale
        score = sigmoid(float(feature @ self._weights + self._bias))
        return PairPrediction(
            source_id, target_id, round(score, 6), f"{self.encoder.model_id}-trained"
        )

    def _features(self, source_id: str, target_id: str) -> np.ndarray:
        graph = self.encoder._graph
        if graph is None:
            raise RuntimeError("encoder.fit(graph) must run before GNN pair training")
        embeddings = self.encoder.embeddings()
        left, right = (
            embeddings[graph.node_index(source_id)],
            embeddings[graph.node_index(target_id)],
        )
        return np.concatenate((np.abs(left - right), left * right))
