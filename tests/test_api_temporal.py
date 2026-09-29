"""The behavioural change surface, against a real database.

Five claims are worth testing harder than the rest, because they are the ones a
reader of the panel would otherwise have to take on trust:

* **the shift is derived, not stored.**  There is no "shift" row anywhere in
  the schema, and the strongest available proof is to recompute the expected
  answer here with the platform's own detector over the same stored rows and
  assert the endpoint agrees with it — value, timestamp and all.  A private
  scorer anywhere in the router would fail that.
* **the boundary is the real one.**  Each fixture series carries the date it was
  built to break on, and the test asserts the reported change lands there rather
  than merely that *something* was reported.
* **a short window is refused, not scored.**  The detectors return ``()`` when
  there is too little to analyse, which on the wire is indistinguishable from
  "no change found".  Every one of those has to surface as a refusal carrying
  the count supplied and the count required.
* **limitations survive the trip.**  A detector's caveats are the difference
  between a finding and an accusation, and an edge that drops them is a lie told
  by omission.
* **the control really is a control.**  Every fixture includes a subject whose
  cadence is flat.  A detector that fires on it has not been shown to detect
  anything.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from aegis.api.app import app
from aegis.api.temporal import (
    COMMON_LIMITATIONS,
    DETECTOR_LIMITATIONS,
    SERVICE_MIN_GAIN,
    activity_min_buckets,
    state_min_events,
)
from aegis.db.models import (
    ActorIdentifierRecord,
    ActorMarketplaceRecord,
    ActorRecord,
    ArtifactRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    SourceRecord,
    TemporalObservationRecord,
)
from aegis.db.session import SessionLocal
from aegis.timeline.detectors import (
    build_activity_series,
    detect_activity_shifts,
    detect_handle_changes,
    detect_marketplace_transitions,
)
from aegis.timeline.types import TimelineEvent, TimelineEventKind

pytestmark = pytest.mark.integration

#: Unique per module run: the fixtures are cleaned up but a run that dies
#: mid-way must not collide with the next one.
RUN_ID = uuid.uuid4().hex[:8]
PREFIX = f"temporal-test-{RUN_ID}"

#: Midnight UTC, so a fixture "day N" is bucket N and the expected boundary is a
#: date an assertion can name.
BASE = datetime(2026, 6, 1, tzinfo=UTC)

#: Where each seeded series is built to break.  The tests assert the detected
#: boundary lands on this day, so a fixture that stopped being shaped would fail
#: rather than quietly stop proving anything.
BREAK_DAY = 20
SERIES_DAYS = 40

#: Two pools an order of magnitude apart, drawn with ±1 jitter.  Jitter is
#: deliberate: a constant series would make detection trivially easy, and the
#: steady control below is the only thing that shows the detector is not simply
#: firing on every subject.
COLD = (1, 2, 2, 3)
HOT = (9, 10, 10, 11, 12)
STEADY = (3, 4, 4, 5)

VENUE_A = "temporal-a.market.example"
VENUE_B = "temporal-b.market.example"


class _World:
    """Identifiers the API needs, created once for the module."""

    def __init__(self) -> None:
        self.case_id: uuid.UUID
        self.short_case_id: uuid.UUID
        self.empty_case_id: uuid.UUID
        self.entity_id: uuid.UUID
        self.short_entity_id: uuid.UUID
        self.breaking_actor_id: uuid.UUID
        self.mover_actor_id: uuid.UUID
        self.steady_actor_id: uuid.UUID
        self.bare_actor_id: uuid.UUID
        self.breaking_handle: str
        self.mover_handle: str
        self.activity_events: list[TimelineEvent]


def _day(day: int, hour: int = 8) -> datetime:
    return BASE + timedelta(days=day, hours=hour)


def _at(value: str) -> datetime:
    """Parse a timestamp out of a response.

    Pydantic serialises a UTC ``datetime`` with a ``Z`` suffix and the library
    returns ``+00:00`` for the same moment, so comparisons go through parsed
    values. Asserting on the string would be asserting on a serialiser.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _activity_events(subject: str, days: int, break_day: int, pools: tuple) -> list[TimelineEvent]:
    """``days`` daily buckets, ``pools[0]`` before the break and ``pools[1]`` after.

    One event per unit of activity, because ``build_activity_series`` counts
    *events* per bucket and ignores any stored magnitude. A single row carrying
    ``magnitude=10`` would chart as ten and detect as one.
    """
    events: list[TimelineEvent] = []
    for day in range(days):
        pool = pools[1] if day >= break_day else pools[0]
        # The day's volume is drawn from the pool by the day alone; the inner
        # index only places the sighting within the day.
        count = pool[(day * 3) % len(pool)]
        for index in range(count):
            events.append(
                TimelineEvent(
                    event_id=f"{subject}:act:{day}:{index}",
                    subject_id=subject,
                    kind=TimelineEventKind.ACTIVITY,
                    observed_at=_day(day, 8 + index % 10),
                    value="post",
                    # Cites the fixture's own synthetic reference. A real
                    # observation would carry a ledger id; what matters to the
                    # library, and to this test, is that it is non-empty and
                    # travels with the event.
                    evidence_ids=(f"fixture:{subject}:{day}:{index}",),
                )
            )
    return events


