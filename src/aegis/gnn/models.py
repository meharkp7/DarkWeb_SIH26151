"""Deterministic NumPy reference models for Phase 19.

These models deliberately favour inspectability over framework-specific magic.
They provide the required R-GCN, HGT and temporal-HGT comparison points on the
compiled :class:`~aegis.gnn.graph.HeteroGraph`; production training can replace
the encoders without changing the graph or pair-scoring contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np

from aegis.attribution.signals import sigmoid
from aegis.gnn.graph import FloatArray, HeteroGraph


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _softmax(values: FloatArray) -> FloatArray:
    shifted = values - np.max(values)
    exp = np.exp(np.clip(shifted, -500.0, 500.0))
    return cast(FloatArray, exp / exp.sum())


@dataclass(frozen=True)
class PairPrediction:
    """A reproducible same-activity hypothesis score, not a calibrated probability."""

    source_id: str
    target_id: str
    raw_score: float
    model_id: str
    model_version: str = "phase-19.0"


class _BaseEncoder:
    model_id = "base"

    def __init__(self, hidden_dim: int = 16, seed: int = 26151) -> None:
        if hidden_dim < 1:
            raise ValueError("hidden_dim must be positive")
        self.hidden_dim = hidden_dim
        self.seed = seed
        self._graph: HeteroGraph | None = None
        self._embeddings: FloatArray | None = None

    def fit(self, graph: HeteroGraph) -> _BaseEncoder:
        """Compile and encode a graph. No labels are consumed by the encoder."""
        graph.compile()
        self._graph = graph
        self._embeddings = self._encode(graph)
        return self

    def embeddings(self, graph: HeteroGraph | None = None) -> FloatArray:
        if graph is not None and graph is not self._graph:
            self.fit(graph)
        if self._embeddings is None:
            if self._graph is None:
                raise RuntimeError("fit(graph) must run before embeddings()")
            self.fit(self._graph)
        embeddings = self._embeddings
        if embeddings is None:  # defensive narrowing for static type checkers
            raise RuntimeError("encoder did not produce embeddings")
        return embeddings.copy()

    def predict_pair(self, source_id: str, target_id: str) -> PairPrediction:
        if self._graph is None or self._embeddings is None:
            raise RuntimeError("fit(graph) must run before predict_pair()")
        if source_id == target_id:
            raise ValueError("candidate pair requires two distinct node ids")
        left = self._embeddings[self._graph.node_index(source_id)]
        right = self._embeddings[self._graph.node_index(target_id)]
        cosine = float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right) + 1e-12))
        return PairPrediction(source_id, target_id, round(sigmoid(2.0 * cosine), 6), self.model_id)

    def _initial_features(self, graph: HeteroGraph) -> FloatArray:
        generator = _rng(self.seed)
        output = np.zeros((graph.node_count, self.hidden_dim), dtype=np.float64)
        for node_type in graph.node_types:
            features = graph.features(node_type)
            projection = generator.normal(
                0.0, 1.0 / math.sqrt(features.shape[1]), (features.shape[1], self.hidden_dim)
            )
            output[graph.rows_for(node_type)] = np.tanh(features @ projection)
        return output

    def _encode(self, graph: HeteroGraph) -> FloatArray:
        raise NotImplementedError


class RGCNEncoder(_BaseEncoder):
    """One-layer relation-aware graph convolution with degree normalisation."""

    model_id = "r-gcn"

    def _encode(self, graph: HeteroGraph) -> FloatArray:
        state = self._initial_features(graph)
        generator = _rng(self.seed + 1)
        self_weight = generator.normal(
            0.0, 1.0 / math.sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)
        )
        relation_weights = [
            generator.normal(
                0.0, 1.0 / math.sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)
            )
            for _ in graph.relations
        ]
        aggregate = np.zeros_like(state)
        counts = np.zeros(graph.node_count, dtype=np.float64)
        for relation_id, edge_indices in enumerate(graph.relation_groups):
            sources = graph.message_sources[edge_indices]
            targets = graph.message_targets[edge_indices]
            messages = state[sources] @ relation_weights[relation_id]
            np.add.at(aggregate, targets, messages)
            np.add.at(counts, targets, 1.0)
        aggregate /= np.maximum(counts[:, None], 1.0)
        return np.tanh(state @ self_weight + aggregate)


class HGTEncoder(_BaseEncoder):
    """One-layer heterogeneous graph transformer reference encoder."""

    model_id = "hgt"

    def _edge_weight(self, graph: HeteroGraph, edge_index: int) -> float:
        del graph, edge_index
        return 1.0

    def _encode(self, graph: HeteroGraph) -> FloatArray:
        state = self._initial_features(graph)
        generator = _rng(self.seed + 2)
        query = generator.normal(
            0.0, 1.0 / math.sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)
        )
        key = generator.normal(
            0.0, 1.0 / math.sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)
        )
        value = generator.normal(
            0.0, 1.0 / math.sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)
        )
        relation = [
            generator.normal(
                0.0, 1.0 / math.sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)
            )
            for _ in graph.relations
        ]
        aggregate = np.zeros_like(state)
        # The graph's precomputed layout keeps each target's neighbours contiguous.
        ordered = graph.segment_layout.order
        for start, count in zip(
            graph.segment_layout.starts, graph.segment_layout.counts, strict=True
        ):
            indices = ordered[start : start + count]
            target = int(graph.message_targets[indices[0]])
            sources = graph.message_sources[indices]
            rel_ids = graph.message_relation_ids[indices]
            keys = np.vstack(
                [
                    state[source] @ key @ relation[rel]
                    for source, rel in zip(sources, rel_ids, strict=True)
                ]
            )
            values = np.vstack(
                [
                    state[source] @ value @ relation[rel]
                    for source, rel in zip(sources, rel_ids, strict=True)
                ]
            )
            logits = keys @ (state[target] @ query) / math.sqrt(self.hidden_dim)
            logits += np.log(
                np.asarray([self._edge_weight(graph, int(index)) for index in indices])
            )
            aggregate[target] = _softmax(logits) @ values
        return np.tanh(state + aggregate)


class TemporalHGTEncoder(HGTEncoder):
    """HGT with an exponential temporal-fit discount on every message."""

    model_id = "temporal-hgt"

    def __init__(
        self, hidden_dim: int = 16, seed: int = 26151, half_life_days: float = 30.0
    ) -> None:
        super().__init__(hidden_dim, seed)
        if half_life_days <= 0.0:
            raise ValueError("half_life_days must be positive")
        self.half_life_days = half_life_days

    def _edge_weight(self, graph: HeteroGraph, edge_index: int) -> float:
        target = int(graph.message_targets[edge_index])
        age = abs(float(graph.message_days[edge_index] - graph.node_days[target]))
        return max(math.exp(-math.log(2.0) * age / self.half_life_days), 1e-12)


class ContradictionAwareTemporalHGT(TemporalHGTEncoder):
    """Temporal HGT whose pair score is reduced by supplied contradiction weight."""

    model_id = "temporal-hgt-contradiction"

    def predict_pair(
        self, source_id: str, target_id: str, *, contradiction_weight: float = 0.0
    ) -> PairPrediction:
        if not math.isfinite(contradiction_weight) or contradiction_weight < 0.0:
            raise ValueError("contradiction_weight must be finite and non-negative")
        prediction = super().predict_pair(source_id, target_id)
        logit = math.log(prediction.raw_score / (1.0 - prediction.raw_score)) - contradiction_weight
        return PairPrediction(source_id, target_id, round(sigmoid(logit), 6), self.model_id)
