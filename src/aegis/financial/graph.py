"""In-memory financial graph with validated writes and derived indexes.

Write path is strict (fail loudly on unknown wallets, duplicate ids,
broken windows) so a malformed synthetic fixture can never silently
contaminate features.  Derived state — canonical counterparty flows,
per-wallet transaction timelines, cluster membership — is maintained
incrementally on ``add_transaction``/``add_cluster``.

Counterparty semantics (documented decision): a direct flow edge is an
input x output cross product of one transaction; co-spend (input-input)
and co-receive (output-output) relations are *not* flows — they are
captured separately by the pair feature ``co_occurrence``.

Two review-driven invariants are maintained here:

* **Amount conservation** — one transaction's ``amount`` is split evenly
  over the flow edges it *emits* (cross-product pairs excluding
  ``source == target`` self-pairs), so a 2x2 transaction contributes its
  amount once in total instead of four times.  A 1x1 transaction (the
  common case, and every hand-written fixture) emits exactly one edge
  and therefore keeps the full amount.
* **O(1) adjacency reads** — besides the aggregated flows, the graph
  maintains a per-wallet pair index (``_wallet_pairs``) so
  :meth:`FinancialGraph.degree` and
  :meth:`FinancialGraph.counterparties_of` touch only that wallet's
  edges instead of scanning every pair.
"""

from __future__ import annotations

from collections.abc import Iterable

from aegis.financial.types import AddressCluster, Counterparty, Transaction, Wallet


