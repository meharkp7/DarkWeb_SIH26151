"""Attribution scoring and signal adapters."""

from aegis.attribution.adapters import (
    AttributionSignalBundle,
    from_behavior_similarity,
    from_explicit_channels,
    from_infrastructure_similarity,
    from_resolution_features,
)
from aegis.attribution.baseline import (
    AttributionBaseline,
    AttributionExample,
    AttributionScore,
    LogisticAttributionBaseline,
    TransparentAttributionBaseline,
    XgboostAttributionBaseline,
    all_baselines,
)

__all__ = [
    "AttributionBaseline",
    "AttributionExample",
    "AttributionScore",
    "AttributionSignalBundle",
    "LogisticAttributionBaseline",
    "TransparentAttributionBaseline",
    "XgboostAttributionBaseline",
    "all_baselines",
    "from_behavior_similarity",
    "from_explicit_channels",
    "from_infrastructure_similarity",
    "from_resolution_features",
]