def _state_events(
    subject: str, values: tuple[str, str], days: int, break_day: int, step: int
) -> list[TimelineEvent]:
    """Categorical sightings on each side of a move, one every ``step`` days."""
    events: list[TimelineEvent] = []
    for day in range(0, days, step):
        value = values[1] if day >= break_day else values[0]
        events.append(
            TimelineEvent(
                event_id=f"{subject}:state:{day}",
                subject_id=subject,
                kind=TimelineEventKind.HANDLE,
                observed_at=_day(day, 9),
                value=value,
                evidence_ids=(f"fixture:{subject}:state:{day}",),
            )
        )
    return events


def _persist(
    db: Any,
    events: list[TimelineEvent],
    *,
    case_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    entity_id: uuid.UUID | None,
    subject_kind: str,
    kind_for: Any,
) -> int:
    """Write a fixture event list into ``temporal_observations``."""
    rows = [
        TemporalObservationRecord(
            observation_id=uuid.uuid5(uuid.NAMESPACE_URL, event.event_id),
            case_id=case_id,
            actor_id=actor_id,
            entity_id=entity_id,
            subject_id=event.subject_id,
            subject_kind=subject_kind,
            channel=kind_for(event.kind),
            observed_at=event.observed_at,
            value=event.value,
            magnitude=1.0 if event.kind is TimelineEventKind.ACTIVITY else None,
            evidence_id=None,
            source_id=None,
            metadata_json={"synthetic": True, "fixture": RUN_ID},
        )
        for event in events
    ]
    db.add_all(rows)
    db.flush()
    return len(rows)


def _channel_for(kind: TimelineEventKind) -> str:
    if kind is TimelineEventKind.HANDLE:
        return "handle"
    if kind is TimelineEventKind.MARKETPLACE:
        return "marketplace"
    return "activity"


