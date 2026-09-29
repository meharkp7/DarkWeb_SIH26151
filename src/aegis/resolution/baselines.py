"""Entity-resolution baselines (Phase 09).

The plan freezes five baselines, built in this exact order, before any
GNN training (Phase 19) is allowed to start:

1. **Exact normalized handle** — equality on :func:`normalize_handle`.
2. **Edit distance** — ``1 - normalized Levenshtein`` on handles.
3. **TF-IDF cosine** — text similarity of the aliases' documents.
4. **Logistic regression** — linear model over the nine plan features
   (gradient descent, class-balanced, deterministic).
5. **XGBoost** — gradient-boosted trees over the same features
   (fixed seed, single-threaded for reproducibility).

All five share one interface: :class:`ResolutionBaseline`.  Stateless
baselines ignore :meth:`ResolutionBaseline.fit`; learned baselines refuse
to score before fitting so a mis-ordered pipeline fails loudly.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from aegis.resolution.features import (
    CandidatePairFeatures,
    handle_similarity,
    normalize_handle,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, xgboost stays lazy at runtime
    from xgboost import Booster

#: Training defaults shared by the learned baselines.
RANDOM_SEED = 26151


@dataclass(frozen=True)
class CandidatePair:
    """One candidate link with its features and (training/eval only) label.

    Handles ride along because the two raw baselines (exact match, edit
    distance) compare observable handles directly, outside the nine
    fixed features.  ``label`` is ground truth: it is consumed by
    ``fit`` and evaluation, never by feature extraction.
    """

    left_alias_id: str
    right_alias_id: str
    left_handle: str
    right_handle: str
    features: CandidatePairFeatures
    label: int

    @property
    def normalized_handles(self) -> tuple[str, str]:
        """The two handles in comparison form (as baseline 1 sees them)."""
        return normalize_handle(self.left_handle), normalize_handle(self.right_handle)


class ResolutionBaseline(ABC):
    """Common interface for the five plan baselines."""

    name: ClassVar[str] = "baseline"

    def fit(self, pairs: Sequence[CandidatePair]) -> None:
        """Learn parameters from labelled pairs; stateless baselines ignore this."""
        del pairs

    @abstractmethod
    def score(self, pair: CandidatePair) -> float:
        """Return a link score in ``[0, 1]`` (higher = more likely same actor)."""


class ExactHandleBaseline(ResolutionBaseline):
    """Plan baseline 1: exact match on the normalized handle."""

    name = "exact_handle"

    def score(self, pair: CandidatePair) -> float:
        left, right = pair.normalized_handles
        return 1.0 if left and left == right else 0.0


class EditDistanceBaseline(ResolutionBaseline):
    """Plan baseline 2: ``1 - normalized Levenshtein`` similarity of handles."""

    name = "edit_distance"

    def score(self, pair: CandidatePair) -> float:
        return handle_similarity(pair.left_handle, pair.right_handle)


class TfIdfCosineBaseline(ResolutionBaseline):
    """Plan baseline 3: TF-IDF cosine over the aliases' documents."""

    name = "tfidf_cosine"

    def score(self, pair: CandidatePair) -> float:
        return pair.features.text_similarity


# ------------------------------------------------------- learned baselines


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


