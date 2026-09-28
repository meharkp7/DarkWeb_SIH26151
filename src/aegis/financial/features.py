"""The six plan features for the financial graph (Phase 14).

Plan feature list: *degree, frequency, temporal burstiness,
counterparty overlap, co-occurrence, cluster membership*.  All six are
computed as candidate-pair features between two wallets of one
:class:`~aegis.financial.graph.FinancialGraph` and are normalized to
``[0, 1]`` so downstream models consume a stable vector:

======================  =================================================
feature                 semantics
======================  =================================================
degree                  ``min(d1,d2)/max(d1,d2)`` flow-degree similarity
                        (both zero -> 0.0: nothing observed)
frequency               ``min(f1,f2)/max(f1,f2)`` transaction-frequency
                        similarity (both zero -> 0.0)
temporal_burstiness     ``1 - |b1-b2|`` rhythm similarity of the two
                        wallets' normalized burstiness scores
counterparty_overlap    Jaccard of direct-flow counterparty sets (both
                        empty -> 0.0: no observed relation)
co_occurrence           shared transactions / min(count) (either zero
                        -> 0.0)
cluster_membership      1.0 iff both wallets share one AddressCluster,
                        else 0.0 (unclustered wallets are not evidence
                        of common control)
======================  =================================================

Burstiness itself is the standard coefficient-of-variation measure
``b = (sigma - mu) / (sigma + mu)`` over inter-arrival times, mapped
from ``[-1, 1]`` onto ``[0, 1]`` via ``(b + 1) / 2``: perfectly regular
cadence -> 0.0, everything-at-once -> 1.0.  Fewer than two observations
carry no rhythm information and score the neutral 0.5.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime

from aegis.financial.graph import FinancialGraph

#: Feature order fixed by the plan; frozen for downstream consumers.
FEATURE_NAMES: tuple[str, ...] = (
    "degree",
    "frequency",
    "temporal_burstiness",
    "counterparty_overlap",
    "co_occurrence",
    "cluster_membership",
)

_NEUTRAL_BURSTINESS = 0.5


def temporal_burstiness(timestamps: Sequence[datetime]) -> float:
    """Normalized temporal burstiness of an event sequence, in ``[0, 1]``.

    0.0 = perfectly regular cadence, 1.0 = maximally clustered events
    (including every event at the same instant).  Fewer than two events
    -> neutral 0.5 (no measurable rhythm).
    """
    if len(timestamps) < 2:
        return _NEUTRAL_BURSTINESS
    ordered = sorted(timestamps)
    gaps = [
        (later - earlier).total_seconds()
        for earlier, later in zip(ordered, ordered[1:], strict=False)
    ]
    mean = sum(gaps) / len(gaps)
    if mean == 0.0:
        return 1.0  # every event simultaneous: maximum burst
    variance = sum((gap - mean) ** 2 for gap in gaps) / len(gaps)
    sigma = math.sqrt(variance)
    coefficient = (sigma - mean) / (sigma + mean)
    return (coefficient + 1.0) / 2.0


@dataclass(frozen=True)
class WalletPairFeatures:
    """The six plan features for one candidate wallet pair."""

    degree: float
    frequency: float
    temporal_burstiness: float
    counterparty_overlap: float
    co_occurrence: float
    cluster_membership: float

    def __post_init__(self) -> None:
        for entry in fields(self):
            value = getattr(self, entry.name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{entry.name} must be within [0, 1], got {value!r}")

    def as_vector(self) -> tuple[float, ...]:
        """Feature values in :data:`FEATURE_NAMES` order."""
        return tuple(float(getattr(self, name)) for name in FEATURE_NAMES)

    @classmethod
    def feature_names(cls) -> tuple[str, ...]:
        """Registry invariant: field order must match the plan list."""
        return tuple(field.name for field in fields(cls))


def validate_feature_registry() -> None:
    """Fail loudly if the dataclass drifts from the frozen plan list."""
    actual = WalletPairFeatures.feature_names()
    if actual != FEATURE_NAMES:
        raise ValueError(f"feature registry drift: dataclass {actual} != plan {FEATURE_NAMES}")


def _ratio_similarity(left: int, right: int) -> float:
    """``min/max`` similarity of two counts (both zero -> 0.0)."""
    if left <= 0 or right <= 0:
        return 0.0
    return min(left, right) / max(left, right)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class WalletFeatureExtractor:
    """Extracts the six plan features for wallet pairs of one graph.

    Burstiness per wallet is cached (same graph, immutable after
    construction in practice — the cache is per-instance, so a graph
    mutated after extraction would need a fresh extractor).
    """

    def __init__(self, graph: FinancialGraph) -> None:
        self._graph = graph
        self._burstiness_cache: dict[str, float] = {}

    def burstiness(self, wallet_id: str) -> float:
        """Normalized burstiness of one wallet's transaction cadence."""
        cached = self._burstiness_cache.get(wallet_id)
        if cached is not None:
            return cached
        timestamps = [tx.timestamp for tx in self._graph.transactions_of(wallet_id)]
        score = temporal_burstiness(timestamps)
        self._burstiness_cache[wallet_id] = score
        return score

    def counterparties(self, wallet_id: str) -> frozenset[str]:
        """Direct-flow counterparty set of a wallet."""
        return frozenset(
            flow.counterparty_id if flow.wallet_id == wallet_id else flow.wallet_id
            for flow in self._graph.counterparties_of(wallet_id)
        )

    def extract(self, left_wallet_id: str, right_wallet_id: str) -> WalletPairFeatures:
        """Compute the six features for one candidate pair.

        Raises ``KeyError`` for unknown wallets (fail loudly — a
        silently-defaulted feature would poison model inputs).
        """
        if left_wallet_id == right_wallet_id:
            raise ValueError("cannot extract pair features for a wallet with itself")
        left_degree = self._graph.degree(left_wallet_id)
        right_degree = self._graph.degree(right_wallet_id)
        left_count = len(self._graph.transactions_of(left_wallet_id))
        right_count = len(self._graph.transactions_of(right_wallet_id))
        shared = len(self._graph.shared_transactions(left_wallet_id, right_wallet_id))

        left_cluster = self._graph.cluster_of(left_wallet_id)
        right_cluster = self._graph.cluster_of(right_wallet_id)
        same_cluster = (
            left_cluster is not None
            and right_cluster is not None
            and left_cluster.cluster_id == right_cluster.cluster_id
        )

        return WalletPairFeatures(
            degree=_ratio_similarity(left_degree, right_degree),
            frequency=_ratio_similarity(left_count, right_count),
            temporal_burstiness=1.0
            - abs(self.burstiness(left_wallet_id) - self.burstiness(right_wallet_id)),
            counterparty_overlap=_jaccard(
                self.counterparties(left_wallet_id), self.counterparties(right_wallet_id)
            ),
            co_occurrence=_ratio_similarity(shared, min(left_count, right_count)),
            cluster_membership=1.0 if same_cluster else 0.0,
        )