@pytest.fixture(scope="module")
def world() -> Iterator[_World]:
    db = SessionLocal()
    fixture = _World()
    source = SourceRecord(
        source_type="marketplace",
        name=f"{PREFIX}-source",
        reliability=0.7,
        metadata_json={"synthetic": True},
    )
    case = CaseRecord(name=f"{PREFIX}-rich", status="open")
    short_case = CaseRecord(name=f"{PREFIX}-short", status="open")
    # A case with nothing in it: no observations, no evidence, no audit entries.
    # It exists to prove the surface refuses to answer rather than answering
    # "nothing changed".
    empty_case = CaseRecord(name=f"{PREFIX}-empty", status="open")
    db.add_all([source, case, short_case, empty_case])
    db.flush()

    artifacts = [
        ArtifactRecord(
            artifact_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-artifact-{index}"),
            sha256=f"{RUN_ID}{index}".ljust(64, "0"),
            storage_uri=f"synthetic://aegis/temporal/{index}",
            media_type="application/json",
            size_bytes=256,
        )
        for index in range(4)
    ]
    db.add_all(artifacts)
    db.flush()

    evidence: list[EvidenceRecord] = []
    for index, artifact in enumerate(artifacts):
        evidence.append(
            EvidenceRecord(
                evidence_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-evidence-{index}"),
                case_id=case.case_id,
                source_id=source.source_id,
                source_type="marketplace",
                observed_at=_day(index),
                collected_at=_day(index, 9),
                entity_type="actor",
                entity_value_hash=f"{RUN_ID}{index}".ljust(64, "1"),
                context_hash=f"{RUN_ID}{index}".ljust(64, "2"),
                raw_artifact_uri=f"synthetic://aegis/temporal/evidence/{index}",
                artifact_id=artifact.artifact_id,
                sha256=artifact.sha256,
                collector_name="temporal-fixture",
                collector_version="1.0.0",
                source_reliability=0.7,
                independence_group="temporal-fixture",
                metadata_json={"synthetic": True, "fixture": RUN_ID},
            )
        )
    db.add_all(evidence)
    db.flush()

    entities = [
        EntityRecord(
            entity_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-entity-{index}"),
            case_id=case.case_id,
            evidence_id=row.evidence_id,
            entity_type="actor",
            surface_form=f"{PREFIX}-entity-{index}",
            normalized_form=f"{PREFIX}-entity-{index}",
            confidence=0.8,
            first_seen=_day(0),
            last_seen=_day(SERIES_DAYS),
            metadata_json={"synthetic": True},
        )
        for index, row in enumerate(evidence)
    ]
    # One entity per case, so the entity series is unambiguously that case's.
    short_entity = EntityRecord(
        entity_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-entity-short"),
        case_id=short_case.case_id,
        evidence_id=evidence[0].evidence_id,
        entity_type="actor",
        surface_form=f"{PREFIX}-entity-short",
        normalized_form=f"{PREFIX}-entity-short",
        confidence=0.8,
        first_seen=_day(0),
        last_seen=_day(2),
        metadata_json={"synthetic": True},
    )
    db.add_all([*entities, short_entity])
    db.flush()

    actors = [
        ActorRecord(
            actor_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-actor-{slug}"),
            handle=f"{PREFIX}-{slug}",
            category="test",
            status="active",
            confidence=0.8,
            first_seen=_day(0),
            last_seen=_day(SERIES_DAYS),
            last_scan_at=_day(1),
            source_id=source.source_id,
            metadata_json={"synthetic": True},
        )
        for slug in ("breaking", "mover", "steady", "bare")
    ]
    db.add_all(actors)
    db.flush()

    breaking, mover, steady, bare = actors
    identifiers = [
        ActorIdentifierRecord(
            identifier_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-identifier-{slug}"),
            actor_id=actor.actor_id,
            kind="handle",
            value=actor.handle,
            confidence=0.8,
            first_seen=_day(0),
            last_seen=_day(SERIES_DAYS),
            source_id=source.source_id,
            # The honest bridge from a cross-case persona to an investigation:
            # this identifier was seen in this case.
            case_id=case.case_id if actor.actor_id in {breaking.actor_id, mover.actor_id} else None,
            metadata_json={"synthetic": True},
        )
        for slug, actor in zip(("breaking", "mover", "steady", "bare"), actors, strict=True)
    ]
    db.add_all(identifiers)

    # Registry presence windows, so the transition route can return them beside
    # the detections and the two can be read against each other.
    db.add_all(
        [
            ActorMarketplaceRecord(
                presence_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-presence-{venue}"),
                actor_id=mover.actor_id,
                marketplace=venue,
                role="vendor",
                first_seen=_day(0, 9),
                last_seen=_day(29, 9),
                listing_count=12,
                source_id=source.source_id,
                metadata_json={"synthetic": True},
            )
            for venue in (VENUE_A, VENUE_B)
        ]
    )

    # --- the seeded series ------------------------------------------------
    entity_events = _activity_events(
        str(entities[0].entity_id), SERIES_DAYS, BREAK_DAY, (COLD, HOT)
    )
    _persist(
        db,
        entity_events,
        case_id=case.case_id,
        actor_id=None,
        entity_id=entities[0].entity_id,
        subject_kind="entity",
        kind_for=_channel_for,
    )
    # A control: a flat series on the same case, which must produce nothing.
    _persist(
        db,
        _activity_events(str(entities[1].entity_id), SERIES_DAYS, BREAK_DAY, (STEADY, STEADY)),
        case_id=case.case_id,
        actor_id=None,
        entity_id=entities[1].entity_id,
        subject_kind="entity",
        kind_for=_channel_for,
    )
    # Too short to analyse: three buckets, where a KS statistic is a number and
    # not a change.
    _persist(
        db,
        _activity_events(str(short_entity.entity_id), 3, 2, (COLD, HOT)),
        case_id=short_case.case_id,
        actor_id=None,
        entity_id=short_entity.entity_id,
        subject_kind="entity",
        kind_for=_channel_for,
    )

    breaking_activity = _activity_events(
        str(breaking.actor_id), SERIES_DAYS, BREAK_DAY, (COLD, HOT)
    )
    breaking_handle = _state_events(
        str(breaking.actor_id),
        (breaking.handle, f"{breaking.handle}_v2"),
        SERIES_DAYS,
        BREAK_DAY,
        1,
    )
    _persist(
        db,
        breaking_activity + breaking_handle,
        case_id=None,
        actor_id=breaking.actor_id,
        entity_id=None,
        subject_kind="actor",
        kind_for=_channel_for,
    )

    mover_activity = _activity_events(str(mover.actor_id), SERIES_DAYS, BREAK_DAY, (STEADY, STEADY))
    mover_market = [
        TimelineEvent(
            event_id=f"{mover.actor_id}:mkt:{index}",
            subject_id=str(mover.actor_id),
            kind=TimelineEventKind.MARKETPLACE,
            observed_at=_day(index * 2, 9),
            # Day-based, not index-based: with a two-day sighting cadence the
            # break is at day 20, which is the tenth sighting.
            value=VENUE_B if index * 2 >= BREAK_DAY else VENUE_A,
            evidence_ids=(f"fixture:{mover.actor_id}:mkt:{index}",),
        )
        for index in range(SERIES_DAYS // 2)
    ]
    _persist(
        db,
        mover_activity + mover_market,
        case_id=None,
        actor_id=mover.actor_id,
        entity_id=None,
        subject_kind="actor",
        kind_for=_channel_for,
    )

    _persist(
        db,
        # The steady control also has a marketplace stream that never moves, so
        # "analysed and found nothing" is distinguishable from "too short to
        # analyse" — two very different things for a registry entry.
        _activity_events(str(steady.actor_id), SERIES_DAYS, BREAK_DAY, (STEADY, STEADY))
        + [
            TimelineEvent(
                event_id=f"{steady.actor_id}:mkt:{index}",
                subject_id=str(steady.actor_id),
                kind=TimelineEventKind.MARKETPLACE,
                observed_at=_day(index, 9),
                value=VENUE_A,
                evidence_ids=(f"fixture:{steady.actor_id}:mkt:{index}",),
            )
            for index in range(SERIES_DAYS)
        ],
        case_id=None,
        actor_id=steady.actor_id,
        entity_id=None,
        subject_kind="actor",
        kind_for=_channel_for,
    )
    # A persona with three sightings and no persistence runway at all.
    _persist(
        db,
        [
            TimelineEvent(
                event_id=f"{bare.actor_id}:mkt:{index}",
                subject_id=str(bare.actor_id),
                kind=TimelineEventKind.MARKETPLACE,
                observed_at=_day(index, 9),
                value=VENUE_A if index < 2 else VENUE_B,
                evidence_ids=(f"fixture:{bare.actor_id}:mkt:{index}",),
            )
            for index in range(3)
        ],
        case_id=None,
        actor_id=bare.actor_id,
        entity_id=None,
        subject_kind="actor",
        kind_for=_channel_for,
    )
    db.commit()

    fixture.case_id = case.case_id
    fixture.short_case_id = short_case.case_id
    fixture.empty_case_id = empty_case.case_id
    fixture.entity_id = entities[0].entity_id
    fixture.short_entity_id = short_entity.entity_id
    fixture.breaking_actor_id = breaking.actor_id
    fixture.mover_actor_id = mover.actor_id
    fixture.steady_actor_id = steady.actor_id
    fixture.bare_actor_id = bare.actor_id
    fixture.breaking_handle = breaking.handle
    fixture.mover_handle = mover.handle
    fixture.activity_events = entity_events
    try:
        yield fixture
    finally:
        # Own rows only, children first. Nothing this module writes touches the
        # audit trail, so there is no hash-chained entry to leave behind.
        db.execute(
            delete(TemporalObservationRecord).where(
                TemporalObservationRecord.subject_id.in_(
                    [
                        str(entities[0].entity_id),
                        str(entities[1].entity_id),
                        str(short_entity.entity_id),
                        str(breaking.actor_id),
                        str(mover.actor_id),
                        str(steady.actor_id),
                        str(bare.actor_id),
                    ]
                )
            )
        )
        db.execute(
            delete(ActorIdentifierRecord).where(ActorIdentifierRecord.value.like(f"{PREFIX}%"))
        )
        db.execute(
            delete(ActorMarketplaceRecord).where(
                ActorMarketplaceRecord.presence_id.in_(
                    [
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{PREFIX}-presence-{venue}")
                        for venue in (VENUE_A, VENUE_B)
                    ]
                )
            )
        )
        db.execute(delete(EntityRecord).where(EntityRecord.surface_form.like(f"{PREFIX}%")))
        db.execute(
            delete(EvidenceRecord).where(EvidenceRecord.collector_name == "temporal-fixture")
        )
        db.execute(
            delete(ArtifactRecord).where(
                ArtifactRecord.storage_uri.like("synthetic://aegis/temporal/%")
            )
        )
        db.execute(delete(ActorRecord).where(ActorRecord.handle.like(f"{PREFIX}%")))
        db.execute(delete(CaseRecord).where(CaseRecord.name.like(f"{PREFIX}%")))
        db.execute(delete(SourceRecord).where(SourceRecord.name == f"{PREFIX}-source"))
        db.commit()
        db.close()


@pytest.fixture
def client(auth_headers: dict[str, str]) -> Iterator[TestClient]:
    with TestClient(app, headers=auth_headers) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# A real shift, derived by the real detector
# ---------------------------------------------------------------------------


def test_case_shifts_are_the_detectors_own_output(client: TestClient, world: _World) -> None:
    """The reported change is what the library returns on the same stored rows.

    The expected value is recomputed here by importing the same detector the
    endpoint calls. If the router ever grew a private scorer, re-derived its own
    thresholds, or reshaped the score, this assertion fails — which is the only
    way to tell "the platform detected a change" from "the endpoint produced a
    number".
    """
    response = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts")
    assert response.status_code == 200, response.text
    body = response.json()

    expected = detect_activity_shifts(
        world.activity_events,
        bucket=timedelta(days=1),
        method="binary_segmentation",
        min_gain=SERVICE_MIN_GAIN["binary_segmentation"],
        min_size=3,
    )
    assert expected, "the fixture must actually contain a detectable break"

    reported = [
        row
        for row in body["shifts"]
        if row["subject_id"] == str(world.entity_id) and row["channel"] == "activity"
    ]
    assert len(reported) == len(expected)
    for row, change in zip(reported, expected, strict=True):
        assert _at(row["changed_at"]) == change.changed_at
        assert row["sharpness"] == pytest.approx(change.score)
        assert row["detector"] == "binary_segmentation"
        assert row["change_id"] == change.change_id
        # The score the library produced, in the library's own units, with the
        # unit stated on the row rather than left for the reader to guess.
        assert "count²·buckets" in row["sharpness_note"]


def test_the_detected_boundary_is_the_seeded_break(client: TestClient, world: _World) -> None:
    """The change lands on the day the fixture was built to break on.

    Not merely "something was detected": a detector that fired anywhere in a
    forty-bucket series would pass a weaker assertion, and a demonstration whose
    boundary is not the one in the data is not demonstrating the detector.
    """
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts").json()
    rows = [row for row in body["shifts"] if row["subject_id"] == str(world.entity_id)]
    assert len(rows) == 1
    detected = _at(rows[0]["changed_at"])
    seeded = _day(BREAK_DAY, 8)
    assert abs((detected - seeded).total_seconds()) < 86400, (
        f"detected {detected.isoformat()} against a seeded break of {seeded.isoformat()}"
    )
    # And the shape either side is the shape that was seeded.
    assert rows[0]["before"]["mean_count"] < rows[0]["after"]["mean_count"]
    assert rows[0]["before"]["buckets"] == BREAK_DAY


def test_no_shift_is_stored_only_derived(client: TestClient, world: _World) -> None:
    """The boundary exists in no row — it is computed per request.

    Storing a detected change would make the whole feature a lookup: the panel
    would be reading back a number this platform wrote, and the detectors in
    ``aegis.timeline`` would still be unreachable. Every observation row carries
    only an observation, so the change has nowhere to live except in the
    response.
    """
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(TemporalObservationRecord).where(
                TemporalObservationRecord.entity_id == world.entity_id
            )
        ).all()
    finally:
        db.close()
    assert rows
    stored = {key for row in rows for key in (row.metadata_json or {})}
    assert not stored & {"change_id", "sharpness", "regime", "change_point"}
    assert not hasattr(rows[0], "change_id")


