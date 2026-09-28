"""Statistical similarity between behaviour profiles (Phase 12).

The plan says **"First use statistical similarity."** — so the
baseline comparator here is pure statistics: cosine for aligned
histograms, Jensen-Shannon divergence for distributions, a chi-square
distance for scaled counts, and a scale-free ratio agreement for
scalars. No learned parameters, no sequence models.

Planned future work (deliberately *not* implemented): sequence models
(HMMs, RNNs/GRUs, or transformers over the event stream) that could
capture ordering effects beyond these summary statistics. Per the plan
they are only to be added after baseline performance of this
statistical layer is understood and recorded — see
:func:`compare_profiles`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from aegis.behavior.profile import BehaviorProfile

#: Relative weights of the nine components in the ``overall`` score.
DEFAULT_WEIGHTS: dict[str, float] = {
    "hour": 1.5,
    "day": 1.0,
    "inter_arrival": 1.0,
    "topic": 1.0,
    "platform": 0.5,
    "response_latency": 1.0,
    "posting_rate": 1.0,
    "burstiness": 1.0,
    "interaction": 1.0,
}


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine of two non-negative histograms; 0.0 on mismatch/zero."""
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def jensen_shannon(left: Sequence[float], right: Sequence[float]) -> float:
    """Base-2 Jensen-Shannon divergence of two distributions in ``[0, 1]``.

    Length mismatches are aligned by zero-padding the shorter side.
    Zero-mass entries contribute ``0 * log2(0) = 0`` by convention, so
    sparse histograms are safe.
    """
    width = max(len(left), len(right))
    if width == 0:
        return 0.0
    p = list(left) + [0.0] * (width - len(left))
    q = list(right) + [0.0] * (width - len(right))
    p_total, q_total = sum(p), sum(q)
    if p_total == 0.0 and q_total == 0.0:
        return 0.0
    if p_total == 0.0 or q_total == 0.0:
        return 1.0
    p = [value / p_total for value in p]
    q = [value / q_total for value in q]
    divergence = 0.0
    for p_value, q_value in zip(p, q, strict=True):
        midpoint = 0.5 * (p_value + q_value)
        if p_value > 0.0:
            divergence += 0.5 * p_value * math.log2(p_value / midpoint) if midpoint else 0.0
        if q_value > 0.0:
            divergence += 0.5 * q_value * math.log2(q_value / midpoint) if midpoint else 0.0
    return max(0.0, min(1.0, divergence))


def chi_square_distance(left: Sequence[float], right: Sequence[float]) -> float:
    """Symmetric chi-square distance ``sqrt(0.5 * sum((p-q)^2/(p+q)))``.

    Length mismatches are zero-padded; bins where both sides are zero
    contribute nothing. Larger means more dissimilar (unbounded).
    """
    width = max(len(left), len(right))
    if width == 0:
        return 0.0
    p = list(left) + [0.0] * (width - len(left))
    q = list(right) + [0.0] * (width - len(right))
    total = 0.0
    for p_value, q_value in zip(p, q, strict=True):
        denominator = p_value + q_value
        if denominator > 0.0:
            difference = p_value - q_value
            total += difference * difference / denominator
    return math.sqrt(0.5 * total)


def scalar_similarity(left: float, right: float) -> float:
    """Scale-free agreement ``1 - |a - b| / (|a| + |b|)`` in ``[0, 1]``.

    Two zeros agree perfectly; opposite-sign values of equal magnitude
    disagree completely — which is the right behaviour for burstiness
    (strongly regular vs strongly bursty).
    """
    if left == 0.0 and right == 0.0:
        return 1.0
    return max(0.0, 1.0 - abs(left - right) / (abs(left) + abs(right)))


