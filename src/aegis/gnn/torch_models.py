"""Trainable temporal heterogeneous GNN for Phase 19.

This module uses core PyTorch only; PyG/DGL are intentionally avoided so the
model has a small, auditable dependency surface.  The NumPy models remain the
reproducible reference baselines.  This module is the learned model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import torch
from torch import Tensor, nn

from aegis.gnn.graph import HeteroGraph


@dataclass(frozen=True)
class TorchPairPrediction:
    source_id: str
    target_id: str
    raw_score: float
    model_id: str
    model_version: str


class _TemporalHGTLayer(nn.Module):
    def __init__(
        self, hidden_dim: int, relation_count: int, heads: int, node_type_count: int
    ) -> None:
        super().__init__()
        if hidden_dim % heads:
            raise ValueError("hidden_dim must be divisible by heads")
        self.hidden_dim = hidden_dim
        self.heads = heads
        self.head_dim = hidden_dim // heads
        self.query = nn.ModuleList(
            nn.Linear(hidden_dim, hidden_dim, bias=False) for _ in range(node_type_count)
        )
        self.key = nn.ModuleList(
            nn.Linear(hidden_dim, hidden_dim, bias=False) for _ in range(relation_count)
        )
        self.value = nn.ModuleList(
            nn.Linear(hidden_dim, hidden_dim, bias=False) for _ in range(relation_count)
        )
        self.relation_bias = nn.Parameter(torch.zeros(relation_count, heads))
        self.self_proj = nn.Linear(hidden_dim, hidden_dim)
        self.out = nn.Linear(hidden_dim, hidden_dim)
        self.norm = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(0.1)

    def forward(
        self,
        x: Tensor,
        source: Tensor,
        target: Tensor,
        relation: Tensor,
        temporal_weight: Tensor,
        node_type_ids: Tensor,
    ) -> Tensor:
        q = torch.zeros_like(x)
        for type_id, query_layer in enumerate(self.query):
            mask = node_type_ids == type_id
            if bool(mask.any()):
                q[mask] = query_layer(x[mask])
        q = q.view(-1, self.heads, self.head_dim)
        aggregate = torch.zeros_like(x)
        for relation_id, (key_layer, value_layer) in enumerate(
            zip(self.key, self.value, strict=True)
        ):
            mask = relation == relation_id
            if not bool(mask.any()):
                continue
            src = source[mask]
            dst = target[mask]
            k = key_layer(x[src]).view(-1, self.heads, self.head_dim)
            v = value_layer(x[src]).view(-1, self.heads, self.head_dim)
            scores = (q[dst] * k).sum(-1) / math.sqrt(self.head_dim)
            scores = scores + self.relation_bias[relation_id]
            scores = scores + torch.log(temporal_weight[mask].clamp_min(1e-8)).unsqueeze(-1)
            for node_id in torch.unique(dst, sorted=True):
                local = dst == node_id
                weights = torch.softmax(scores[local], dim=0)
                message = (weights.unsqueeze(-1) * v[local]).sum(0).reshape(self.hidden_dim)
                aggregate[node_id] = aggregate[node_id] + message
        updated = self.self_proj(x) + self.out(aggregate)
        return cast(Tensor, self.norm(x + self.dropout(torch.nn.functional.gelu(updated))))


class TemporalHeterogeneousGNN(nn.Module):
    """Two-layer relation-aware temporal HGT with a pair classifier."""

    model_id = "temporal-hgt-learned"
    model_version = "phase-19.1"

    def __init__(
        self,
        graph: HeteroGraph,
        *,
        hidden_dim: int = 64,
        heads: int = 4,
        layers: int = 2,
        half_life_days: float = 30.0,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if hidden_dim < 8 or hidden_dim % heads:
            raise ValueError("hidden_dim must be >= 8 and divisible by heads")
        if layers < 1 or half_life_days <= 0:
            raise ValueError("layers must be positive and half_life_days must be positive")
        graph.compile()
        self.graph = graph
        self.hidden_dim = hidden_dim
        self.half_life_days = half_life_days
        self.input_proj = nn.ModuleDict(
            {
                node_type.value: nn.Linear(graph.input_dims[node_type], hidden_dim)
                for node_type in graph.node_types
            }
        )
        self.type_embedding = nn.Embedding(len(graph.node_types), hidden_dim)
        self.time_proj = nn.Linear(4, hidden_dim)
        self.layers = nn.ModuleList(
            _TemporalHGTLayer(hidden_dim, len(graph.relations), heads, len(graph.node_types))
            for _ in range(layers)
        )
        self.dropout = nn.Dropout(dropout)
        self.pair_head = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def encode(self) -> Tensor:
        x = torch.zeros(
            (self.graph.node_count, self.hidden_dim),
            dtype=torch.float32,
            device=self.type_embedding.weight.device,
        )
        for _type_id, node_type in enumerate(self.graph.node_types):
            rows = torch.as_tensor(
                self.graph.rows_for(node_type), dtype=torch.long, device=x.device
            )
            features = torch.as_tensor(
                self.graph.features(node_type), dtype=torch.float32, device=x.device
            )
            x[rows] = self.input_proj[node_type.value](features)
        type_ids = torch.as_tensor(self.graph.node_type_ids, dtype=torch.long, device=x.device)
        days = torch.as_tensor(
            self.graph.node_days - self.graph.reference_day,
            dtype=torch.float32,
            device=x.device,
        )
        phase = days.unsqueeze(1) / torch.tensor([7.0, 30.0], device=x.device)
        temporal = torch.cat((torch.sin(phase), torch.cos(phase)), dim=1)
        x = x + self.type_embedding(type_ids) + self.time_proj(temporal)

        source = torch.as_tensor(self.graph.message_sources, dtype=torch.long, device=x.device)
        target = torch.as_tensor(self.graph.message_targets, dtype=torch.long, device=x.device)
        relation = torch.as_tensor(
            self.graph.message_relation_ids, dtype=torch.long, device=x.device
        )
        node_type_ids = torch.as_tensor(self.graph.node_type_ids, dtype=torch.long, device=x.device)
        edge_days = torch.as_tensor(self.graph.message_days, dtype=torch.float32, device=x.device)
        target_days = torch.as_tensor(self.graph.node_days, dtype=torch.float32, device=x.device)
        age = (edge_days - target_days[target]).abs()
        temporal_weight = torch.exp(-math.log(2.0) * age / self.half_life_days)
        for layer in self.layers:
            x = layer(x, source, target, relation, temporal_weight, node_type_ids)
        return cast(Tensor, self.dropout(x))

    def pair_logit(self, embeddings: Tensor, source_id: str, target_id: str) -> Tensor:
        source = embeddings[self.graph.node_index(source_id)]
        target = embeddings[self.graph.node_index(target_id)]
        pair = torch.cat((torch.abs(source - target), source * target), dim=0)
        return cast(Tensor, self.pair_head(pair).squeeze(-1))

    def pair_score(
        self, source_id: str, target_id: str, *, contradiction_weight: float = 0.0
    ) -> Tensor:
        if source_id == target_id:
            raise ValueError("candidate pair requires two distinct node ids")
        if contradiction_weight < 0.0 or not math.isfinite(contradiction_weight):
            raise ValueError("contradiction_weight must be finite and non-negative")
        embeddings = self.encode()
        logit = self.pair_logit(embeddings, source_id, target_id)
        if contradiction_weight:
            logit = logit - contradiction_weight
        return torch.sigmoid(logit)

    @torch.no_grad()
    def predict_pair(
        self, source_id: str, target_id: str, *, contradiction_weight: float = 0.0
    ) -> TorchPairPrediction:
        self.eval()
        score = float(
            self.pair_score(source_id, target_id, contradiction_weight=contradiction_weight)
        )
        return TorchPairPrediction(source_id, target_id, score, self.model_id, self.model_version)
