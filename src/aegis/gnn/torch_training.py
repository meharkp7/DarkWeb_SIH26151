"""Leakage-controlled training utilities for the learned Phase 19 model."""

from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np
import torch

from aegis.gnn.torch_models import TemporalHeterogeneousGNN


@dataclass(frozen=True)
class TemporalPair:
    source_id: str
    target_id: str
    label: int
    group_id: str
    cutoff_day: float | None = None

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id or self.source_id == self.target_id:
            raise ValueError("pair endpoints must be distinct and non-empty")
        if self.label not in (0, 1):
            raise ValueError("label must be 0 or 1")
        if not self.group_id:
            raise ValueError("group_id must be non-empty")


@dataclass(frozen=True)
class SplitPairs:
    train: tuple[TemporalPair, ...]
    validation: tuple[TemporalPair, ...]
    test: tuple[TemporalPair, ...]


def split_by_group(
    pairs: list[TemporalPair],
    *,
    seed: int = 26151,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
) -> SplitPairs:
    if not pairs:
        raise ValueError("pairs must not be empty")
    if not 0.0 < train_fraction < 1.0 or not 0.0 < validation_fraction < 1.0:
        raise ValueError("fractions must be in (0, 1)")
    if train_fraction + validation_fraction >= 1.0:
        raise ValueError("train + validation fractions must be below 1")
    groups = sorted({pair.group_id for pair in pairs})
    rng = random.Random(seed)
    rng.shuffle(groups)
    train_end = max(1, int(len(groups) * train_fraction))
    validation_end = max(train_end + 1, int(len(groups) * (train_fraction + validation_fraction)))
    validation_end = min(validation_end, len(groups) - 1)
    train_groups = set(groups[:train_end])
    validation_groups = set(groups[train_end:validation_end])
    test_groups = set(groups[validation_end:])
    if not validation_groups or not test_groups:
        raise ValueError("group split requires at least three distinct groups")
    return SplitPairs(
        tuple(pair for pair in pairs if pair.group_id in train_groups),
        tuple(pair for pair in pairs if pair.group_id in validation_groups),
        tuple(pair for pair in pairs if pair.group_id in test_groups),
    )


@dataclass(frozen=True)
class TrainingResult:
    best_epoch: int
    best_validation_loss: float
    train_loss: float
    test_scores: tuple[float, ...]


def train_pair_model(
    model: TemporalHeterogeneousGNN,
    train_pairs: tuple[TemporalPair, ...],
    validation_pairs: tuple[TemporalPair, ...],
    test_pairs: tuple[TemporalPair, ...],
    *,
    epochs: int = 100,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-4,
    patience: int = 12,
    seed: int = 26151,
) -> TrainingResult:
    if not train_pairs or not validation_pairs or not test_pairs:
        raise ValueError("train, validation and test pairs must all be non-empty")
    if epochs < 1 or learning_rate <= 0.0 or weight_decay < 0.0 or patience < 1:
        raise ValueError("invalid training hyperparameters")
    torch.manual_seed(seed)
    np.random.seed(seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    positive = sum(pair.label for pair in train_pairs)
    negative = len(train_pairs) - positive
    if positive == 0 or negative == 0:
        raise ValueError("training requires both positive and negative labels")
    device = next(model.parameters()).device
    pos_weight = torch.tensor([negative / positive], dtype=torch.float32, device=device)
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    best_loss = float("inf")
    best_epoch = 0
    stale = 0

    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        embeddings = model.encode()
        logits = torch.stack(
            [model.pair_logit(embeddings, pair.source_id, pair.target_id) for pair in train_pairs]
        )
        labels = torch.tensor([pair.label for pair in train_pairs], dtype=torch.float32)
        loss = criterion(logits, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()

        model.eval()
        with torch.no_grad():
            validation_embeddings = model.encode()
            validation_logits = torch.stack(
                [
                    model.pair_logit(validation_embeddings, pair.source_id, pair.target_id)
                    for pair in validation_pairs
                ]
            )
            validation_labels = torch.tensor(
                [pair.label for pair in validation_pairs], dtype=torch.float32
            )
            validation_loss = float(
                torch.nn.functional.binary_cross_entropy_with_logits(
                    validation_logits, validation_labels
                )
            )
        if validation_loss < best_loss - 1e-7:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        embeddings = model.encode()
        test_scores = tuple(
            float(torch.sigmoid(model.pair_logit(embeddings, pair.source_id, pair.target_id)))
            for pair in test_pairs
        )
    return TrainingResult(best_epoch, best_loss, float(loss.detach()), test_scores)
