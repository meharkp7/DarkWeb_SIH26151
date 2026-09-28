"""Train and compare Phase 16 baselines with Phase 19 GNN pair heads.

The default run creates a deterministic, controlled synthetic graph with
actor-disjoint train/validation/test groups. It is a pipeline smoke benchmark,
not evidence of real-world attribution performance.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import cast

import numpy as np

from aegis.attribution.baseline import AttributionExample, all_baselines
from aegis.attribution.evaluation import _metrics
from aegis.attribution.signals import ChannelSignals
from aegis.gnn.graph import GnnNodeType, HeteroGraph
from aegis.gnn.models import HGTEncoder, RGCNEncoder, TemporalHGTEncoder
from aegis.gnn.training import GnnPairTrainer, LabeledNodePair
from aegis.ontology import RelationshipType


def _dataset(seed: int, groups: int) -> tuple[HeteroGraph, dict[str, list[tuple[str, str, int]]]]:
    if groups < 6:
        raise ValueError("at least 6 groups required for non-empty train/validation/test cohorts")
    rng = np.random.default_rng(seed)
    graph = HeteroGraph()
    hub_id = "evidence:shared-context"
    start = datetime(2026, 1, 1, tzinfo=UTC)
    actors: list[tuple[str, np.ndarray]] = []
    graph.add_node(hub_id, GnnNodeType.EVIDENCE, observed_at=start)
    grouped: dict[str, list[tuple[str, str, int]]] = {"train": [], "validation": [], "test": []}
    train_end = int(groups * 0.6)
    validation_end = int(groups * 0.8)

    for group in range(groups):
        base = rng.uniform(0.05, 0.95, 6)
        vectors = [
            np.clip(base + rng.normal(0.0, 0.02, 6), 0.0, 1.0),
            np.clip(base + rng.normal(0.0, 0.02, 6), 0.0, 1.0),
            rng.uniform(0.05, 0.95, 6),
            rng.uniform(0.05, 0.95, 6),
        ]
        ids = [f"actor-g{group:03d}-{index}" for index in range(4)]
        for index, (actor_id, vector) in enumerate(zip(ids, vectors, strict=True)):
            graph.add_node(
                actor_id, GnnNodeType.ACTOR, observed_at=start + timedelta(days=index + group)
            )
            graph.add_edge(
                RelationshipType.OBSERVED_AT,
                actor_id,
                hub_id,
                observed_at=start + timedelta(days=index + group),
            )
            actors.append((actor_id, vector))
        split = "train" if group < train_end else "validation" if group < validation_end else "test"
        for left, right in combinations(ids, 2):
            grouped[split].append((left, right, int(left == ids[0] and right == ids[1])))

    actor_features = np.asarray([vector for _, vector in actors], dtype=np.float64)
    graph.set_features(GnnNodeType.ACTOR, actor_features)
    graph.set_features(GnnNodeType.EVIDENCE, np.ones((1, 6), dtype=np.float64))
    graph.compile()
    return graph, grouped


def _pair_examples(
    rows: list[tuple[str, str, int]], features: dict[str, np.ndarray]
) -> list[AttributionExample]:
    results = []
    for source, target, label in rows:
        left, right = features[source], features[target]
        similarity = np.clip(1.0 - np.abs(left - right), 0.0, 1.0)
        results.append(
            AttributionExample(
                pair_id=f"{source}:{target}",
                signals=ChannelSignals(*[float(value) for value in similarity]),
                label=label,
            )
        )
    return results


def run(seed: int, groups: int, epochs: int) -> dict[str, object]:
    graph, splits = _dataset(seed, groups)
    feature_by_id = {
        node.node_id: graph.features(GnnNodeType.ACTOR)[index]
        for index, node in enumerate(
            node for node in graph.nodes if node.node_type is GnnNodeType.ACTOR
        )
    }
    train_rows, validation_rows, test_rows = splits["train"], splits["validation"], splits["test"]
    baseline_train = _pair_examples(train_rows, feature_by_id)
    baseline_validation = _pair_examples(validation_rows, feature_by_id)
    baseline_test = _pair_examples(test_rows, feature_by_id)
    comparisons: list[dict[str, object]] = []

    for baseline in all_baselines():
        baseline.fit(baseline_train)
        validation_scores = [baseline.score(item).raw_score for item in baseline_validation]
        test_scores = [baseline.score(item).raw_score for item in baseline_test]
        comparisons.append(
            {
                "model": baseline.name,
                "model_version": baseline.version,
                "validation": _metrics(
                    [item.label for item in baseline_validation], validation_scores
                ),
                "test": _metrics([item.label for item in baseline_test], test_scores),
            }
        )

    pair_train = [LabeledNodePair(source, target, label) for source, target, label in train_rows]
    for encoder_type in (RGCNEncoder, HGTEncoder, TemporalHGTEncoder):
        encoder = encoder_type(seed=seed).fit(graph)
        trainer = GnnPairTrainer(encoder, epochs=epochs).fit(pair_train)
        for split_name, rows in (("validation", validation_rows), ("test", test_rows)):
            predictions = [trainer.predict(source, target).raw_score for source, target, _ in rows]
            labels = [label for _, _, label in rows]
            if split_name == "validation":
                validation_metrics = _metrics(labels, predictions)
            else:
                test_metrics = _metrics(labels, predictions)
        comparisons.append(
            {
                "model": f"{encoder.model_id}-trained-pair-head",
                "model_version": "phase-19-reference-0.2",
                "validation": validation_metrics,
                "test": test_metrics,
                "training_scope": "supervised pair head; fixed deterministic graph encoder",
            }
        )

    return {
        "seed": seed,
        "groups": groups,
        "graph_nodes": graph.node_count,
        "graph_edges": graph.edge_count,
        "split_pair_counts": {name: len(rows) for name, rows in splits.items()},
        "split_actor_disjoint": True,
        "results": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=26151)
    parser.add_argument("--groups", type=int, default=30)
    parser.add_argument("--epochs", type=int, default=400)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/training/phase19-comparison.json")
    )
    args = parser.parse_args()
    result = run(args.seed, args.groups, args.epochs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"training comparison written to {args.output}")
    for item in cast(list[dict[str, object]], result["results"]):
        test = cast(dict[str, float], item["test"])
        print(f"{item['model']}: test F1={test['f1']:.3f}, ROC-AUC={test['roc_auc']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
