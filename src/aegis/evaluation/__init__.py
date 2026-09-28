"""Evaluation harness (Phase 04/16): synthetic benchmark ground truth,
metrics, scenarios, and the reproducible runner.

The package answers one question — *"does the system get better?"* —
with deterministic, synthetic-only fixtures:

-   :class:`~aegis.evaluation.benchmark.SyntheticBenchmark` declares the
    explicit ground-truth actor pairs of the controlled benchmark.
-   :class:`~aegis.evaluation.metrics.SyntheticEvaluator` scores
    predicted pairs against that ground truth (precision, recall, F1,
    FPR) with the same safe-division semantics as
    ``aegis.resolution.metrics``.
-   :class:`~aegis.evaluation.scenarios.ScenarioBuilder` builds the five
    frozen scenario variations (clean strong/weak, contradictory, noisy,
    no-match) the pipeline is measured on.
-   :class:`~aegis.evaluation.runner.SyntheticBenchmarkRunner` runs the
    whole loop across seeds and returns reproducible
    :class:`~aegis.evaluation.runner.BenchmarkResult` records.

Evaluation is synthetic-only: no live data enters the harness.
"""

from aegis.evaluation.benchmark import SyntheticBenchmark
from aegis.evaluation.metrics import EvaluationMetrics, SyntheticEvaluator
from aegis.evaluation.runner import BenchmarkResult, SyntheticBenchmarkRunner
from aegis.evaluation.scenarios import ScenarioBuilder, ScenarioResult

__all__ = [
    "BenchmarkResult",
    "EvaluationMetrics",
    "ScenarioBuilder",
    "ScenarioResult",
    "SyntheticBenchmark",
    "SyntheticBenchmarkRunner",
    "SyntheticEvaluator",
]
