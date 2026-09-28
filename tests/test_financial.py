"""Phase 14 financial-graph tests.

Covers the four plan objects' validation, the graph's derived flow
indexes (counterparty aggregation, degree, timelines, clusters), the
six plan features against hand-computed examples, burstiness math, and
the deterministic synthetic transaction-graph builder.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegis.financial import (
    DEFAULT_SYNTHETIC_SEED,
    FEATURE_NAMES,
    AddressCluster,
    Counterparty,
    FinancialGraph,
    Transaction,
    Wallet,
    WalletFeatureExtractor,
    WalletPairFeatures,
    build_graph,
    build_synthetic_financial_graph,
    temporal_burstiness,
    validate_feature_registry,
)
from aegis.graph import GraphValidationError

T0 = datetime(2026, 3, 1, tzinfo=UTC)


def _wallet(wallet_id: str, *, address: str | None = None) -> Wallet:
    return Wallet(
        wallet_id=wallet_id,
        address=address or f"synthetic-{wallet_id}",
        first_seen=T0,
        last_seen=T0 + timedelta(days=10),
    )


def _tx(
    tx_id: str,
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
    *,
    timestamp: datetime = T0,
    amount: float = 1.0,
) -> Transaction:
    return Transaction(
        tx_id=tx_id,
        inputs=inputs,
        outputs=outputs,
        amount=amount,
        timestamp=timestamp,
    )


def _cluster(cluster_id: str, *wallet_ids: str) -> AddressCluster:
    return AddressCluster(
        cluster_id=cluster_id,
        wallet_ids=frozenset(wallet_ids),
        basis="test_fixture",
        confidence=1.0,
    )


# ---------------------------------------------------------- type validation


def test_wallet_validation() -> None:
    with pytest.raises(ValueError, match="wallet_id"):
        _wallet("")
    with pytest.raises(ValueError, match="address"):
        Wallet(wallet_id="w", address="  ", first_seen=T0, last_seen=T0)
    with pytest.raises(GraphValidationError, match="timezone-aware"):
        Wallet(
            wallet_id="w",
            address="a",
            first_seen=datetime(2026, 1, 1),  # naive
            last_seen=T0,
        )
    with pytest.raises(ValueError, match="last_seen"):
        Wallet(
            wallet_id="w",
            address="a",
            first_seen=T0 + timedelta(days=5),
            last_seen=T0,
        )
    with pytest.raises(ValueError, match="labels"):
        Wallet(
            wallet_id="w",
            address="a",
            first_seen=T0,
            last_seen=T0,
            labels=frozenset({""}),
        )


def test_transaction_validation() -> None:
    with pytest.raises(ValueError, match="tx_id"):
        _tx("", ("w1",), ("w2",))
    with pytest.raises(ValueError, match="inputs must be non-empty"):
        _tx("t", (), ("w2",))
    with pytest.raises(ValueError, match="outputs must be non-empty"):
        _tx("t", ("w1",), ())
    with pytest.raises(ValueError, match="unique within"):
        _tx("t", ("w1", "w1"), ("w2",))
    with pytest.raises(ValueError, match="unique within"):
        _tx("t", ("w1",), ("w2", "w2"))
    with pytest.raises(ValueError, match="non-empty"):
        _tx("t", ("w1",), ("",))
    with pytest.raises(ValueError, match="amount"):
        _tx("t", ("w1",), ("w2",), amount=0.0)
    with pytest.raises(ValueError, match="amount"):
        _tx("t", ("w1",), ("w2",), amount=float("nan"))
    with pytest.raises(ValueError, match="timezone-aware"):
        Transaction(
            tx_id="t",
            inputs=("w1",),
            outputs=("w2",),
            amount=1.0,
            timestamp=datetime(2026, 1, 1),  # naive
        )
    tx = _tx("t", ("w1", "w2"), ("w3",))
    assert tx.participants == frozenset({"w1", "w2", "w3"})


def test_counterparty_validation() -> None:
    def make(**overrides: object) -> Counterparty:
        base: dict[str, object] = {
            "wallet_id": "w1",
            "counterparty_id": "w2",
            "transaction_count": 1,
            "first_seen": T0,
            "last_seen": T0,
            "total_amount": 1.0,
        }
        base.update(overrides)
        return Counterparty(**base)  # type: ignore[arg-type]

    assert make().wallet_id == "w1"
    with pytest.raises(ValueError, match="distinct"):
        make(counterparty_id="w1")
    with pytest.raises(ValueError, match="canonical"):
        make(wallet_id="w2", counterparty_id="w1")
    with pytest.raises(ValueError, match="transaction_count"):
        make(transaction_count=0)
    with pytest.raises(ValueError, match="last_seen"):
        make(last_seen=T0 - timedelta(days=1))
    with pytest.raises(ValueError, match="total_amount"):
        make(total_amount=-1.0)


def test_address_cluster_validation() -> None:
    with pytest.raises(ValueError, match="cluster_id"):
        AddressCluster(cluster_id="", wallet_ids=frozenset({"a", "b"}), basis="x")
    with pytest.raises(ValueError, match="at least two"):
        AddressCluster(cluster_id="c", wallet_ids=frozenset({"a"}), basis="x")
    with pytest.raises(ValueError, match="basis"):
        AddressCluster(cluster_id="c", wallet_ids=frozenset({"a", "b"}), basis=" ")
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        AddressCluster(
            cluster_id="c",
            wallet_ids=frozenset({"a", "b"}),
            basis="x",
            confidence=1.5,
        )


# ---------------------------------------------------------- graph store


def _flow_fixture() -> FinancialGraph:
    """w1 -> w2 twice, w1 -> w3 once, w4 <-> w5 twice (via flows)."""
    return build_graph(
        wallets=[_wallet(f"w{i}") for i in range(1, 6)],
        transactions=[
            _tx("tx_a", ("w1",), ("w2",), timestamp=T0, amount=1.0),
            _tx("tx_b", ("w1",), ("w3",), timestamp=T0 + timedelta(hours=1)),
            _tx("tx_c", ("w1",), ("w2",), timestamp=T0 + timedelta(hours=2), amount=1.5),
            _tx("tx_d", ("w4",), ("w5",), timestamp=T0),
            _tx("tx_e", ("w4",), ("w5",), timestamp=T0 + timedelta(hours=1)),
        ],
        clusters=[_cluster("cluster-1", "w1", "w2"), _cluster("cluster-2", "w4", "w5")],
    )


def test_graph_fails_loudly_on_bad_writes() -> None:
    graph = FinancialGraph()
    graph.add_wallet(_wallet("w1"))
    graph.add_wallet(_wallet("w2"))
    with pytest.raises(ValueError, match="duplicate wallet_id"):
        graph.add_wallet(_wallet("w1"))
    with pytest.raises(ValueError, match="unknown wallet"):
        graph.add_transaction(_tx("tx_x", ("ghost",), ("w1",)))
    with pytest.raises(ValueError, match="unknown wallet"):
        graph.add_transaction(_tx("tx_x", ("w1",), ("ghost",)))

    graph.add_transaction(_tx("tx_1", ("w1",), ("w1",)))  # self-payment: legal
    with pytest.raises(ValueError, match="duplicate tx_id"):
        graph.add_transaction(_tx("tx_1", ("w1",), ("w1",)))

    graph.add_cluster(_cluster("c1", "w1", "w2"))
    with pytest.raises(ValueError, match="duplicate cluster_id"):
        graph.add_cluster(_cluster("c1", "w1", "w2"))


def test_counterparty_aggregation_and_degree() -> None:
    graph = _flow_fixture()

    flows = graph.counterparty_pairs()
    assert [(f.wallet_id, f.counterparty_id) for f in flows] == [
        ("w1", "w2"),
        ("w1", "w3"),
        ("w4", "w5"),
    ]
    w1_w2 = flows[0]
    assert w1_w2.transaction_count == 2
    assert w1_w2.first_seen == T0
    assert w1_w2.last_seen == T0 + timedelta(hours=2)
    assert w1_w2.total_amount == pytest.approx(2.5)

    assert graph.degree("w1") == 2
    assert graph.degree("w2") == 1
    assert graph.degree("w4") == 1
    with pytest.raises(KeyError, match="unknown wallet"):
        graph.degree("ghost")


def test_counterparties_of_is_canonical_and_ordered() -> None:
    graph = _flow_fixture()
    of_w2 = graph.counterparties_of("w2")
    assert [(f.wallet_id, f.counterparty_id) for f in of_w2] == [("w1", "w2")]
    of_w4 = graph.counterparties_of("w4")
    assert [(f.wallet_id, f.counterparty_id) for f in of_w4] == [("w4", "w5")]
    with pytest.raises(KeyError, match="unknown wallet"):
        graph.counterparties_of("ghost")


def test_self_payment_creates_no_counterparty() -> None:
    graph = build_graph(
        wallets=[_wallet("w1")],
        transactions=[_tx("tx_self", ("w1",), ("w1",))],
    )
    assert graph.counterparty_pairs() == ()
    assert graph.degree("w1") == 0
    assert len(graph.transactions_of("w1")) == 1


def test_transactions_of_sorted_and_shared() -> None:
    graph = _flow_fixture()
    ids = [tx.tx_id for tx in graph.transactions_of("w1")]
    assert ids == ["tx_a", "tx_b", "tx_c"]  # ordered by (timestamp, tx_id)
    shared = [tx.tx_id for tx in graph.shared_transactions("w1", "w2")]
    assert shared == ["tx_a", "tx_c"]
    assert graph.shared_transactions("w3", "w4") == ()
    with pytest.raises(KeyError, match="unknown wallet"):
        graph.transactions_of("ghost")
    with pytest.raises(KeyError, match="unknown tx_id"):
        graph.transaction("ghost")
    with pytest.raises(KeyError, match="unknown wallet"):
        graph.wallet("ghost")


def test_cluster_membership_is_single_and_loud() -> None:
    graph = _flow_fixture()
    cluster = graph.cluster_of("w1")
    assert cluster is not None and cluster.cluster_id == "cluster-1"
    assert graph.cluster_of("w3") is None  # unclustered by fixture design
    with pytest.raises(ValueError, match="already belongs to cluster"):
        graph.add_cluster(_cluster("c3", "w1", "w3"))
    with pytest.raises(ValueError, match="unknown wallet"):
        graph.add_cluster(_cluster("c4", "ghost", "w3"))
    with pytest.raises(KeyError, match="unknown cluster_id"):
        graph.cluster("ghost")


def test_build_graph_requires_wallets_before_transactions() -> None:
    with pytest.raises(ValueError, match="unknown wallet"):
        build_graph(wallets=[], transactions=[_tx("tx", ("w1",), ("w2",))])


def test_summary_is_deterministic() -> None:
    assert _flow_fixture().summary() == _flow_fixture().summary()


# ---------------------------------------------------------- burstiness


def test_temporal_burstiness_hand_computed() -> None:
    assert temporal_burstiness([]) == 0.5  # neutral: no rhythm observed
    assert temporal_burstiness([T0]) == 0.5
    regular = [T0, T0 + timedelta(hours=1), T0 + timedelta(hours=2), T0 + timedelta(hours=3)]
    assert temporal_burstiness(regular) == 0.0  # sigma = 0 -> perfectly regular
    simultaneous = [T0, T0, T0]
    assert temporal_burstiness(simultaneous) == 1.0  # everything at once
    bursty = [
        T0 + timedelta(seconds=10),
        T0 + timedelta(seconds=20),
        T0 + timedelta(seconds=30),
        T0 + timedelta(seconds=40),
        T0 + timedelta(seconds=1040),
    ]
    score = temporal_burstiness(bursty)
    assert score == pytest.approx(0.625, abs=0.001)  # gaps 10,10,10,1000
    # order must not matter (sorted internally)
    assert temporal_burstiness(list(reversed(bursty))) == pytest.approx(score)


# ---------------------------------------------------------- pair features


def test_wallet_pair_features_validation_and_registry() -> None:
    validate_feature_registry()
    assert WalletPairFeatures.feature_names() == FEATURE_NAMES
    zeros = WalletPairFeatures(
        degree=0.0,
        frequency=0.0,
        temporal_burstiness=0.0,
        counterparty_overlap=0.0,
        co_occurrence=0.0,
        cluster_membership=0.0,
    )
    assert zeros.as_vector() == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert len(FEATURE_NAMES) == 6
    for bad in (-0.1, 1.5, float("nan")):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            WalletPairFeatures(
                degree=bad,
                frequency=0.0,
                temporal_burstiness=0.0,
                counterparty_overlap=0.0,
                co_occurrence=0.0,
                cluster_membership=0.0,
            )


def test_pair_features_hand_computed() -> None:
    graph = _flow_fixture()
    extractor = WalletFeatureExtractor(graph)

    # (w1, w2): both sides of the first flow, same cluster
    pair = extractor.extract("w1", "w2")
    assert pair.degree == pytest.approx(0.5)  # degrees 2 vs 1
    assert pair.frequency == pytest.approx(2 / 3)  # txs 3 vs 2
    assert pair.temporal_burstiness == 1.0  # both regular (0.0 vs 0.0)
    assert pair.counterparty_overlap == 0.0  # {w2,w3} vs {w1}
    assert pair.co_occurrence == 1.0  # shared {a,c} / min(3,2)
    assert pair.cluster_membership == 1.0  # cluster-1

    # (w2, w3): shared counterparty, different cluster status
    pair = extractor.extract("w2", "w3")
    assert pair.degree == 1.0  # degrees 1 vs 1
    assert pair.frequency == pytest.approx(0.5)  # txs 2 vs 1
    assert pair.temporal_burstiness == pytest.approx(0.5)  # 0.0 vs neutral 0.5
    assert pair.counterparty_overlap == 1.0  # both {w1}
    assert pair.co_occurrence == 0.0  # no shared transaction
    assert pair.cluster_membership == 0.0  # w3 unclustered

    # (w1, w4): different clusters entirely
    pair = extractor.extract("w1", "w4")
    assert pair.cluster_membership == 0.0
    assert pair.counterparty_overlap == 0.0
    assert pair.co_occurrence == 0.0
    assert pair.degree == pytest.approx(0.5)  # 2 vs 1
    assert pair.frequency == pytest.approx(2 / 3)  # 3 vs 2

    # shared cluster: (w4, w5)
    assert extractor.extract("w4", "w5").cluster_membership == 1.0
    # one-sided membership: (w1, w3)
    assert extractor.extract("w1", "w3").cluster_membership == 0.0


def test_extractor_rejects_self_and_unknown_wallets() -> None:
    extractor = WalletFeatureExtractor(_flow_fixture())
    with pytest.raises(ValueError, match="itself"):
        extractor.extract("w1", "w1")
    with pytest.raises(KeyError, match="unknown wallet"):
        extractor.extract("w1", "ghost")


def test_extractor_caches_burstiness_per_wallet() -> None:
    extractor = WalletFeatureExtractor(_flow_fixture())
    first = extractor.burstiness("w1")
    second = extractor.burstiness("w1")
    assert first is second  # same cached object, not recomputed
    assert extractor.counterparties("w1") == frozenset({"w2", "w3"})


# ---------------------------------------------------------- synthetic


def test_default_seed_is_frozen() -> None:
    assert DEFAULT_SYNTHETIC_SEED == 26151


def test_synthetic_builder_rejects_unsatisfiable_sizes() -> None:
    with pytest.raises(ValueError, match="wallet_count"):
        build_synthetic_financial_graph(wallet_count=3, transaction_count=10)
    with pytest.raises(ValueError, match="transaction_count"):
        build_synthetic_financial_graph(wallet_count=10, transaction_count=5)


def test_synthetic_graph_invariants() -> None:
    graph = build_synthetic_financial_graph()
    assert graph.wallet_count == 60
    assert graph.transaction_count == 400

    window_end = datetime(2026, 7, 1, tzinfo=UTC)
    for wallet in graph.wallets.values():
        assert wallet.address.startswith("synthetic_")
        assert graph.transactions_of(wallet.wallet_id), "round-robin guarantees coverage"
        assert datetime(2026, 1, 1, tzinfo=UTC) <= wallet.first_seen <= wallet.last_seen
        assert wallet.last_seen <= window_end

    for tx in graph.transactions.values():
        assert tx.amount > 0.0
        for wallet_id in tx.participants:
            assert wallet_id in graph.wallets

    clusters = graph.clusters
    assert clusters
    for cluster in clusters.values():
        assert len(cluster.wallet_ids) >= 2
        assert cluster.basis == "synthetic_ground_truth"
        for wallet_id in cluster.wallet_ids:
            assert graph.wallet(wallet_id)
            member = graph.cluster_of(wallet_id)
            assert member is not None and member.cluster_id == cluster.cluster_id


def test_synthetic_builder_is_deterministic() -> None:
    first = build_synthetic_financial_graph()
    second = build_synthetic_financial_graph()
    assert first.summary() == second.summary()
    other_seed = build_synthetic_financial_graph(seed=DEFAULT_SYNTHETIC_SEED + 1)
    assert other_seed.summary() != first.summary()


def test_synthetic_features_have_range_and_spread() -> None:
    graph = build_synthetic_financial_graph()
    extractor = WalletFeatureExtractor(graph)
    validate_feature_registry()

    # in-range vectors for cluster-mates and cross-cluster pairs
    cluster_ids = sorted(graph.clusters)
    assert len(cluster_ids) >= 2
    first_cluster = sorted(graph.clusters[cluster_ids[0]].wallet_ids)
    second_cluster = sorted(graph.clusters[cluster_ids[1]].wallet_ids)

    same = extractor.extract(first_cluster[0], first_cluster[1])
    assert same.cluster_membership == 1.0
    cross = extractor.extract(first_cluster[0], second_cluster[0])
    assert cross.cluster_membership == 0.0
    # as_vector raises on anything outside [0, 1], so construction passing
    # is the range assertion; check explicitly too
    for value in (*same.as_vector(), *cross.as_vector()):
        assert 0.0 <= value <= 1.0

    # injected structure produces burstiness spread across wallets
    scores = {extractor.burstiness(w.wallet_id) for w in graph.wallets.values()}
    assert len(scores) >= 2

    # flows exist (cluster-biased outputs + round-robin inputs)
    assert graph.counterparty_pairs()