def _aligned_by_label(
    left_labels: Sequence[str],
    left_values: Sequence[float],
    right_labels: Sequence[str],
    right_values: Sequence[float],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Two label->distribution pairs aligned over the union of labels."""
    labels = sorted(set(left_labels) | set(right_labels))
    left_map = dict(zip(left_labels, left_values, strict=True))
    right_map = dict(zip(right_labels, right_values, strict=True))
    return (
        tuple(left_map.get(label, 0.0) for label in labels),
        tuple(right_map.get(label, 0.0) for label in labels),
    )


@dataclass(frozen=True)
class ProfileSimilarity:
    """Component and overall statistical similarity of two profiles.

    Every component lies in ``[0, 1]`` where 1.0 means "indistinguishable
    on this feature"; ``overall`` is the weighted mean of the nine
    components (see :data:`DEFAULT_WEIGHTS`).
    """

    hour: float
    day: float
    inter_arrival: float
    topic: float
    platform: float
    response_latency: float
    posting_rate: float
    burstiness: float
    interaction: float
    overall: float

    def components(self) -> dict[str, float]:
        """Component name -> value (excluding ``overall``)."""
        return {
            "hour": self.hour,
            "day": self.day,
            "inter_arrival": self.inter_arrival,
            "topic": self.topic,
            "platform": self.platform,
            "response_latency": self.response_latency,
            "posting_rate": self.posting_rate,
            "burstiness": self.burstiness,
            "interaction": self.interaction,
        }


def compare_profiles(
    left: BehaviorProfile,
    right: BehaviorProfile,
    *,
    weights: Mapping[str, float] | None = None,
) -> ProfileSimilarity:
    """Statistical similarity between two behaviour profiles.

    Baseline comparator per the plan: cosine similarity for the
    hour/day/platform histograms, ``1 - Jensen-Shannon`` for the
    inter-arrival and topic distributions, and scale-free agreement for
    the scalars (posting rate, burstiness, response latency,
    interaction degree).

    *Planned future work — not implemented here:* sequence models over
    the ordered event stream (HMMs, recurrent networks, transformers)
    to capture temporal dependencies these summary statistics cannot
    express. The plan requires understanding baseline performance
    first, so those are deferred until this statistical layer has been
    measured on real data.

    Args:
        left: First profile.
        right: Second profile.
        weights: Optional component weights *overlaying*
            :data:`DEFAULT_WEIGHTS`; unlisted components keep their
            defaults.
    """
    topic_left, topic_right = _aligned_by_label(
        left.topic_labels, left.topic_distribution, right.topic_labels, right.topic_distribution
    )
    platform_left, platform_right = _aligned_by_label(
        left.platform_labels,
        left.platform_distribution,
        right.platform_labels,
        right.platform_distribution,
    )

    components = {
        "hour": cosine_similarity(left.hour_of_day, right.hour_of_day),
        "day": cosine_similarity(left.day_of_week, right.day_of_week),
        "inter_arrival": 1.0
        - jensen_shannon(left.inter_arrival_distribution, right.inter_arrival_distribution),
        "topic": 1.0 - jensen_shannon(topic_left, topic_right),
        "platform": cosine_similarity(platform_left, platform_right),
        "response_latency": scalar_similarity(
            left.response_latency_mean, right.response_latency_mean
        ),
        "posting_rate": scalar_similarity(left.posting_rate, right.posting_rate),
        "burstiness": scalar_similarity(left.burstiness, right.burstiness),
        "interaction": scalar_similarity(left.interaction_degree, right.interaction_degree),
    }

    active_weights = dict(DEFAULT_WEIGHTS)
    if weights:
        active_weights.update(weights)
    unknown = set(active_weights) - set(components)
    if unknown:
        raise ValueError(f"weights refer to unknown components: {sorted(unknown)}")
    total_weight = sum(active_weights.get(name, 0.0) for name in components)
    if total_weight <= 0.0:
        raise ValueError("weights must sum to a positive value")

    overall = (
        sum(components[name] * active_weights.get(name, 0.0) for name in components) / total_weight
    )

    return ProfileSimilarity(
        hour=round(components["hour"], 6),
        day=round(components["day"], 6),
        inter_arrival=round(components["inter_arrival"], 6),
        topic=round(components["topic"], 6),
        platform=round(components["platform"], 6),
        response_latency=round(components["response_latency"], 6),
        posting_rate=round(components["posting_rate"], 6),
        burstiness=round(components["burstiness"], 6),
        interaction=round(components["interaction"], 6),
        overall=round(overall, 6),
    )
