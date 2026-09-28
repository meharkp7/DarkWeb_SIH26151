"""Timeline and change detection (Phase 15).

The plan's three objects (TimelineEvent, ChangePoint,
MigrationCandidate), the three algorithm families (CUSUM, distribution
distance / KS, ruptures-style binary segmentation — reimplemented in
pure Python, no new dependency), the five required detections (handle
changes, activity shifts, marketplace transitions, identifier
rotations, infrastructure changes), and migration-candidate
construction with data-derived confidence.
"""

from aegis.timeline.algorithms import (
    cusum,
    ks_distance,
    ks_gain,
    mean_shift_gain,
    segment,
)
from aegis.timeline.detectors import (
    ACTIVITY_METHODS,
    DEFAULT_ACTIVITY_BUCKET,
    DEFAULT_MIN_PERSIST,
    build_activity_series,
    build_migration_candidates,
    detect_activity_shifts,
    detect_handle_changes,
    detect_identifier_rotations,
    detect_infrastructure_changes,
    detect_marketplace_transitions,
)
from aegis.timeline.types import (
    CATEGORICAL_KINDS,
    ChangePoint,
    Direction,
    MigrationCandidate,
    TimelineEvent,
    TimelineEventKind,
)

__all__ = [
    "ACTIVITY_METHODS",
    "CATEGORICAL_KINDS",
    "DEFAULT_ACTIVITY_BUCKET",
    "DEFAULT_MIN_PERSIST",
    "ChangePoint",
    "Direction",
    "MigrationCandidate",
    "TimelineEvent",
    "TimelineEventKind",
    "build_activity_series",
    "build_migration_candidates",
    "cusum",
    "detect_activity_shifts",
    "detect_handle_changes",
    "detect_identifier_rotations",
    "detect_infrastructure_changes",
    "detect_marketplace_transitions",
    "ks_distance",
    "ks_gain",
    "mean_shift_gain",
    "segment",
]
