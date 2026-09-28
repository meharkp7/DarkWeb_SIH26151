"""Timeline detectors (Phase 15).

The plan's five detection targets, one per channel:

============================  ==========================================
plan target                   detector
============================  ==========================================
handle changes                :func:`detect_handle_changes`
activity shifts               :func:`detect_activity_shifts`
marketplace transitions       :func:`detect_marketplace_transitions`
identifier rotations          :func:`detect_identifier_rotations`
infrastructure changes        :func:`detect_infrastructure_changes`
============================  ==========================================

Categorical channels (handle, marketplace, identifier, infrastructure)
use **state-change detection with persistence confirmation**: a change
is only emitted when the new value persists for ``min_persist``
following events — single-event flaps are dropped, and a change at the
end of the stream that never gets its confirmation window is dropped
too (documented, deliberate: unconfirmed transitions are noise).

The numeric channel (activity) buckets ``kind=ACTIVITY`` events into a
count series and runs one of the plan's algorithms — ``cusum``,
``ks`` (distribution distance), or ``binary_segmentation``
(mean-shift cost, the ``ruptures``-style recursive split).

:func:`build_migration_candidates` turns confirmed categorical change
points into :class:`~aegis.timeline.types.MigrationCandidate`
records with a data-derived confidence: the fraction of the subject's
later events on that channel still showing the destination value.

Evidence propagation
--------------------
Every emitted :class:`~aegis.timeline.types.ChangePoint` /
:class:`~aegis.timeline.types.MigrationCandidate` cites the immutable
evidence behind its claim via ``evidence_ids``:

* state changes cite the change event **and** its ``min_persist``
  confirmation events (together they justify the claim);
* activity shifts cite the events falling in the bucket where the
  detector fired (epoch-aligned bucketing shared with
  :func:`build_activity_series` via :func:`_bucket_key`);
* migration candidates inherit their supporting change point's ids.

Ordering is deterministic: ids are deduplicated **preserving
first-seen order** (chronological event order, then id order within
an event), so identical inputs always yield identical citations.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from aegis.timeline.algorithms import cusum, ks_gain, mean_shift_gain, segment
from aegis.timeline.types import (
    ChangePoint,
    Direction,
    MigrationCandidate,
    TimelineEvent,
    TimelineEventKind,
)

#: Activity series bucket (plan's fixture cadence is daily).
DEFAULT_ACTIVITY_BUCKET = timedelta(days=1)
#: Activity detection methods (plan's three algorithm families).
ACTIVITY_METHODS: frozenset[str] = frozenset({"cusum", "ks", "binary_segmentation"})

#: Default confirmation windows: state changes must persist across this
#: many following events before they are believed (anti-flap).
DEFAULT_MIN_PERSIST = 2

#: Default per-method detection thresholds (tune per dataset; chosen so
#: daily-count series with shifts of several events per bucket alarm).
_DEFAULT_CUSUM_DRIFT = 1.0
_DEFAULT_CUSUM_THRESHOLD = 5.0
_DEFAULT_MIN_GAIN: dict[str, float] = {"ks": 0.3, "binary_segmentation": 1.0}


def _channel_events(
    events: Sequence[TimelineEvent], kind: TimelineEventKind
) -> list[TimelineEvent]:
    """Filter to one channel, require a single subject, order by time."""
    selected = [event for event in events if event.kind is kind]
    if not selected:
        return []
    subjects = sorted({event.subject_id for event in selected})
    if len(subjects) > 1:
        raise ValueError(f"{kind.value} events must share one subject, got {subjects}")
    return sorted(selected, key=lambda event: (event.observed_at, event.event_id))


def _bucket_key(stamp: datetime, bucket: timedelta) -> int:
    """Epoch-aligned bucket index — the single source of bucketing math.

    Shared by :func:`build_activity_series` (counting) and
    :func:`detect_activity_shifts` (evidence attribution) so a change
    point's ``evidence_ids`` cite exactly the events in the bucket its
    ``changed_at`` stamps — never a neighbouring bucket.
    """
    return int(stamp.timestamp() // bucket.total_seconds())


def _union_evidence(events: Sequence[TimelineEvent]) -> tuple[str, ...]:
    """Union of the events' ``evidence_ids`` in first-seen order.

    Deterministic: events arrive in chronological order and ids keep
    the order they appear within each event; duplicates are dropped
    without reordering.
    """
    return tuple(dict.fromkeys(eid for event in events for eid in event.evidence_ids))


def _detect_state_changes(
    events: Sequence[TimelineEvent],
    kind: TimelineEventKind,
    *,
    min_persist: int,
    prefix: str,
) -> tuple[ChangePoint, ...]:
    """Confirmed value transitions on one categorical channel.

    A change point cites the evidence of the change event **and** its
    ``min_persist`` confirmation events — together they are what
    justifies the claim (with ``min_persist=0`` the change event
    alone).
    """
    if min_persist < 0:
        raise ValueError("min_persist must be >= 0")
    selected = _channel_events(events, kind)
    if len(selected) < 2:
        return ()

    changes: list[ChangePoint] = []
    previous = selected[0].value
    for index in range(1, len(selected)):
        current = selected[index].value
        if current == previous:
            continue
        confirmations = selected[index + 1 : index + 1 + min_persist]
        if len(confirmations) != min_persist:
            continue  # not enough runway left in the stream
        if not all(event.value == current for event in confirmations):
            continue  # flap: the new value did not persist
        supporting = (selected[index], *confirmations)
        changes.append(
            ChangePoint(
                change_id=f"cp-{prefix}-{len(changes) + 1:04d}",
                subject_id=selected[index].subject_id,
                kind=kind,
                detector="state_change",
                changed_at=selected[index].observed_at,
                score=1.0,
                from_value=previous,
                to_value=current,
                # the claim rests on the change event + its confirmations
                evidence_ids=_union_evidence(supporting),
            )
        )
        previous = current
    return tuple(changes)


def detect_handle_changes(
    events: Sequence[TimelineEvent],
    *,
    min_persist: int = DEFAULT_MIN_PERSIST,
) -> tuple[ChangePoint, ...]:
    """Handle changes: confirmed transitions on the handle channel."""
    return _detect_state_changes(
        events, TimelineEventKind.HANDLE, min_persist=min_persist, prefix="handle"
    )


def detect_marketplace_transitions(
    events: Sequence[TimelineEvent],
    *,
    min_persist: int = DEFAULT_MIN_PERSIST,
) -> tuple[ChangePoint, ...]:
    """Marketplace transitions: confirmed platform moves."""
    return _detect_state_changes(
        events,
        TimelineEventKind.MARKETPLACE,
        min_persist=min_persist,
        prefix="marketplace",
    )


def detect_identifier_rotations(
    events: Sequence[TimelineEvent],
    *,
    min_persist: int = DEFAULT_MIN_PERSIST,
) -> tuple[ChangePoint, ...]:
    """Identifier rotations: confirmed identifier replacements."""
    return _detect_state_changes(
        events,
        TimelineEventKind.IDENTIFIER,
        min_persist=min_persist,
        prefix="identifier",
    )


def detect_infrastructure_changes(
    events: Sequence[TimelineEvent],
    *,
    min_persist: int = DEFAULT_MIN_PERSIST,
) -> tuple[ChangePoint, ...]:
    """Infrastructure changes: confirmed host/cert/service moves."""
    return _detect_state_changes(
        events,
        TimelineEventKind.INFRASTRUCTURE,
        min_persist=min_persist,
        prefix="infrastructure",
    )


def build_activity_series(
    events: Sequence[TimelineEvent],
    *,
    bucket: timedelta = DEFAULT_ACTIVITY_BUCKET,
) -> tuple[tuple[datetime, float], ...]:
    """Per-bucket event counts on the activity channel.

    Buckets are aligned to absolute multiples of ``bucket`` from the
    Unix epoch and **gaps are zero-filled** (silence is signal for
    change detection).  Returns ``()`` for an empty channel.
    """
    if bucket <= timedelta(0):
        raise ValueError("bucket must be positive")
    selected = _channel_events(events, TimelineEventKind.ACTIVITY)
    if not selected:
        return ()

    bucket_seconds = bucket.total_seconds()
    counts: dict[int, float] = {}
    for event in selected:
        key = _bucket_key(event.observed_at, bucket)
        counts[key] = counts.get(key, 0.0) + 1.0

    lowest, highest = min(counts), max(counts)
    series: list[tuple[datetime, float]] = []
    for key in range(lowest, highest + 1):
        stamp = datetime.fromtimestamp(round(key * bucket_seconds), tz=UTC)
        series.append((stamp, counts.get(key, 0.0)))
    return tuple(series)


def detect_activity_shifts(
    events: Sequence[TimelineEvent],
    *,
    bucket: timedelta = DEFAULT_ACTIVITY_BUCKET,
    method: str = "cusum",
    drift: float = _DEFAULT_CUSUM_DRIFT,
    threshold: float = _DEFAULT_CUSUM_THRESHOLD,
    min_gain: float | None = None,
    min_size: int = 3,
) -> tuple[ChangePoint, ...]:
    """Activity shifts: change points on the bucketed activity counts.

    ``method`` selects the plan's algorithm family: ``cusum`` (alarm
    indices with signed magnitude), ``ks`` (recursive segmentation by
    distribution distance), or ``binary_segmentation`` (recursive
    segmentation by mean-shift gain — the ``ruptures``-style
    reimplemented here).  ``changed_at`` is the start of the bucket
    where the detector fired — for CUSUM that is an upper bound on
    when the shift began, documented as approximate.

    Each change point's ``evidence_ids`` is the union of the evidence
    ids of the activity events inside the fired bucket (computed with
    the same epoch-aligned bucketing as :func:`build_activity_series`,
    deduped first-seen order).  A detector firing inside a zero-filled
    gap bucket cites no evidence (``()``) — honest: no event backs it.
    """
    if method not in ACTIVITY_METHODS:
        raise ValueError(f"unknown method {method!r}; expected one of {sorted(ACTIVITY_METHODS)}")
    selected = _channel_events(events, TimelineEventKind.ACTIVITY)
    if not selected:
        return ()
    subject_id = selected[0].subject_id
    series = build_activity_series(selected, bucket=bucket)
    values = [count for _, count in series]
    if len(values) < max(2 * min_size, 4):
        return ()  # too few buckets to claim a change

    detections: list[tuple[int, float, Direction]] = []
    if method == "cusum":
        for index, signed_score in cusum(values, drift=drift, threshold=threshold):
            direction = Direction.INCREASE if signed_score > 0.0 else Direction.DECREASE
            detections.append((index, abs(signed_score), direction))
    else:
        gain = ks_gain if method == "ks" else mean_shift_gain
        floor = _DEFAULT_MIN_GAIN[method] if min_gain is None else min_gain
        for index, split_gain in segment(values, gain=gain, min_size=min_size, min_gain=floor):
            before = values[:index]
            after = values[index:]
            direction = (
                Direction.INCREASE
                if sum(after) / len(after) > sum(before) / len(before)
                else Direction.DECREASE
            )
            detections.append((index, split_gain, direction))

    changes: list[ChangePoint] = []
    for index, score, direction in sorted(detections):
        fired_at = series[index][0]
        fired_key = _bucket_key(fired_at, bucket)
        in_bucket = [
            event for event in selected if _bucket_key(event.observed_at, bucket) == fired_key
        ]
        changes.append(
            ChangePoint(
                change_id=f"cp-activity-{len(changes) + 1:04d}",
                subject_id=subject_id,
                kind=TimelineEventKind.ACTIVITY,
                detector=method,
                changed_at=fired_at,
                score=score,
                direction=direction,
                # cite only the events inside the fired bucket
                evidence_ids=_union_evidence(in_bucket),
            )
        )
    return tuple(changes)


def build_migration_candidates(
    events: Sequence[TimelineEvent],
    changes: Sequence[ChangePoint],
) -> tuple[MigrationCandidate, ...]:
    """Confirmed categorical change points -> migration candidates.

    Numeric change points (activity shifts) are skipped — they describe
    cadence, not a move.  Confidence is the fraction of the subject's
    later events on the same channel that still show the destination
    value; ``basis`` states the detector that produced the change.
    Each candidate inherits ``evidence_ids`` from its supporting change
    point (first-seen order preserved from the detector).
    """
    candidates: list[MigrationCandidate] = []
    for change in changes:
        if change.from_value is None or change.to_value is None:
            continue  # numeric change point: not a migration
        after = [
            event
            for event in _channel_events(events, change.kind)
            if event.observed_at > change.changed_at
        ]
        support = (
            sum(1 for event in after if event.value == change.to_value) / len(after)
            if after
            else 0.0
        )
        candidates.append(
            MigrationCandidate(
                candidate_id=f"mig-{change.change_id}",
                subject_id=change.subject_id,
                kind=change.kind,
                origin=change.from_value,
                destination=change.to_value,
                changed_at=change.changed_at,
                confidence=support,
                supporting_change_points=(change.change_id,),
                basis=(
                    f"state_change persistence on {change.kind.value} events "
                    f"(detector={change.detector})"
                ),
                # the migration cites exactly what its change point cited
                evidence_ids=change.evidence_ids,
            )
        )
    return tuple(
        sorted(candidates, key=lambda candidate: (candidate.changed_at, candidate.candidate_id))
    )


__all__ = [
    "ACTIVITY_METHODS",
    "DEFAULT_ACTIVITY_BUCKET",
    "DEFAULT_MIN_PERSIST",
    "build_activity_series",
    "build_migration_candidates",
    "detect_activity_shifts",
    "detect_handle_changes",
    "detect_identifier_rotations",
    "detect_infrastructure_changes",
    "detect_marketplace_transitions",
]