@dataclass
class LogisticRegressionBaseline(ResolutionBaseline):
    """Plan baseline 4: class-balanced logistic regression via gradient descent.

    Deterministic: full-batch gradient descent with a fixed number of
    epochs, L2 regularization, and features standardized from the
    training set (constant features become zero, not NaN).  ``fit``
    vectorizes over numpy for speed; ``score`` stays pure Python so the
    inference path has no import cost.
    """

    name: ClassVar[str] = "logistic_regression"

    learning_rate: float = 0.5
    epochs: int = 300
    l2: float = 1e-3

    def __post_init__(self) -> None:
        self._weights: list[float] | None = None
        self._bias: float = 0.0
        self._mean: list[float] | None = None
        self._scale: list[float] | None = None

    @property
    def fitted(self) -> bool:
        return self._weights is not None

    def fit(self, pairs: Sequence[CandidatePair]) -> None:
        if not pairs:
            raise ValueError("cannot fit logistic regression on an empty pair set")
        import numpy as np  # noqa: PLC0415 - lazy: keeps import cost off the package path

        features = np.asarray([pair.features.as_vector() for pair in pairs], dtype=np.float64)
        labels = np.asarray([pair.label for pair in pairs], dtype=np.float64)
        row_count, dimensions = features.shape

        # standardize from training data only (constant columns -> scale 1)
        mean = features.mean(axis=0)
        scale = features.std(axis=0)
        scale[scale == 0.0] = 1.0
        standardized = (features - mean) / scale

        positives = float(labels.sum())
        negatives = float(row_count) - positives
        class_weights = np.where(
            labels == 1.0,
            row_count / (2.0 * positives) if positives else 0.0,
            row_count / (2.0 * negatives) if negatives else 0.0,
        )

        coefficients = np.zeros(dimensions, dtype=np.float64)
        bias = 0.0
        for _ in range(self.epochs):
            logits = standardized @ coefficients + bias
            predictions = 1.0 / (1.0 + np.exp(-np.clip(logits, -500.0, 500.0)))
            errors = (predictions - labels) * class_weights
            gradient = standardized.T @ errors / row_count + self.l2 * coefficients
            coefficients = coefficients - self.learning_rate * gradient
            bias -= self.learning_rate * float(errors.mean())

        self._weights = coefficients.tolist()
        self._bias = bias
        self._mean = mean.tolist()
        self._scale = scale.tolist()

    def score(self, pair: CandidatePair) -> float:
        if self._weights is None or self._mean is None or self._scale is None:
            raise RuntimeError(f"{self.name} must be fit before scoring")
        vector = pair.features.as_vector()
        standardized = [
            (value - mean_column) / scale_column
            for value, mean_column, scale_column in zip(
                vector, self._mean, self._scale, strict=True
            )
        ]
        logit = sum(
            coefficient * value
            for coefficient, value in zip(self._weights, standardized, strict=True)
        )
        return _sigmoid(logit + self._bias)


@dataclass
class XgboostBaseline(ResolutionBaseline):
    """Plan baseline 5: XGBoost gradient-boosted trees over the nine features.

    The ``xgboost`` dependency is installed platform-appropriately
    (``xgboost-cpu`` on Linux/Windows CI to avoid CUDA payloads) and
    imported lazily so import errors surface as a clear runtime message.
    """

    name: ClassVar[str] = "xgboost"

    estimators: int = 80
    max_depth: int = 3
    learning_rate: float = 0.15

    def __post_init__(self) -> None:
        self._model: Booster | None = None

    @property
    def fitted(self) -> bool:
        return self._model is not None

    def fit(self, pairs: Sequence[CandidatePair]) -> None:
        if not pairs:
            raise ValueError("cannot fit XGBoost on an empty pair set")
        try:
            from xgboost import DMatrix, train  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - only without optional dep
            raise RuntimeError(
                "xgboost is required for XgboostBaseline; install project dependencies"
            ) from exc

        import numpy as np  # noqa: PLC0415 - lazy: keeps import cost off the package path

        features = np.asarray([pair.features.as_vector() for pair in pairs], dtype=np.float64)
        labels = np.asarray([pair.label for pair in pairs], dtype=np.float32)
        # nthread=1 on DMatrix as well as in params: params only throttles the
        # booster, whereas DMatrix's own OpenMP team (SparsePage::Push) is
        # sized separately and is what crashes when another native library in
        # the process ships its own copy of libomp.
        dtrain = DMatrix(features, label=labels, nthread=1)
        params: dict[str, object] = {
            "max_depth": self.max_depth,
            "eta": self.learning_rate,
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "seed": RANDOM_SEED,
            "nthread": 1,
            "verbosity": 0,
        }
        # native Booster API: no scikit-learn requirement
        self._model = train(params, dtrain, num_boost_round=self.estimators)

    def score(self, pair: CandidatePair) -> float:
        if self._model is None:
            raise RuntimeError(f"{self.name} must be fit before scoring")
        import numpy as np  # noqa: PLC0415
        from xgboost import DMatrix  # noqa: PLC0415

        features = np.asarray([pair.features.as_vector()], dtype=np.float64)
        probabilities = self._model.predict(DMatrix(features, nthread=1))
        return float(probabilities[0])


def all_baselines() -> list[ResolutionBaseline]:
    """The five plan baselines in specification order (baselines 1-5)."""
    return [
        ExactHandleBaseline(),
        EditDistanceBaseline(),
        TfIdfCosineBaseline(),
        LogisticRegressionBaseline(),
        XgboostBaseline(),
    ]
