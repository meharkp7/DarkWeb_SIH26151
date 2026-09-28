"""Run the learned Phase 19 Temporal-HGT smoke/research training path.

This command intentionally uses a small synthetic graph. Production experiments
should build a point-in-time HeteroGraph through ``build_gnn_graph`` using
feature vectors computed only from data available at each cutoff.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aegis.gnn.graph import HeteroGraph
from aegis.gnn.store_adapter import build_gnn_graph
from aegis.gnn.torch_models import TemporalHeterogeneousGNN
from aegis.gnn.torch_training import TemporalPair, split_by_group, train_pair_model
from aegis.graph import InMemoryGraphStore, NodeLabel
from aegis.ontology import EntityType, RelationshipType


def build_synthetic_graph(groups: int, seed: int) -> tuple[HeteroGraph, list[TemporalPair]]:
    del seed
    if groups < 6:
        raise ValueError("at least 6 groups are required")
    store = InMemoryGraphStore()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    features: dict[str, list[float]] = {}
    times: dict[str, datetime] = {}
    pairs: list[TemporalPair] = []

    for group in range(groups):
        handle_id = f"handle:{group:04d}"
        store.add_node(handle_id, NodeLabel.HANDLE, entity_type=EntityType.HANDLE)
        features[handle_id] = [float(group % 2), 1.0]
        times[handle_id] = start + timedelta(days=group)
        actors = [f"actor:{group:04d}:{index}" for index in range(4)]
        for index, actor_id in enumerate(actors):
            store.add_node(actor_id, NodeLabel.ACTOR, entity_type=EntityType.ACTOR_HYPOTHESIS)
            features[actor_id] = [1.0 if index < 2 else 0.0, float(index) / 3.0]
            observed = start + timedelta(days=group, hours=index)
            times[actor_id] = observed
            store.add_edge(
                RelationshipType.USES_HANDLE,
                actor_id,
                handle_id,
                first_seen=observed,
                last_seen=observed + timedelta(days=30),
                confidence=0.9,
                evidence_ids=[f"evidence:{group}:{index}"],
            )
        pairs.extend(
            [
                TemporalPair(actors[0], actors[1], 1, f"actor-group:{group}"),
                TemporalPair(actors[0], actors[2], 0, f"actor-group:{group}"),
                TemporalPair(actors[1], actors[3], 0, f"actor-group:{group}"),
            ]
        )

    graph = build_gnn_graph(store, features=features, observed_at=times)
    return graph, pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", type=int, default=12)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--seed", type=int, default=26151)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/training/phase19-temporal-gnn.json")
    )
    args = parser.parse_args()

    graph, pairs = build_synthetic_graph(args.groups, args.seed)
    split = split_by_group(pairs, seed=args.seed)
    model = TemporalHeterogeneousGNN(graph, hidden_dim=32, heads=4, layers=2)
    result = train_pair_model(
        model,
        split.train,
        split.validation,
        split.test,
        epochs=args.epochs,
        seed=args.seed,
    )
    payload = {
        "model_id": model.model_id,
        "model_version": model.model_version,
        "seed": args.seed,
        "graph_nodes": graph.node_count,
        "graph_edges": graph.edge_count,
        "train_pairs": len(split.train),
        "validation_pairs": len(split.validation),
        "test_pairs": len(split.test),
        "best_epoch": result.best_epoch,
        "best_validation_loss": result.best_validation_loss,
        "test_scores": list(result.test_scores),
        "raw_score_is_not_calibrated_probability": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
