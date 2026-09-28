"""Financial-graph domain objects (Phase 14).

The plan's four objects — *Wallet*, *Transaction*, *Counterparty*,
*AddressCluster* — as frozen, validated records:

* :class:`Wallet` — an observed address with an activity window.
* :class:`Transaction` — a directed value flow (inputs -> outputs)
  with a timestamp and positive amount.
* :class:`Counterparty` — an aggregated wallet-to-wallet flow derived
  from transactions (canonical ``wallet_id < counterparty_id`` order,
  transaction count, time range, summed amount).
* :class:`AddressCluster` — a set of wallets believed to be under one
  control, carrying provenance (``basis``) and a confidence in
  ``[0, 1]``.

Defensive/synthetic-only: records here are populated from synthetic
transaction graphs (Phase 14 starts with synthetic fixtures per plan);
live blockchain observation is explicitly deferred until a permitted
public source is approved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from aegis.graph import ensure_aware


@dataclass(frozen=True)
class Wallet:
    """An observed wallet address with its activity window."""

    wallet_id: str
    address: str
    first_seen: datetime
    last_seen: datetime
    labels: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.wallet_id.strip():
            raise ValueError("wallet_id must be non-empty")
        if not self.address.strip():
            raise ValueError("address must be non-empty")
        first = ensure_aware(self.first_seen, field_name="first_seen")
        last = ensure_aware(self.last_seen, field_name="last_seen")
        if last < first:
            raise ValueError("last_seen must not precede first_seen")
        if any(not label.strip() for label in self.labels):
            raise ValueError("labels must be non-empty strings")


@dataclass(frozen=True)
class Transaction:
    """A directed value flow from input wallets to output wallets.

    Input/output overlap is allowed (change addresses belong to the
    sender); a wallet paying itself simply creates no counterparty
    edge for that pair.
    """

    tx_id: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    amount: float
    timestamp: datetime
    asset: str = "synthetic"

    def __post_init__(self) -> None:
        if not self.tx_id.strip():
            raise ValueError("tx_id must be non-empty")
        if not self.inputs:
            raise ValueError("inputs must be non-empty")
        if not self.outputs:
            raise ValueError("outputs must be non-empty")
        if any(not wallet_id.strip() for wallet_id in (*self.inputs, *self.outputs)):
            raise ValueError("input/output wallet ids must be non-empty")
        if len(set(self.inputs)) != len(self.inputs):
            raise ValueError("inputs must be unique within a transaction")
        if len(set(self.outputs)) != len(self.outputs):
            raise ValueError("outputs must be unique within a transaction")
        if not math.isfinite(self.amount) or self.amount <= 0.0:
            raise ValueError("amount must be finite and > 0")
        if not self.asset.strip():
            raise ValueError("asset must be non-empty")
        ensure_aware(self.timestamp, field_name="timestamp")

    @property
    def participants(self) -> frozenset[str]:
        """Every wallet touched by this transaction (inputs + outputs)."""
        return frozenset(self.inputs) | frozenset(self.outputs)


@dataclass(frozen=True)
class Counterparty:
    """Aggregated direct flow between two wallets, derived from transactions.

    Canonical order: ``wallet_id < counterparty_id`` (the store never
    emits both directions of the same pair).
    """

    wallet_id: str
    counterparty_id: str
    transaction_count: int
    first_seen: datetime
    last_seen: datetime
    total_amount: float

    def __post_init__(self) -> None:
        if not self.wallet_id.strip() or not self.counterparty_id.strip():
            raise ValueError("counterparty wallet ids must be non-empty")
        if self.wallet_id == self.counterparty_id:
            raise ValueError("counterparty must link two distinct wallets")
        if self.wallet_id > self.counterparty_id:
            raise ValueError("counterparty pair must be in canonical (min, max) order")
        if self.transaction_count < 1:
            raise ValueError("transaction_count must be >= 1")
        if not math.isfinite(self.total_amount) or self.total_amount < 0.0:
            raise ValueError("total_amount must be finite and >= 0")
        first = ensure_aware(self.first_seen, field_name="first_seen")
        last = ensure_aware(self.last_seen, field_name="last_seen")
        if last < first:
            raise ValueError("last_seen must not precede first_seen")


@dataclass(frozen=True)
class AddressCluster:
    """Wallets believed to be under common control.

    ``basis`` is provenance for how the cluster was derived (plan
    requires cluster membership to be explainable); ``confidence`` is
    calibrated in ``[0, 1]``.
    """

    cluster_id: str
    wallet_ids: frozenset[str]
    basis: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.cluster_id.strip():
            raise ValueError("cluster_id must be non-empty")
        if len(self.wallet_ids) < 2:
            raise ValueError("a cluster needs at least two wallets")
        if any(not wallet_id.strip() for wallet_id in self.wallet_ids):
            raise ValueError("cluster wallet ids must be non-empty")
        if not self.basis.strip():
            raise ValueError("basis must be non-empty (cluster provenance is required)")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
