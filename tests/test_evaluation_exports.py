"""Public API of :mod:`aegis.evaluation` (L1): every documented export
imports from the package root and the key callables actually work."""

from __future__ import annotations

import aegis.evaluation as evaluation
from aegis.evaluation import (
    BenchmarkResult,
    EvaluationMetrics,
    ScenarioBuilder,
    ScenarioResult,
    SyntheticBenchmark,
    SyntheticBenchmarkRunner,
    SyntheticEvaluator,
)
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator

EXPECTED_EXPORTS = [
    "BenchmarkResult",
    "EvaluationMetrics",
    "ScenarioBuilder",
    "ScenarioResult",
    "SyntheticBenchmark",
    "SyntheticBenchmarkRunner",
    "SyntheticEvaluator",
]


def test_all_exports_are_importable_and_listed() -> None:
    assert sorted(evaluation.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert getattr(evaluation, name) is not None


def test_evaluator_scores_against_explicit_ground_truth() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    truth = SyntheticBenchmark.ground_truth_pairs(actors)

    metrics = SyntheticEvaluator().evaluate(
        predicted_pairs=truth,
        ground_truth_pairs=truth,
        all_actor_ids={actor.actor_id for actor in actors},
    )

    assert isinstance(metrics, EvaluationMetrics)
    assert metrics.f1 == 1.0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0


def test_scenario_builder_returns_the_five_frozen_scenarios() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    scenarios = ScenarioBuilder().build(evidence)

    assert [scenario.name for scenario in scenarios] == [
        "clean_strong",
        "clean_weak",
        "contradictory",
        "noisy_match",
        "no_match",
    ]
    assert all(isinstance(scenario, ScenarioResult) for scenario in scenarios)


def test_benchmark_runner_returns_reproducible_records() -> None:
    results = SyntheticBenchmarkRunner().run([26151], actor_count=4)

    assert len(results) == 1
    assert isinstance(results[0], BenchmarkResult)
    assert results[0].seed == 26151
    assert results[0].actor_count == 4
    assert isinstance(results[0].metrics, EvaluationMetrics)