class FinancialGraph:
    """Validated wallet/transaction/cluster graph with derived indexes."""

    def __init__(self) -> None:
        self._wallets: dict[str, Wallet] = {}
        self._transactions: dict[str, Transaction] = {}
        self._clusters: dict[str, AddressCluster] = {}
        #: canonical (min, max) wallet pair -> aggregated flow
        self._counterparties: dict[tuple[str, str], Counterparty] = {}
        #: wallet -> the canonical pair keys it participates in (adjacency
        #: index maintained by ``add_transaction``; keeps degree() O(1) and
        #: counterparties_of() proportional to that wallet's degree)
        self._wallet_pairs: dict[str, set[tuple[str, str]]] = {}
        #: wallet -> transaction ids touching it (sorted at read time)
        self._wallet_transactions: dict[str, list[str]] = {}
        #: wallet -> cluster id (single membership per wallet)
        self._wallet_cluster: dict[str, str] = {}

    # ------------------------------------------------------------ writes

    def add_wallet(self, wallet: Wallet) -> None:
        if wallet.wallet_id in self._wallets:
            raise ValueError(f"duplicate wallet_id: {wallet.wallet_id!r}")
        self._wallets[wallet.wallet_id] = wallet
        self._wallet_transactions.setdefault(wallet.wallet_id, [])
        self._wallet_pairs.setdefault(wallet.wallet_id, set())

    def add_transaction(self, transaction: Transaction) -> None:
        if transaction.tx_id in self._transactions:
            raise ValueError(f"duplicate tx_id: {transaction.tx_id!r}")
        for wallet_id in transaction.participants:
            if wallet_id not in self._wallets:
                raise ValueError(
                    f"transaction {transaction.tx_id!r} references unknown wallet "
                    f"{wallet_id!r}; add wallets before transactions"
                )

        self._transactions[transaction.tx_id] = transaction
        for wallet_id in transaction.participants:
            self._wallet_transactions[wallet_id].append(transaction.tx_id)

        # direct flows: input x output cross product (self-pairs skipped).
        # The transaction's amount is split evenly across the EMITTED edges
        # (amount conservation): a 2x2 transaction would otherwise add its
        # full amount to four aggregates. A single emitted edge — including
        # every 1x1 transaction — keeps the full amount.
        emitted: list[tuple[str, str]] = []
        for source in transaction.inputs:
            for target in transaction.outputs:
                if source == target:
                    continue
                emitted.append((min(source, target), max(source, target)))
        share = transaction.amount / len(emitted) if emitted else 0.0

        for key in emitted:
            existing = self._counterparties.get(key)
            if existing is None:
                self._counterparties[key] = Counterparty(
                    wallet_id=key[0],
                    counterparty_id=key[1],
                    transaction_count=1,
                    first_seen=transaction.timestamp,
                    last_seen=transaction.timestamp,
                    total_amount=share,
                )
            else:
                self._counterparties[key] = Counterparty(
                    wallet_id=key[0],
                    counterparty_id=key[1],
                    transaction_count=existing.transaction_count + 1,
                    first_seen=min(existing.first_seen, transaction.timestamp),
                    last_seen=max(existing.last_seen, transaction.timestamp),
                    total_amount=existing.total_amount + share,
                )
            # maintain the per-wallet adjacency index (both endpoints)
            self._wallet_pairs[key[0]].add(key)
            self._wallet_pairs[key[1]].add(key)

    def add_cluster(self, cluster: AddressCluster) -> None:
        if cluster.cluster_id in self._clusters:
            raise ValueError(f"duplicate cluster_id: {cluster.cluster_id!r}")
        for wallet_id in cluster.wallet_ids:
            if wallet_id not in self._wallets:
                raise ValueError(
                    f"cluster {cluster.cluster_id!r} references unknown wallet {wallet_id!r}"
                )
            owner = self._wallet_cluster.get(wallet_id)
            if owner is not None:
                raise ValueError(
                    f"wallet {wallet_id!r} already belongs to cluster {owner!r}; "
                    "single membership keeps the cluster feature unambiguous"
                )
        self._clusters[cluster.cluster_id] = cluster
        for wallet_id in cluster.wallet_ids:
            self._wallet_cluster[wallet_id] = cluster.cluster_id

    # ------------------------------------------------------------- reads

    @property
    def wallets(self) -> dict[str, Wallet]:
        return dict(self._wallets)

    @property
    def transactions(self) -> dict[str, Transaction]:
        return dict(self._transactions)

    @property
    def clusters(self) -> dict[str, AddressCluster]:
        return dict(self._clusters)

    @property
    def wallet_count(self) -> int:
        return len(self._wallets)

    @property
    def transaction_count(self) -> int:
        return len(self._transactions)

    def wallet(self, wallet_id: str) -> Wallet:
        try:
            return self._wallets[wallet_id]
        except KeyError:
            raise KeyError(f"unknown wallet_id: {wallet_id!r}") from None

    def transaction(self, tx_id: str) -> Transaction:
        try:
            return self._transactions[tx_id]
        except KeyError:
            raise KeyError(f"unknown tx_id: {tx_id!r}") from None

    def cluster(self, cluster_id: str) -> AddressCluster:
        try:
            return self._clusters[cluster_id]
        except KeyError:
            raise KeyError(f"unknown cluster_id: {cluster_id!r}") from None

    def degree(self, wallet_id: str) -> int:
        """Distinct direct-flow counterparties of a wallet.

        O(1): served from the per-wallet adjacency index maintained on
        ``add_transaction`` rather than a scan of every aggregated pair.
        """
        self.wallet(wallet_id)  # fail loudly on unknown ids
        return len(self._wallet_pairs[wallet_id])

    def transactions_of(self, wallet_id: str) -> tuple[Transaction, ...]:
        """Transactions touching a wallet, ordered by (timestamp, tx_id)."""
        self.wallet(wallet_id)
        txs = (self._transactions[tx_id] for tx_id in self._wallet_transactions[wallet_id])
        return tuple(sorted(txs, key=lambda tx: (tx.timestamp, tx.tx_id)))

    def counterparties_of(self, wallet_id: str) -> tuple[Counterparty, ...]:
        """Direct-flow aggregates involving a wallet, ordered by pair key.

        Only this wallet's indexed pairs are visited (same ordering as
        sorting every aggregated pair and filtering by membership).
        """
        self.wallet(wallet_id)
        return tuple(self._counterparties[key] for key in sorted(self._wallet_pairs[wallet_id]))

    def counterparty_pairs(self) -> tuple[Counterparty, ...]:
        """Every direct-flow aggregate in canonical order."""
        return tuple(self._counterparties[key] for key in sorted(self._counterparties))

    def cluster_of(self, wallet_id: str) -> AddressCluster | None:
        """The cluster a wallet belongs to, or ``None`` when unclustered."""
        self.wallet(wallet_id)
        cluster_id = self._wallet_cluster.get(wallet_id)
        return None if cluster_id is None else self._clusters[cluster_id]

    def shared_transactions(
        self, left_wallet_id: str, right_wallet_id: str
    ) -> tuple[Transaction, ...]:
        """Transactions both wallets participate in, ordered by (timestamp, tx_id)."""
        left = {tx.tx_id for tx in self.transactions_of(left_wallet_id)}
        shared = (tx for tx in self.transactions_of(right_wallet_id) if tx.tx_id in left)
        return tuple(shared)  # already ordered by transactions_of

    def summary(self) -> dict[str, object]:
        """Deterministic structural snapshot (used by tests and tooling)."""
        return {
            "wallet_ids": sorted(self._wallets),
            "tx_ids": sorted(self._transactions),
            "counterparties": [
                (flow.wallet_id, flow.counterparty_id, flow.transaction_count)
                for flow in self.counterparty_pairs()
            ],
            "clusters": [
                (cluster_id, sorted(self._clusters[cluster_id].wallet_ids))
                for cluster_id in sorted(self._clusters)
            ],
        }


def build_graph(
    wallets: Iterable[Wallet],
    transactions: Iterable[Transaction],
    clusters: Iterable[AddressCluster] = (),
) -> FinancialGraph:
    """Convenience: populate a graph in dependency order (wallets first)."""
    graph = FinancialGraph()
    for wallet in wallets:
        graph.add_wallet(wallet)
    for transaction in transactions:
        graph.add_transaction(transaction)
    for cluster in clusters:
        graph.add_cluster(cluster)
    return graph