def test_the_steady_control_produces_nothing(client: TestClient, world: _World) -> None:
    """A flat series is not reported as changed.

    Without this, a surface that always finds a shift and one that finds the real
    one look identical on a single case.
    """
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts").json()
    controls = _case_subjects(world.case_id) - {str(world.entity_id)}
    assert controls, "fixture must include a control series"
    for subject in controls:
        assert not [row for row in body["shifts"] if row["subject_id"] == subject]


def _case_subjects(case_id: uuid.UUID) -> set[str]:
    db = SessionLocal()
    try:
        return set(
            db.scalars(
                select(TemporalObservationRecord.subject_id)
                .where(TemporalObservationRecord.case_id == case_id)
                .distinct()
            ).all()
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Evidence on both sides of the boundary
# ---------------------------------------------------------------------------


def _citable_ids(subject_id: str) -> set[str]:
    """Every id a stored observation for a subject can legitimately cite.

    An observation with a ledger row cites that row; one without cites itself.
    The point of this helper is that a shift's citations must be a subset of it
    — nothing invented, nothing dropped.
    """
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(TemporalObservationRecord).where(
                TemporalObservationRecord.subject_id == subject_id
            )
        ).all()
    finally:
        db.close()
    ids: set[str] = set()
    for row in rows:
        if row.evidence_id is not None:
            ids.add(str(row.evidence_id))
        ids.add(f"temporal-observation:{row.observation_id}")
    return ids


