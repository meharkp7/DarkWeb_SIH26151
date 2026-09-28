"""Evaluate L1–L5 synthetic persona migrations with leakage-safe split checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

from aegis.evaluation.benchmark import actor_disjoint_split
from aegis.evaluation.metrics import EvaluationMetrics, SyntheticEvaluator
from aegis.evaluation.protocols import platform_disjoint_split, temporal_split
from aegis.synthetic.actor import SyntheticActor
from aegis.synthetic.candidate_links import CandidateLink, CandidateLinkEngine
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.persona_simulator import AdversarialPersonaSimulator, MigrationLevel


def _pairs(candidates: Sequence[CandidateLink]) -> set[tuple[str, str]]:
    return {
        (candidate.source_actor_id, candidate.target_actor_id)
        for candidate in candidates
        if candidate.score > 0.0
    }


def _evaluate_pairing(
    seed: int, originals: list[SyntheticActor], migrated: list[SyntheticActor], label: str
) -> EvaluationMetrics:
    generator = SyntheticEvidenceGenerator(seed=seed)
    original_evidence, _ = generator.generate(originals)
    migrated_evidence, _ = generator.generate(migrated)
    candidates = CandidateLinkEngine().generate(
        original_evidence + migrated_evidence, min_score=0.0
    )
    truth = {(actor.actor_id, f"{actor.actor_id}:{label}") for actor in originals}
    actor_ids = {actor.actor_id for actor in originals + migrated}
    return SyntheticEvaluator().evaluate(_pairs(candidates), truth, actor_ids)


def _evaluate_clean(seed: int, actors: int) -> EvaluationMetrics:
    originals = SyntheticActorGenerator(seed=seed).generate(actors)
    clones = [replace(actor, actor_id=f"{actor.actor_id}:clean") for actor in originals]
    return _evaluate_pairing(seed, originals, clones, "clean")


def _evaluate_level(seed: int, actors: int, level: MigrationLevel) -> EvaluationMetrics:
    originals = SyntheticActorGenerator(seed=seed).generate(actors)
    migrations = AdversarialPersonaSimulator().generate(originals, level)
    migrated = [
        replace(migration.migrated, actor_id=f"{migration.actor_id}:migration-l{level}")
        for migration in migrations
    ]
    return _evaluate_pairing(seed, originals, migrated, f"migration-l{level}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=26151)
    parser.add_argument("--actors", type=int, default=12)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/adversarial-migration.json")
    )
    args = parser.parse_args()
    if args.actors < 4:
        parser.error("--actors must be at least 4")

    originals = SyntheticActorGenerator(seed=args.seed).generate(args.actors)
    evidence, _ = SyntheticEvidenceGenerator(seed=args.seed).generate(originals)
    actor_train, actor_test = actor_disjoint_split(originals)
    cutoff = min(item.observed_at for item in evidence) + timedelta(days=15)
    temporal = temporal_split(evidence, cutoff)
    held_out = {sorted({item.platform for item in evidence if item.platform != "synthetic"})[-1]}
    platform = platform_disjoint_split(evidence, held_out)

    results: list[dict[str, object]] = []
    clean_metrics = _evaluate_clean(args.seed, args.actors)
    baseline_f1 = clean_metrics.f1
    for level in MigrationLevel:
        metrics = _evaluate_level(args.seed, args.actors, level)
        results.append(
            {
                "level": level.name,
                "changed_modalities": list(
                    AdversarialPersonaSimulator().migrate(originals[0], level).changed_modalities
                ),
                "metrics": asdict(metrics),
                "f1_degradation_from_clean": round(max(0.0, baseline_f1 - metrics.f1), 3),
            }
        )
        print(
            f"{level.name}: F1={metrics.f1:.3f} recall={metrics.recall:.3f} "
            f"false-association-rate={metrics.false_association_rate:.3f} "
            f"degradation={max(0.0, baseline_f1 - metrics.f1):.3f}"
        )

    report = {
        "seed": args.seed,
        "actor_count": args.actors,
        "method": "candidate-link baseline; synthetic-only; no trained-model claim",
        "clean_clone_baseline": asdict(clean_metrics),
        "split_checks": {
            "actor_disjoint": {"train_actors": len(actor_train), "test_actors": len(actor_test)},
            "temporal": {
                "train_evidence": len(temporal.train),
                "test_evidence": len(temporal.test),
            },
            "platform_disjoint": {
                "held_out_platforms": sorted(held_out),
                "train_evidence": len(platform.train),
                "test_evidence": len(platform.test),
            },
        },
        "migration_ladder": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"adversarial evaluation written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
