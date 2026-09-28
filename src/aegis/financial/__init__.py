"""Financial graph (Phase 14).

The plan's four domain objects — Wallet, Transaction, Counterparty,
AddressCluster — a validated in-memory graph with derived flow
indexes, the six plan features (degree, frequency, temporal
burstiness, counterparty overlap, co-occurrence, cluster membership),
and a deterministic synthetic transaction-graph builder.  Synthetic
first per plan; live blockchain observation is deferred until a
permitted public source is approved.
"""

from aegis.financial.features import (
    FEATURE_NAMES,
    WalletFeatureExtractor,
    WalletPairFeatures,
    temporal_burstiness,
    validate_feature_registry,
)
from aegis.financial.graph import FinancialGraph, build_graph
from aegis.financial.synthetic import (
    DEFAULT_SYNTHETIC_SEED,
    build_synthetic_financial_graph,
)
from aegis.financial.types import (
    AddressCluster,
    Counterparty,
    Transaction,
    Wallet,
)

__all__ = [
    "DEFAULT_SYNTHETIC_SEED",
    "FEATURE_NAMES",
    "AddressCluster",
    "Counterparty",
    "FinancialGraph",
    "Transaction",
    "Wallet",
    "WalletFeatureExtractor",
    "WalletPairFeatures",
    "build_graph",
    "build_synthetic_financial_graph",
    "temporal_burstiness",
    "validate_feature_registry",
]
