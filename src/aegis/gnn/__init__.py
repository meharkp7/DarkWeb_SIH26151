"""Phase 19 temporal heterogeneous graph models.

The torch-backed models are imported **lazily**.

The numeric core here — `graph`, `models` — is numpy only, and is the part
the rest of the system and most of the test suite use. But an eager
``from aegis.gnn.torch_models import ...`` in this file made importing
``aegis.gnn.graph`` require torch, because a package's ``__init__`` always
runs first. That broke two things:

* the *numerical* model tests could not be collected in any job that does
  not install the ``ml`` extra, even though they do not need torch. The
  integration job is one of those, and it failed collection outright::

      tests/test_gnn_models.py:6: in <module>
          from aegis.gnn.graph import GnnNodeType, HeteroGraph
      src/aegis/gnn/__init__.py:11: in <module>
          from aegis.gnn.torch_models import ...
      src/aegis/gnn/torch_models.py:14: in <module>
          import torch
      E   ModuleNotFoundError: No module named 'torch'

  The fix was *not* to add a fourth ``--ignore`` to the integration job.
  Those are how the file was missed in the first place, and hiding a test
  that needs nothing hidden is a worse outcome than the one that caused it.

* the "ML stack is optional" property was not actually true of this
  package. Nothing outside ``aegis.gnn`` imports it today, so no deployed
  path was broken — but a package that cannot be imported without its
  optional dependency is one refactor away from breaking a free-tier deploy
  that has no torch.

``__getattr__`` (PEP 562) defers the torch import to first use and reports a
missing dependency by name, instead of a bare ``ModuleNotFoundError`` at
import time that names ``torch`` and not the thing that wanted it.
"""

from typing import TYPE_CHECKING, Any

from aegis.gnn.graph import GnnNodeType, HeteroGraph
from aegis.gnn.models import (
    ContradictionAwareTemporalHGT,
    HGTEncoder,
    RGCNEncoder,
    TemporalHGTEncoder,
)
from aegis.gnn.store_adapter import build_gnn_graph

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from aegis.gnn.torch_models import TemporalHeterogeneousGNN, TorchPairPrediction
    from aegis.gnn.torch_training import (
        SplitPairs,
        TemporalPair,
        TrainingResult,
        split_by_group,
        train_pair_model,
    )

#: Public name -> the module that actually defines it.
#:
#: Kept as data rather than a chain of ``if`` branches so a name cannot be
#: listed in ``__all__`` and quietly resolve to nothing.
_TORCH_EXPORTS: dict[str, str] = {
    "TemporalHeterogeneousGNN": "aegis.gnn.torch_models",
    "TorchPairPrediction": "aegis.gnn.torch_models",
    "SplitPairs": "aegis.gnn.torch_training",
    "TemporalPair": "aegis.gnn.torch_training",
    "TrainingResult": "aegis.gnn.torch_training",
    "split_by_group": "aegis.gnn.torch_training",
    "train_pair_model": "aegis.gnn.torch_training",
}

_EAGER = frozenset(
    {
        "ContradictionAwareTemporalHGT",
        "GnnNodeType",
        "HGTEncoder",
        "HeteroGraph",
        "RGCNEncoder",
        "TemporalHGTEncoder",
        "build_gnn_graph",
    }
)

__all__ = [
    "ContradictionAwareTemporalHGT",
    "GnnNodeType",
    "HGTEncoder",
    "HeteroGraph",
    "RGCNEncoder",
    "SplitPairs",
    "TemporalHGTEncoder",
    "TemporalHeterogeneousGNN",
    "TemporalPair",
    "TorchPairPrediction",
    "TrainingResult",
    "build_gnn_graph",
    "split_by_group",
    "train_pair_model",
]


def __getattr__(name: str) -> Any:
    """Resolve a torch-backed export on first access (PEP 562)."""
    module_name = _TORCH_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_name)
    try:
        value = getattr(module, name)
    except AttributeError as error:  # pragma: no cover - guards a stale export map
        raise AttributeError(
            f"{module_name!r} does not define {name!r}; the export map in "
            f"{__name__}.__init__ is out of date"
        ) from error
    # Cache on the module so the next access skips this entirely.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