def test_a_shift_carries_evidence_on_both_sides(client: TestClient, world: _World) -> None:
    """The windows either side of the boundary cite their own observations.

    A change point the library cites is the firing bucket alone; the regime on
    each side is what an analyst has to check the claim against, and it is
    computed from the same stored events rather than asserted.
    """
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts").json()
    row = next(
        item
        for item in body["shifts"]
        if item["subject_id"] == str(world.entity_id) and item["channel"] == "activity"
    )
    before, after = row["before"], row["after"]
    assert before["event_count"] > 0 and after["event_count"] > 0
    assert before["evidence_ids"] and after["evidence_ids"]
    citable = _citable_ids(str(world.entity_id))
    assert set(before["evidence_ids"]) <= citable
    assert set(after["evidence_ids"]) <= citable
    assert set(before["evidence_ids"]).isdisjoint(after["evidence_ids"])
    assert _at(before["to_at"]) < _at(after["from_at"])
    # And the context the chart draws is the same series, not a reconstruction.
    assert any(point["is_boundary"] for point in row["context"])
    assert _at(row["context"][0]["at"]) <= _at(row["changed_at"]) <= _at(row["context"][-1]["at"])


def test_a_categorical_shift_names_both_values(client: TestClient, world: _World) -> None:
    """A state change says what it moved from and to, and cites the runway.

    ``detect_marketplace_transitions`` emits a change only once the new venue has
    persisted, and the row must show which venue that was — a confirmation with
    no named destination is not checkable.
    """
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts").json()
    rows = [item for item in body["shifts"] if item["channel"] == "marketplace"]
    assert len(rows) == 1
    row = rows[0]
    assert row["subject_id"] == str(world.mover_actor_id)
    assert row["from_value"] == VENUE_A
    assert row["to_value"] == VENUE_B
    assert row["detector"] == "state_change"
    # 1.0 records that the persistence rule was satisfied; it is not a
    # probability, and the row says so.
    assert row["sharpness"] == 1.0
    assert "not a probability" in row["sharpness_note"]
    assert len(row["evidence_ids"]) >= 3  # the change plus its confirmations
    assert row["after"]["values"] == [VENUE_B]
    assert row["before"]["values"] == [VENUE_A]


def test_the_handle_rebrand_is_found_on_the_handle_channel(
    client: TestClient, world: _World
) -> None:
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts").json()
    rows = [item for item in body["shifts"] if item["channel"] == "handle"]
    assert len(rows) == 1
    assert rows[0]["from_value"] == world.breaking_handle
    assert rows[0]["to_value"] == f"{world.breaking_handle}_v2"


