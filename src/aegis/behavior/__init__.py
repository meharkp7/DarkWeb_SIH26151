"""Behavioural profiling layer (Phase 12).

``raw events -> BehaviorProfile -> statistical similarity``

Sequence models are explicitly deferred (see
:mod:`aegis.behavior.similarity`); the baseline comparator is pure
statistics — cosine, Jensen-Shannon, chi-square, and scale-free scalar
agreement.
"""

from aegis.behavior.profile import (
    DAYS_PER_WEEK,
    DEFAULT_TOPIC_VOCABULARY,
    HOURS_PER_DAY,
    INTER_ARRIVAL_BIN_EDGES,
    INTER_ARRIVAL_BIN_LABELS,
    BehaviorProfile,
    PostingEvent,
    assign_topic,
    build_behavior_profile,
    events_from_corpus,
)
from aegis.behavior.similarity import (
    DEFAULT_WEIGHTS,
    ProfileSimilarity,
    chi_square_distance,
    compare_profiles,
    cosine_similarity,
    jensen_shannon,
    scalar_similarity,
)

__all__ = [
    "DEFAULT_TOPIC_VOCABULARY",
    "DEFAULT_WEIGHTS",
    "DAYS_PER_WEEK",
    "HOURS_PER_DAY",
    "INTER_ARRIVAL_BIN_EDGES",
    "INTER_ARRIVAL_BIN_LABELS",
    "BehaviorProfile",
    "ProfileSimilarity",
    "PostingEvent",
    "assign_topic",
    "build_behavior_profile",
    "chi_square_distance",
    "compare_profiles",
    "cosine_similarity",
    "events_from_corpus",
    "jensen_shannon",
    "scalar_similarity",
]
