"""Deterministic synthetic transaction graphs (Phase 14).

Plan: *"Start with synthetic transaction graphs. Only later add
permitted public blockchain observations."*  Everything here is
generated from one seeded ``random.Random`` — same seed, same graph,
on any machine — and is clearly marked synthetic (``synthetic_``
address prefix, ``synthetic`` asset, ``synthetic_ground_truth``
cluster basis).

Structure injected on purpose so every feature has signal to measure:

* a round-robin primary input guarantees every wallet participates;
* per-wallet **burst windows** make cadences differ (regular vs
  bursty wallets -> temporal burstiness spread);
* outputs are biased toward cluster-mates -> clusters show real
  counterparty overlap and co-occurrence, unclustered pairs don't.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from aegis.financial.graph import FinancialGraph
from aegis.financial.types import AddressCluster, Transaction, Wallet

#: The frozen project seed (matches the corpus and baseline defaults).
DEFAULT_SYNTHETIC_SEED = 26151

_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
_WINDOW_DAYS = 180
_MIN_AMOUNT = 0.01


def build_synthetic_financial_graph(
    *,
    seed: int = DEFAULT_SYNTHETIC_SEED,
    wallet_count: int = 60,
    transaction_count: int = 400,
) -> FinancialGraph:
    """Build a deterministic synthetic wallet/transaction/cluster graph.

    Raises ``ValueError`` on sizes that cannot satisfy the injected
    structure invariants (round-robin coverage, at least one cluster).
    """
    if wallet_count < 4:
        raise ValueError("wallet_count must be >= 4 to form clusters")
    if transaction_count < wallet_count:
        raise ValueError(
            "transaction_count must be >= wallet_count so round-robin inputs cover every wallet"
        )
    rng = random.Random(seed)

    wallet_ids = [f"wallet-{i:04d}" for i in range(wallet_count)]
    addresses = {wallet_id: f"synthetic_{rng.getrandbits(160):040x}" for wallet_id in wallet_ids}

    # per-wallet burst windows (0-2 each): anchors for bursty cadence
    burst_windows: dict[str, list[tuple[datetime, datetime]]] = {}
    for wallet_id in wallet_ids:
        windows: list[tuple[datetime, datetime]] = []
        for _ in range(rng.randrange(0, 3)):
            start = _BASE_TIME + timedelta(days=rng.uniform(0.0, _WINDOW_DAYS - 10.0))
            end = start + timedelta(days=rng.uniform(1.0, 9.0))
            windows.append((start, end))
        burst_windows[wallet_id] = windows

    # clusters: shuffle, then group into 2-4 member sets (one leftover
    # singleton stays unclustered on purpose — the feature needs negatives)
    order = list(wallet_ids)
    rng.shuffle(order)
    clusters: list[AddressCluster] = []
    index = 0
    cluster_number = 0
    while index < len(order):
        members = order[index : index + rng.choice((2, 2, 3, 4))]
        index += len(members)
        if len(members) < 2:
            break
        cluster_number += 1
        clusters.append(
            AddressCluster(
                cluster_id=f"cluster-{cluster_number:03d}",
                wallet_ids=frozenset(members),
                basis="synthetic_ground_truth",
                confidence=1.0,
            )
        )
    if not clusters:
        raise ValueError("wallet_count too small to form any cluster")
    cluster_members = [sorted(cluster.wallet_ids) for cluster in clusters]

    # transactions with round-robin coverage + cluster-biased outputs
    transactions: list[Transaction] = []
    participation: dict[str, list[datetime]] = {wallet_id: [] for wallet_id in wallet_ids}
    for tx_index in range(transaction_count):
        primary_input = wallet_ids[tx_index % wallet_count]
        inputs = [primary_input]
        if rng.random() < 0.4:
            extra = rng.choice(wallet_ids)
            if extra != primary_input:
                inputs.append(extra)

        outputs: list[str] = []
        for _ in range(rng.randint(1, 3)):
            if rng.random() < 0.5:
                candidate = rng.choice(rng.choice(cluster_members))
            else:
                candidate = rng.choice(wallet_ids)
            if candidate not in outputs:
                outputs.append(candidate)

        anchor = primary_input if rng.random() < 0.5 else rng.choice(wallet_ids)
        windows = burst_windows[anchor]
        if windows and rng.random() < 0.7:
            start, end = rng.choice(windows)
            timestamp = start + (end - start) * rng.random()
        else:
            timestamp = _BASE_TIME + timedelta(seconds=rng.uniform(0.0, _WINDOW_DAYS * 86400.0))

        transactions.append(
            Transaction(
                tx_id=f"tx-{tx_index:05d}",
                inputs=tuple(inputs),
                outputs=tuple(outputs),
                amount=max(round(rng.lognormvariate(1.5, 1.0), 2), _MIN_AMOUNT),
                timestamp=timestamp,
            )
        )
        for wallet_id in (*inputs, *outputs):
            participation[wallet_id].append(timestamp)

    wallets = [
        Wallet(
            wallet_id=wallet_id,
            address=addresses[wallet_id],
            first_seen=min(participation[wallet_id]),
            last_seen=max(participation[wallet_id]),
        )
        for wallet_id in wallet_ids
    ]

    graph = FinancialGraph()
    for wallet in wallets:
        graph.add_wallet(wallet)
    for transaction in transactions:
        graph.add_transaction(transaction)
    for cluster in clusters:
        graph.add_cluster(cluster)
    return graph