# ---------------------------------------------------------------------------
# A window too short to analyse is refused, not scored
# ---------------------------------------------------------------------------


def test_a_short_activity_series_is_refused_with_its_counts(
    client: TestClient, world: _World
) -> None:
    """Three buckets produce a refusal, not a KS statistic.

    ``detect_activity_shifts`` returns ``()`` below ``max(2 * min_size, 4)``
    buckets, which on the wire is indistinguishable from "no change found". The
    refusal has to carry both numbers and say the difference between them.
    """
    response = client.get(f"/api/v1/cases/{world.short_case_id}/temporal/shifts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["shifts"] == []
    assert len(body["refusals"]) == 1
    refusal = body["refusals"][0]
    assert refusal["observed"] == 3
    assert refusal["required"] == activity_min_buckets(3) == 6
    assert refusal["unit"] == "buckets"
    assert "no score was computed" in refusal["reason"]
    assert "unanalysed rather than unchanged" in refusal["reason"]
    # And the report says what the empty result means rather than leaving it to
    # read as a clean bill of health.
    assert "absence of data rather than an absence of change" in body["basis"]


def test_a_short_marketplace_stream_is_refused(client: TestClient, world: _World) -> None:
    """Three sightings cannot confirm a move, so none is reported.

    The bare actor is on one venue twice and another once: the library drops a
    change with no confirmation runway, and the refusal has to say so rather than
    report the flap.
    """
    body = client.get(f"/api/v1/actors/{world.bare_actor_id}/temporal/transitions").json()
    assert body["transitions"] == []
    assert len(body["refusals"]) == 1
    refusal = body["refusals"][0]
    assert refusal["observed"] == 3
    assert refusal["required"] == state_min_events(2) == 4
    assert "not been shown not to have changed" in refusal["reason"]
    assert "too short to confirm a move" in body["basis"]


def test_a_case_with_no_history_is_refused_not_answered(client: TestClient, world: _World) -> None:
    """An uncollected case gets a 422 that names the gap.

    An empty list here would read as "no change detected", which is the specific
    misreading this surface exists to prevent.
    """
    response = client.get(f"/api/v1/cases/{world.empty_case_id}/temporal/shifts")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "collection gap rather than a finding" in detail
    assert "not the same as no change having occurred" in detail


def test_segmentation_refuses_a_series_it_cannot_cut(client: TestClient, world: _World) -> None:
    """``segment`` would skip a 3-bucket series; the route says so instead.

    A silent skip reads as "one regime, no change", which asserts a division
    nobody could check.
    """
    body = client.get(f"/api/v1/cases/{world.short_case_id}/temporal/segments").json()
    assert body["series"] == []
    assert len(body["refusals"]) == 1
    refusal = body["refusals"][0]
    assert refusal["observed"] == 3
    assert refusal["required"] == 6
    assert "2 × 3 = 6" in refusal["reason"]
    assert "listed as refusals rather than as a single regime" in body["basis"]


def test_behaviour_declares_the_bandwidth_it_refuses_below(
    client: TestClient, world: _World
) -> None:
    """A short series is still chartable, and says it is not analysable.

    The points are what the analyst has; withholding them would hide the very
    gap the refusal is describing. What must not happen is a score derived from
    them.
    """
    body = client.get(f"/api/v1/actors/{world.bare_actor_id}/temporal/behaviour").json()
    assert body["analysable"] is False
    assert body["refusal"] is not None
    assert body["refusal"]["required"] == 6
    bandwidth = body["bandwidth"]
    assert bandwidth["cusum"]["min_points"] == 6
    assert bandwidth["ks"]["min_points"] == 6
    assert bandwidth["binary_segmentation"]["min_points"] == 6
    assert "not a distribution difference" in bandwidth["ks"]["note"]


# ---------------------------------------------------------------------------
# Segmentation: regimes, not one average
# ---------------------------------------------------------------------------


def test_segmentation_divides_a_series_into_regimes(client: TestClient, world: _World) -> None:
    """The two regimes are the two things the mean would have averaged away.

    Also asserts the regimes tile the series exactly — a segmentation that
    dropped or double-counted buckets would still draw two boxes.
    """
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/segments").json()
    series = next(row for row in body["series"] if row["subject_id"] == str(world.entity_id))
    assert series["buckets"] == SERIES_DAYS
    assert len(series["boundaries"]) == 1
    boundary = series["boundaries"][0]
    assert boundary["index"] == BREAK_DAY
    assert boundary["mean_before"] < boundary["mean_after"]
    assert series["gain_function"] == "mean_shift_gain"

    regimes = series["regimes"]
    assert len(regimes) == 2
    assert sum(row["buckets"] for row in regimes) == SERIES_DAYS
    assert _at(regimes[0]["last_bucket"]) < _at(boundary["at"])
    assert _at(regimes[1]["first_bucket"]) == _at(boundary["at"])
    assert regimes[0]["mean"] < regimes[1]["mean"]

    # The control series is one regime, and says so rather than implying a split.
    controls = [row for row in body["series"] if row["subject_id"] != str(world.entity_id)]
    assert controls
    for control in controls:
        assert control["boundaries"] == []
        assert len(control["regimes"]) == 1
        assert control["regimes"][0]["buckets"] == SERIES_DAYS


def test_segmentation_of_an_unknown_subject_is_404(client: TestClient, world: _World) -> None:
    response = client.get(
        f"/api/v1/cases/{world.case_id}/temporal/segments",
        params={"subject": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    assert "not a subject with no change" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Cross-marketplace transitions
# ---------------------------------------------------------------------------


def test_transitions_match_the_library_and_the_registry_window(
    client: TestClient, world: _World
) -> None:
    """The route is ``detect_marketplace_transitions``, and it disagrees usefully.

    The registry presence windows are returned beside the detection so the two
    can be read against each other — and the fixture's windows deliberately run
    past the detected move, which is exactly the disagreement an analyst needs
    to see rather than have hidden.
    """
    body = client.get(f"/api/v1/actors/{world.mover_actor_id}/temporal/transitions").json()
    assert body["handle"] == world.mover_handle
    assert body["marketplaces"] == [VENUE_A, VENUE_B]
    assert len(body["transitions"]) == 1

    reported = body["transitions"][0]
    assert reported["from_value"] == VENUE_A
    assert reported["to_value"] == VENUE_B

    # The same call, made here over the same stored rows.
    events = [
        TimelineEvent(
            event_id=f"{world.mover_actor_id}:mkt:{index}",
            subject_id=str(world.mover_actor_id),
            kind=TimelineEventKind.MARKETPLACE,
            observed_at=_day(index * 2, 9),
            value=VENUE_B if index * 2 >= BREAK_DAY else VENUE_A,
            evidence_ids=(f"fixture:{world.mover_actor_id}:mkt:{index}",),
        )
        for index in range(SERIES_DAYS // 2)
    ]
    expected = detect_marketplace_transitions(events, min_persist=2)
    assert len(expected) == 1
    # The reported change is the library's, field for field. The citation list
    # is not compared: the endpoint cites what the *stored* row cites, while the
    # hand-built events above cite the fixture's own reference. That is checked
    # separately, against the ids the stored rows actually carry.
    assert _at(reported["changed_at"]) == expected[0].changed_at
    assert reported["from_value"] == expected[0].from_value
    assert reported["to_value"] == expected[0].to_value
    assert reported["sharpness"] == expected[0].score
    assert reported["change_id"] == expected[0].change_id
    # The change plus its confirmation runway, and every id real.
    citable = _citable_ids(str(world.mover_actor_id))
    assert len(reported["evidence_ids"]) >= 3
    assert set(reported["evidence_ids"]) <= citable

    presence = {row["marketplace"]: row for row in body["presence"]}
    assert set(presence) == {VENUE_A, VENUE_B}
    # The windows were built to run past the move; the detection says the persona
    # left on day 20. Both are returned, and neither is corrected to match the
    # other.
    assert _at(presence[VENUE_A]["last_seen"]) > _at(reported["changed_at"])


def test_an_actor_with_no_moves_says_so_rather_than_returning_nothing(
    client: TestClient, world: _World
) -> None:
    body = client.get(f"/api/v1/actors/{world.steady_actor_id}/temporal/transitions").json()
    assert body["transitions"] == []
    assert body["refusals"] == []
    assert "No transition confirmed" in body["basis"]
    assert "persistence rule ran over the whole stream" in body["basis"]


def test_behaviour_series_is_chartable_and_analysable(client: TestClient, world: _World) -> None:
    body = client.get(f"/api/v1/actors/{world.breaking_actor_id}/temporal/behaviour").json()
    assert body["analysable"] is True
    assert body["refusal"] is None
    assert body["buckets"] == SERIES_DAYS
    # Buckets are returned as bucket starts, which is what a chart needs: the
    # API never hands back the raw event times it was given.
    assert _at(body["points"][0]["at"]) == _day(0, 0)
    assert body["mean"] is not None and body["standard_deviation"] is not None
    assert body["peak"] == 12
    # The mean sits between the two regimes because it is an average of both,
    # which is the reading the segmentation endpoint exists to replace.
    assert 3.0 < body["mean"] < 9.0


# ---------------------------------------------------------------------------
# Limitations travel with the finding
# ---------------------------------------------------------------------------


def test_limitations_survive_to_the_response(client: TestClient, world: _World) -> None:
    """Every row carries its detector's own documented limitations.

    Not a summary and not a count: the words, because the library's caveats are
    what separate a detection from an accusation, and an edge that trims them is
    asserting more than the detector did.
    """
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts").json()
    assert body["shifts"]
    for row in body["shifts"]:
        detector = row["detector"]
        expected = [*DETECTOR_LIMITATIONS[detector], *COMMON_LIMITATIONS]
        assert row["limitations"], f"{detector} row carried no limitations"
        # Not a summary and not a count: the library's own words, in order.
        assert row["limitations"] == expected
    assert body["limitations"] == [
        *DETECTOR_LIMITATIONS["binary_segmentation"],
        *COMMON_LIMITATIONS,
    ]


def test_limitations_reach_every_endpoint(client: TestClient, world: _World) -> None:
    """The actor routes carry them too, including on a refusal-only response."""
    for path in (
        f"/api/v1/actors/{world.mover_actor_id}/temporal/transitions",
        f"/api/v1/actors/{world.bare_actor_id}/temporal/transitions",
        f"/api/v1/actors/{world.breaking_actor_id}/temporal/behaviour",
    ):
        body = client.get(path).json()
        assert body["limitations"], path
        assert body["limitations"][-len(COMMON_LIMITATIONS) :] == list(COMMON_LIMITATIONS), path

    segmentation = client.get(f"/api/v1/cases/{world.case_id}/temporal/segments").json()
    assert segmentation["limitations"]
    assert segmentation["series"]
    for series in segmentation["series"]:
        assert series["limitations"], series["subject_id"]


# ---------------------------------------------------------------------------
# Not found, and not authenticated
# ---------------------------------------------------------------------------


def test_unknown_case_is_404(client: TestClient) -> None:
    unknown = uuid.uuid4()
    assert client.get(f"/api/v1/cases/{unknown}/temporal/shifts").status_code == 404
    segments = client.get(f"/api/v1/cases/{unknown}/temporal/segments")
    assert segments.status_code == 404
    assert segments.json()["detail"] == "Case not found"


def test_unknown_actor_is_404(client: TestClient) -> None:
    unknown = uuid.uuid4()
    for suffix in ("transitions", "behaviour"):
        response = client.get(f"/api/v1/actors/{unknown}/temporal/{suffix}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Actor not found"


def test_every_temporal_endpoint_requires_authentication(world: _World) -> None:
    """No route on this surface is reachable without a credential.

    The middleware gates on path, and a path nobody tested would be a path
    nobody noticed was open.
    """
    anonymous = TestClient(app)
    paths = [
        f"/api/v1/cases/{world.case_id}/temporal/shifts",
        f"/api/v1/cases/{world.case_id}/temporal/segments",
        f"/api/v1/actors/{world.mover_actor_id}/temporal/transitions",
        f"/api/v1/actors/{world.mover_actor_id}/temporal/behaviour",
    ]
    for path in paths:
        response = anonymous.get(path)
        assert response.status_code == 401, f"{path} answered {response.status_code}"
        assert response.text == "authentication required"
    # A bad token is no better than none.
    with TestClient(app, headers={"Authorization": "Bearer not-a-real-token"}) as bogus:
        assert bogus.get(paths[0]).status_code == 401


def test_the_activity_series_the_shifts_used_is_reproducible(
    client: TestClient, world: _World
) -> None:
    """The bucketed series the detector read is the one the library builds.

    Pins the two things the response depends on being the *same* series: the
    zero-filled buckets and the boundary index into them.
    """
    series = build_activity_series(world.activity_events, bucket=timedelta(days=1))
    assert len(series) == SERIES_DAYS
    body = client.get(f"/api/v1/cases/{world.case_id}/temporal/shifts").json()
    row = next(
        item
        for item in body["shifts"]
        if item["subject_id"] == str(world.entity_id) and item["channel"] == "activity"
    )
    assert row["after"]["buckets"] == len(series) - BREAK_DAY
    assert row["before"]["mean_count"] == pytest.approx(
        sum(count for _, count in series[:BREAK_DAY]) / BREAK_DAY
    )
    # The supplementary 0-1 figure is the library's own distance, so an activity
    # shift can be compared with another detector's without translating units.
    assert row["distribution_distance"] == pytest.approx(
        __import__("aegis.timeline.algorithms", fromlist=["ks_distance"]).ks_distance(
            [count for _, count in series[:BREAK_DAY]],
            [count for _, count in series[BREAK_DAY:]],
        )
    )
    assert 0.0 <= row["distribution_distance"] <= 1.0


def test_handle_channel_detection_is_the_library_call(world: _World) -> None:
    """The handle fixture is a real detectable change, not a hopeful one.

    Asserted against the detector directly so that a later edit to the fixture
    which quietly stopped being detectable fails here rather than making the
    endpoint test pass by finding nothing.
    """
    events = _state_events(
        f"{world.breaking_actor_id}",
        (world.breaking_handle, f"{world.breaking_handle}_v2"),
        SERIES_DAYS,
        BREAK_DAY,
        1,
    )
    found = detect_handle_changes(events, min_persist=2)
    assert len(found) == 1
    assert found[0].from_value == world.breaking_handle
    assert found[0].to_value == f"{world.breaking_handle}_v2"
    assert found[0].changed_at == _day(BREAK_DAY, 9)


def test_behaviour_peak_and_mean_come_from_the_stored_series(
    client: TestClient, world: _World
) -> None:
    """The chart statistics are the series, not a summary of a summary."""
    events = _activity_events(str(world.breaking_actor_id), SERIES_DAYS, BREAK_DAY, (COLD, HOT))
    counts: dict[str, int] = {}
    for event in events:
        counts[event.observed_at.date().isoformat()] = (
            counts.get(event.observed_at.date().isoformat(), 0) + 1
        )
    body = client.get(f"/api/v1/actors/{world.breaking_actor_id}/temporal/behaviour").json()
    assert [row["events"] for row in body["points"]] == [
        counts[_day(day).date().isoformat()] for day in range(SERIES_DAYS)
    ]
    assert body["peak"] == max(counts.values())
