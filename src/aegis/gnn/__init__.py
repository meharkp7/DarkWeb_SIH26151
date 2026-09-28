"""Phase 19 temporal heterogeneous graph models."""

from aegis.gnn.graph import GnnNodeType, HeteroGraph
from aegis.gnn.models import (
    ContradictionAwareTemporalHGT,
    HGTEncoder,
    RGCNEncoder,
    TemporalHGTEncoder,
)
from aegis.gnn.store_adapter import build_gnn_graph
from aegis.gnn.torch_models import TemporalHeterogeneousGNN, TorchPairPrediction
from aegis.gnn.torch_training import (
    SplitPairs,
    TemporalPair,
    TrainingResult,
    split_by_group,
    train_pair_model,
)

__all__ = [
    "ContradictionAwareTemporalHGT",
    "GnnNodeType",
    "HGTEncoder",
    "HeteroGraph",
    "RGCNEncoder",
    "TemporalHGTEncoder",
    "TemporalHeterogeneousGNN",
    "TorchPairPrediction",
    "TemporalPair",
    "SplitPairs",
    "TrainingResult",
    "build_gnn_graph",
    "split_by_group",
    "train_pair_model",
]
