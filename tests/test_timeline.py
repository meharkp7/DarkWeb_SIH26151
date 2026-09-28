"""Phase 15 timeline and change-detection tests.

Covers the three plan objects, the three algorithm families against
hand-computed examples (CUSUM alarms, exact KS statistics, binary
segmentation gains), all five required detections, persistence/ flap
filtering, migration-candidate confidence, and an end-to-end scenario
where every plan target fires.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegis.graph import GraphValidationError
from aegis.timeline import (
    ACTIVITY_METHODS,
    ChangePoint,
    Direction,
    MigrationCandidate,
    TimelineEvent,
    TimelineEventKind,
    build_activity_series,
    build_migration_candidates,
    cusum,
    detect_activity_shifts,
    detect_handle_changes,
    detect_identifier_rotations,
    detect_infrastructure_changes,
    detect_marketplace_transitions,
    ks_distance,
    ks_gain,
    mean_shift_gain,
    segment,
)

T0 = datetime(2026, 3, 1, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def _event(
    event_id: str,
    kind: TimelineEventKind,
    observed_at: datetime,
    value: str,
    subject: str = "alias-1",
) -> TimelineEvent:
    return TimelineEvent(
        event_id=event_id,
        subject_id=subject,
        kind=kind,
        observed_at=observed_at,
        value=value,
    )


def _state_series(
    kind: TimelineEventKind,
    values: tuple[str, ...],
    *,
    subject: str = "alias-1",
    step: timedelta = timedelta(hours=6),
    prefix: str = "e",
) -> list[TimelineEvent]:
    return [
        _event(f"{prefix}-{index:03d}", kind, T0 + index * step, value, subject)
        for index, value in enumerate(values)
    ]


# ---------------------------------------------------------- object validation


def test_timeline_event_validation() -> None:
    good = _event("e1", TimelineEventKind.HANDLE, T0, "ghost")
    assert good.kind is TimelineEventKind.HANDLE
    assert len(TimelineEventKind) == 5  # exactly the plan's five channels
    with pytest.raises(ValueError, match="event_id"):
        _event("", TimelineEventKind.HANDLE, T0, "ghost")
    with pytest.raises(ValueError, match="subject_id"):
        _event("e1", TimelineEventKind.HANDLE, T0, "ghost", subject="")
    with pytest.raises(ValueError, match="value"):
        _event("e1", TimelineEventKind.HANDLE, T0, "  ")
    with pytest.raises(GraphValidationError, match="timezone-aware"):
        _event("e1", TimelineEventKind.HANDLE, datetime(2026, 1, 1), "ghost")


def test_change_point_validation() -> None:
    categorical = ChangePoint(
        change_id="cp-1",
        subject_id="alias-1",
        kind=TimelineEventKind.HANDLE,
        detector="state_change",
        changed_at=T0,
        score=1.0,
        from_value="a",
        to_value="b",
    )
    assert categorical.direction is None

    numeric = ChangePoint(
        change_id="cp-2",
        subject_id="alias-1",
        kind=TimelineEventKind.ACTIVITY,
        detector="cusum",
        changed_at=T0,
        score=3.5,
        direction=Direction.INCREASE,
    )
    assert numeric.from_value is None

    with pytest.raises(ValueError, match="score"):
        ChangePoint(
            change_id="cp",
            subject_id="a",
            kind=TimelineEventKind.ACTIVITY,
            detector="cusum",
            changed_at=T0,
            score=-1.0,
            direction=Direction.INCREASE,
        )
    with pytest.raises(ValueError, match="score"):
        ChangePoint(
            change_id="cp",
            subject_id="a",
            kind=TimelineEventKind.ACTIVITY,
            detector="cusum",
            changed_at=T0,
            score=float("nan"),
            direction=Direction.INCREASE,
        )
    with pytest.raises(ValueError, match="together"):
        ChangePoint(
            change_id="cp",
            subject_id="a",
            kind=TimelineEventKind.HANDLE,
            detector="state_change",
            changed_at=T0,
            score=1.0,
            from_value="only-one",
        )
    with pytest.raises(ValueError, match="differ"):
        ChangePoint(
            change_id="cp",
            subject_id="a",
            kind=TimelineEventKind.HANDLE,
            detector="state_change",
            changed_at=T0,
            score=1.0,
            from_value="same",
            to_value="same",
        )
    with pytest.raises(ValueError, match="no direction"):
        ChangePoint(
            change_id="cp",
            subject_id="a",
            kind=TimelineEventKind.HANDLE,
            detector="state_change",
            changed_at=T0,
            score=1.0,
            from_value="a",
            to_value="b",
            direction=Direction.INCREASE,
        )
    with pytest.raises(ValueError, match="direction"):
        ChangePoint(
            change_id="cp",
            subject_id="a",
            kind=TimelineEventKind.ACTIVITY,
            detector="cusum",
            changed_at=T0,
            score=1.0,  # numeric activity change without direction
        )


def test_migration_candidate_validation() -> None:
    good = MigrationCandidate(
        candidate_id="m1",
        subject_id="alias-1",
        kind=TimelineEventKind.MARKETPLACE,
        origin="market_alpha",
        destination="market_beta",
        changed_at=T0,
        confidence=0.9,
        supporting_change_points=("cp-1",),
        basis="state_change",
    )
    assert good.confidence == 0.9

    def make(**overrides: object) -> MigrationCandidate:
        base: dict[str, object] = {
            "candidate_id": "m1",
            "subject_id": "alias-1",
            "kind": TimelineEventKind.MARKETPLACE,
            "origin": "market_alpha",
            "destination": "market_beta",
            "changed_at": T0,
            "confidence": 0.9,
            "supporting_change_points": ("cp-1",),
            "basis": "state_change",
        }
        base.update(overrides)
        return MigrationCandidate(**base)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="differ"):
        make(destination="market_alpha")
    with pytest.raises(ValueError, match="supporting"):
        make(supporting_change_points=())
    with pytest.raises(ValueError, match="basis"):
        make(basis=" ")
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        make(confidence=1.2)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        make(confidence=-0.1)


# ---------------------------------------------------------- algorithms


def test_cusum_up_and_down_shifts() -> None:
    up = tuple(2.0 for _ in range(10)) + tuple(20.0 for _ in range(10))
    alarms = cusum(up, drift=1.0, threshold=5.0)
    positive = [(index, score) for index, score in alarms if score > 0]
    negative = [(index, score) for index, score in alarms if score < 0]
    assert positive, "the high phase must alarm"
    assert min(index for index, _ in positive) == 10  # first bucket after the shift
    assert all(score > 5.0 for _, score in positive)
    assert all(index < 10 for index, _ in negative)  # low phase alarms as decrease

    down = tuple(20.0 for _ in range(10)) + tuple(2.0 for _ in range(10))
    alarms = cusum(down, drift=1.0, threshold=5.0)
    negative = [index for index, score in alarms if score < 0]
    assert negative and min(negative) == 10
    assert all(index >= 10 for index, score in alarms if score < 0)

    flat = tuple(5.0 for _ in range(20))
    assert cusum(flat, drift=1.0, threshold=5.0) == ()


def test_cusum_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError, match="drift"):
        cusum([1.0, 2.0], drift=0.0, threshold=1.0)
    with pytest.raises(ValueError, match="threshold"):
        cusum([1.0, 2.0], drift=1.0, threshold=-1.0)
    with pytest.raises(ValueError, match="at least 2"):
        cusum([1.0], drift=1.0, threshold=1.0)
    with pytest.raises(ValueError, match="non-finite"):
        cusum([1.0, float("inf")], drift=1.0, threshold=1.0)


def test_ks_distance_exact_values() -> None:
    assert ks_distance([1.0, 2.0], [1.0, 2.0]) == 0.0  # identical
    assert ks_distance([1.0, 2.0], [3.0, 4.0]) == 1.0  # disjoint
    assert ks_distance([1.0, 2.0, 3.0], [2.0, 3.0, 4.0]) == pytest.approx(1 / 3)
    assert ks_distance([1.0, 2.0, 3.0, 4.0], [3.0, 4.0, 5.0, 6.0]) == pytest.approx(0.5)
    assert ks_gain([1.0, 2.0], [3.0, 4.0]) == 1.0
    with pytest.raises(ValueError, match="at least 1"):
        ks_distance([], [1.0])
    with pytest.raises(ValueError, match="non-finite"):
        ks_distance([1.0, float("nan")], [2.0])


def test_mean_shift_gain() -> None:
    # (n1*n2/(n1+n2)) * (mean1-mean2)^2 = (2*2/4) * (0-10)^2 = 100
    assert mean_shift_gain([0.0, 0.0], [10.0, 10.0]) == pytest.approx(100.0)
    assert mean_shift_gain([5.0, 5.0], [5.0]) == 0.0
    assert mean_shift_gain([], [1.0]) == 0.0


def test_segment_binary_segmentation_hand_computed() -> None:
    values = [0.0, 0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 10.0]
    splits = segment(values, gain=mean_shift_gain, min_size=2, min_gain=1.0)
    assert splits == ((4, pytest.approx(200.0)),)

    values = [0.0, 0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 10.0, 5.0, 5.0, 5.0, 5.0]
    splits = segment(values, gain=mean_shift_gain, min_size=2, min_gain=1.0)
    assert [index for index, _ in splits] == [4, 8]
    # top split: left mean 0, right mean 7.5 -> (4*8/12) * 7.5^2 = 150
    assert splits[0][1] == pytest.approx(150.0)
    assert splits[1][1] == pytest.approx(50.0)

    assert segment([1.0, 1.0, 1.0, 1.0], gain=mean_shift_gain, min_size=2, min_gain=1.0) == ()
    with pytest.raises(ValueError, match="min_size"):
        segment([1.0, 2.0], gain=mean_shift_gain, min_size=0, min_gain=0.0)
    with pytest.raises(ValueError, match="min_gain"):
        segment([1.0, 2.0], gain=mean_shift_gain, min_size=1, min_gain=-1.0)


# ---------------------------------------------------------- categorical detectors


def test_handle_changes_persistence_and_flap_filtering() -> None:
    events = _state_series(
        TimelineEventKind.HANDLE,
        ("ghost", "ghost", "phantom", "phantom", "phantom"),
    )
    changes = detect_handle_changes(events, min_persist=2)
    assert len(changes) == 1
    change = changes[0]
    assert change.change_id == "cp-handle-0001"
    assert change.from_value == "ghost"
    assert change.to_value == "phantom"
    assert change.detector == "state_change"
    assert change.changed_at == T0 + 2 * timedelta(hours=6)
    assert change.score == 1.0

    # a one-event flap (ghost -> phantom -> ghost) must not produce a change
    flappy = _state_series(
        TimelineEventKind.HANDLE,
        ("ghost", "ghost", "phantom", "ghost", "ghost"),
    )
    assert detect_handle_changes(flappy, min_persist=2) == ()

    # an unconfirmed change at the end of the stream is dropped
    trailing = _state_series(TimelineEventKind.HANDLE, ("a", "a", "b"))
    assert detect_handle_changes(trailing, min_persist=2) == ()
    # ... but min_persist=0 believes it immediately
    assert len(detect_handle_changes(trailing, min_persist=0)) == 1

    assert detect_handle_changes([]) == ()
    assert detect_handle_changes(events[:1]) == ()
    with pytest.raises(ValueError, match="min_persist"):
        detect_handle_changes(events, min_persist=-1)


def test_handle_detector_ignores_other_channels() -> None:
    events = _state_series(
        TimelineEventKind.HANDLE, ("h1", "h1", "h2", "h2", "h2")
    ) + _state_series(TimelineEventKind.MARKETPLACE, ("m1", "m2", "m3"), prefix="m")
    changes = detect_handle_changes(events, min_persist=2)
    assert [c.to_value for c in changes] == ["h2"]  # marketplace noise ignored


def test_other_three_state_detectors() -> None:
    cases = (
        (
            detect_marketplace_transitions,
            TimelineEventKind.MARKETPLACE,
            "cp-marketplace-0001",
        ),
        (
            detect_identifier_rotations,
            TimelineEventKind.IDENTIFIER,
            "cp-identifier-0001",
        ),
        (
            detect_infrastructure_changes,
            TimelineEventKind.INFRASTRUCTURE,
            "cp-infrastructure-0001",
        ),
    )
    for detector, kind, expected_id in cases:
        events = _state_series(kind, ("v1", "v1", "v2", "v2", "v2"))
        changes = detector(events, min_persist=2)
        assert len(changes) == 1
        assert changes[0].change_id == expected_id
        assert changes[0].kind is kind
        assert (changes[0].from_value, changes[0].to_value) == ("v1", "v2")


def test_state_detectors_reject_mixed_subjects() -> None:
    events = _state_series(TimelineEventKind.HANDLE, ("a", "a", "b", "b", "b")) + _state_series(
        TimelineEventKind.HANDLE,
        ("x", "x", "y", "y", "y"),
        subject="alias-2",
        prefix="other",
    )
    with pytest.raises(ValueError, match="one subject"):
        detect_handle_changes(events, min_persist=2)


# ---------------------------------------------------------- activity channel


def test_build_activity_series_zero_fills_gaps() -> None:
    events = [
        _event("a1", TimelineEventKind.ACTIVITY, T0, "post"),
        _event("a2", TimelineEventKind.ACTIVITY, T0 + 3 * HOUR, "post"),
        _event("a3", TimelineEventKind.ACTIVITY, T0 + 2 * DAY, "post"),
    ]
    series = build_activity_series(events)
    assert series == (
        (T0, 2.0),
        (T0 + DAY, 0.0),  # gap zero-filled: silence is signal
        (T0 + 2 * DAY, 1.0),
    )
    assert build_activity_series([]) == ()
    assert (
        build_activity_series([_event("a", TimelineEventKind.HANDLE, T0, "h")]) == ()
    )  # other channels are not activity
    with pytest.raises(ValueError, match="bucket"):
        build_activity_series(events, bucket=timedelta(0))


def test_detect_activity_shifts_cusum() -> None:
    # volume series: 2 events/day for ten days, then 20 events/day
    events: list[TimelineEvent] = []
    for index in range(10):
        for copy in range(2):
            events.append(
                _event(
                    f"low-{index}-{copy}",
                    TimelineEventKind.ACTIVITY,
                    T0 + index * DAY + copy * HOUR,
                    "post",
                )
            )
    for index in range(10, 20):
        for copy in range(20):
            events.append(
                _event(
                    f"high-{index}-{copy}",
                    TimelineEventKind.ACTIVITY,
                    T0 + index * DAY + copy * 5 * MINUTE,
                    "post",
                )
            )

    changes = detect_activity_shifts(events, method="cusum", drift=1.0, threshold=5.0)
    assert changes, "sustained volume jump must alarm"
    positive = [c for c in changes if c.direction is Direction.INCREASE]
    assert positive
    first = min(positive, key=lambda c: c.changed_at)
    assert first.changed_at == T0 + 10 * DAY  # first bucket after the shift
    assert first.detector == "cusum"
    assert all(c.kind is TimelineEventKind.ACTIVITY for c in changes)
    # negative alarms (the low phase vs the global mean) precede the shift
    assert all(c.changed_at < T0 + 10 * DAY for c in changes if c.direction is Direction.DECREASE)


def test_detect_activity_shifts_segmentation_methods() -> None:
    events = []
    for index in range(10):
        events.append(_event(f"lo-{index}", TimelineEventKind.ACTIVITY, T0 + index * DAY, "post"))
    for index in range(10, 20):
        for copy in range(10):
            events.append(
                _event(
                    f"hi-{index}-{copy}",
                    TimelineEventKind.ACTIVITY,
                    T0 + index * DAY + copy * HOUR,
                    "post",
                )
            )

    ks_changes = detect_activity_shifts(events, method="ks", min_size=2, min_gain=0.4)
    assert len(ks_changes) == 1  # disjoint phases split exactly once
    assert ks_changes[0].changed_at == T0 + 10 * DAY
    assert ks_changes[0].score == pytest.approx(1.0)
    assert ks_changes[0].direction is Direction.INCREASE

    bseg_changes = detect_activity_shifts(
        events, method="binary_segmentation", min_size=2, min_gain=1.0
    )
    assert len(bseg_changes) == 1
    assert bseg_changes[0].changed_at == T0 + 10 * DAY
    assert bseg_changes[0].detector == "binary_segmentation"
    assert bseg_changes[0].direction is Direction.INCREASE

    # both method families from the plan are addressable
    assert ACTIVITY_METHODS == {"cusum", "ks", "binary_segmentation"}


def test_detect_activity_shifts_edge_cases() -> None:
    flat = [_event(f"f-{i}", TimelineEventKind.ACTIVITY, T0 + i * DAY, "post") for i in range(12)]
    assert detect_activity_shifts(flat, method="cusum", drift=1.0, threshold=5.0) == ()
    assert detect_activity_shifts([], method="cusum") == ()
    sparse = [_event(f"s-{i}", TimelineEventKind.ACTIVITY, T0 + i * DAY, "post") for i in range(3)]
    assert detect_activity_shifts(sparse, method="cusum") == ()  # below bucket minimum
    with pytest.raises(ValueError, match="unknown method"):
        detect_activity_shifts(flat, method="prophet")


# ---------------------------------------------------------- migration


def test_migration_candidates_from_state_changes() -> None:
    events = _state_series(
        TimelineEventKind.MARKETPLACE,
        (
            "market_alpha",
            "market_alpha",
            "market_alpha",
            "market_beta",
            "market_beta",
            "market_beta",
            "market_beta",
        ),
        step=DAY,
        prefix="m",
    )
    changes = detect_marketplace_transitions(events, min_persist=2)
    candidates = build_migration_candidates(events, changes)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.candidate_id == "mig-cp-marketplace-0001"
    assert (candidate.origin, candidate.destination) == ("market_alpha", "market_beta")
    assert candidate.kind is TimelineEventKind.MARKETPLACE
    assert candidate.supporting_change_points == ("cp-marketplace-0001",)
    assert candidate.confidence == 1.0  # all later events still on beta
    assert "state_change" in candidate.basis

    # rollback: a second migration back with partial destination support
    rollback = _state_series(
        TimelineEventKind.MARKETPLACE,
        ("m1", "m1", "m1", "m2", "m2", "m2", "m1", "m1"),
        step=DAY,
        prefix="r",
    )
    changes = detect_marketplace_transitions(rollback, min_persist=1)
    candidates = build_migration_candidates(rollback, changes)
    assert [c.candidate_id for c in candidates] == [
        "mig-cp-marketplace-0001",
        "mig-cp-marketplace-0002",
    ]
    # candidate 1: later events are m2,m2,m1,m1 -> support 0.5
    assert candidates[0].confidence == pytest.approx(0.5)
    # candidate 2 (m2 -> m1): only later event is m1 -> support 1.0
    assert candidates[1].confidence == pytest.approx(1.0)
    assert candidates[1].origin == "m2" and candidates[1].destination == "m1"


def test_migration_candidates_skip_numeric_changes() -> None:
    events = [_event("a", TimelineEventKind.ACTIVITY, T0 + i * DAY, "post") for i in range(12)]
    changes = detect_activity_shifts(events, method="cusum", drift=1.0, threshold=5.0)
    assert build_migration_candidates(events, changes) == ()


# ---------------------------------------------------------- end to end


def test_all_five_plan_targets_detected() -> None:
    """One scenario exercising every detection target the plan lists."""
    events: list[TimelineEvent] = []
    events += _state_series(TimelineEventKind.HANDLE, ("h1", "h1", "h2", "h2", "h2"), prefix="h")
    events += _state_series(
        TimelineEventKind.MARKETPLACE, ("m1", "m1", "m2", "m2", "m2"), prefix="m"
    )
    events += _state_series(
        TimelineEventKind.IDENTIFIER,
        ("id-a", "id-a", "id-b", "id-b", "id-b"),
        prefix="i",
    )
    events += _state_series(
        TimelineEventKind.INFRASTRUCTURE,
        ("host-1", "host-1", "host-2", "host-2", "host-2"),
        prefix="n",
    )
    for index in range(6):  # quiet week
        events.append(_event(f"low-{index}", TimelineEventKind.ACTIVITY, T0 + index * DAY, "post"))
    for index in range(6, 12):  # burst week
        for copy in range(10):
            events.append(
                _event(
                    f"high-{index}-{copy}",
                    TimelineEventKind.ACTIVITY,
                    T0 + index * DAY + copy * HOUR,
                    "post",
                )
            )

    assert len(detect_handle_changes(events)) == 1
    assert len(detect_marketplace_transitions(events)) == 1
    assert len(detect_identifier_rotations(events)) == 1
    assert len(detect_infrastructure_changes(events)) == 1
    activity = detect_activity_shifts(events, method="cusum", drift=1.0, threshold=5.0)
    assert any(c.direction is Direction.INCREASE for c in activity)

    migrations = build_migration_candidates(events, [*detect_marketplace_transitions(events)])
    assert len(migrations) == 1
    assert migrations[0].confidence == 1.0
