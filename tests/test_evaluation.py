from aegis.evaluation.benchmark import SyntheticBenchmark
from aegis.evaluation.metrics import SyntheticEvaluator
from aegis.synthetic.generator import SyntheticActorGenerator


def test_benchmark_ground_truth_is_explicit() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(4)

    truth = SyntheticBenchmark.ground_truth_pairs(actors)

    assert truth == {
        ("actor-0001", "actor-0002"),
        ("actor-0003", "actor-0004"),
    }


def test_perfect_predictions() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    truth = SyntheticBenchmark.ground_truth_pairs(actors)

    metrics = SyntheticEvaluator().evaluate(
        predicted_pairs=truth,
        ground_truth_pairs=truth,
        all_actor_ids={actor.actor_id for actor in actors},
    )

    assert metrics.true_positives == 2
    assert metrics.false_positives == 0
    assert metrics.false_negatives == 0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0


def test_partial_predictions() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    truth = SyntheticBenchmark.ground_truth_pairs(actors)

    metrics = SyntheticEvaluator().evaluate(
        predicted_pairs={("actor-0001", "actor-0002")},
        ground_truth_pairs=truth,
        all_actor_ids={actor.actor_id for actor in actors},
    )

    assert metrics.true_positives == 1
    assert metrics.false_positives == 0
    assert metrics.false_negatives == 1
    assert metrics.precision == 1.0
    assert metrics.recall == 0.5
    assert metrics.f1 == 0.667


def test_benchmark_runner_is_deterministic() -> None:
    from aegis.evaluation.runner import SyntheticBenchmarkRunner

    runner = SyntheticBenchmarkRunner()

    first = runner.run([26151, 26152, 26153])
    second = runner.run([26151, 26152, 26153])

    assert first == second
    assert len(first) == 3
