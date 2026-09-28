"""Reproducible benchmark runner: one deterministic run per seed."""

from dataclasses import dataclass
from time import perf_counter

from aegis.evaluation.benchmark import SyntheticBenchmark
from aegis.evaluation.metrics import EvaluationMetrics, SyntheticEvaluator
from aegis.synthetic.candidate_links import CandidateLinkEngine
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator


@dataclass(frozen=True)
class BenchmarkResult:
    seed: int
    actor_count: int
    metrics: EvaluationMetrics
    evidence_count: int = 0
    candidate_count: int = 0
    generation_ms: float = 0.0
    candidate_generation_ms: float = 0.0


class SyntheticBenchmarkRunner:
    """Run reproducible evaluation across multiple synthetic seeds."""

    def run(
        self,
        seeds: list[int],
        actor_count: int = 4,
    ) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []

        for seed in seeds:
            generation_started = perf_counter()
            actors = SyntheticActorGenerator(seed=seed).generate(actor_count)
            evidence, _ = SyntheticEvidenceGenerator(seed=seed).generate(actors)
            generation_ms = (perf_counter() - generation_started) * 1000.0

            candidate_started = perf_counter()
            candidates = CandidateLinkEngine().generate(
                evidence,
                min_score=0.0,
            )
            candidate_generation_ms = (perf_counter() - candidate_started) * 1000.0

            predicted = {
                (candidate.source_actor_id, candidate.target_actor_id)
                for candidate in candidates
                if candidate.score > 0.0
            }

            truth = SyntheticBenchmark.ground_truth_pairs(actors)

            metrics = SyntheticEvaluator().evaluate(
                predicted_pairs=predicted,
                ground_truth_pairs=truth,
                all_actor_ids={actor.actor_id for actor in actors},
            )

            results.append(
                BenchmarkResult(
                    seed=seed,
                    actor_count=actor_count,
                    metrics=metrics,
                    evidence_count=len(evidence),
                    candidate_count=len(candidates),
                    generation_ms=round(generation_ms, 3),
                    candidate_generation_ms=round(candidate_generation_ms, 3),
                )
            )

        return results
