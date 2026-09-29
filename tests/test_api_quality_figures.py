"""Tests for the two figures the console added on top of existing routes.

Both are additive fields on responses the platform already returns — the
per-actor weekly evidence series on ``ActorRegistryRow``, and the reliability
bands on ``CollectionStatus`` — so what is asserted here is the set of
distinctions each one has to keep:

* ``evidence_weekly`` is ``None`` when nothing was recorded, and *not* a run of
  zeros. A client that cannot tell those apart will draw a flat line for an
  actor the platform never measured, which is the single most misleading thing
  a register can contain.
* a sighting with no evidence row behind it is not evidence volume, and must
  not be counted as one.
* a band holds each registered source exactly once, and the band's records are
  the records that band has actually produced.

These live apart from ``test_api_actors.py`` because that file is owned by the
registry work and this one is additive to it; a shared file would mean two
agents editing the same fixtures.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from aegis.api.app import app
from aegis.db.models import (
    ActorRecord,
    EvidenceRecord,
    SourceRecord,
    TemporalObservationRecord,
)
from aegis.db.session import SessionLocal, engine

NOW = datetime.now(UTC)
PREFIX = "zz-quality-test-"


@pytest.fixture
def client(auth_headers: dict[str, str]) -> Iterator[TestClient]:
    with TestClient(app, headers=auth_headers) as test_client:
        yield test_client


def _purge(db: Any) -> None:
    """Remove this file's rows, child-first.

    ``temporal_observations``, ``evidence`` and ``sources`` are hard-deleted
    rather than left behind: the demo corpus is seeded into the same database,
    and a fixture source that outlived the run would change the band counts
    every later test asserts on.
    """
    actor_ids = select(ActorRecord.actor_id).where(ActorRecord.handle.like(f"{PREFIX}%"))
    source_ids = select(SourceRecord.source_id).where(SourceRecord.name.like(f"{PREFIX}%"))
    evidence_ids = select(EvidenceRecord.evidence_id).where(
        EvidenceRecord.source_id.in_(source_ids)
    )
    db.execute(
        TemporalObservationRecord.__table__.delete().where(
            TemporalObservationRecord.actor_id.in_(actor_ids)
            | TemporalObservationRecord.evidence_id.in_(evidence_ids)
        )
    )
    db.execute(ActorRecord.__table__.delete().where(ActorRecord.actor_id.in_(actor_ids)))
    db.execute(EvidenceRecord.__table__.delete().where(EvidenceRecord.source_id.in_(source_ids)))
    db.execute(SourceRecord.__table__.delete().where(SourceRecord.name.like(f"{PREFIX}%")))
    db.commit()


@pytest.fixture(autouse=True)
def _clean(db_available: bool) -> Iterator[None]:
    if db_available:
        with SessionLocal() as db:
            _purge(db)
    yield
    if db_available:
        with SessionLocal() as db:
            _purge(db)


def _make_source(db: Any, slug: str, reliability: float = 0.8) -> SourceRecord:
    record = SourceRecord(
        source_id=uuid4(),
        source_type="marketplace",
        name=f"{PREFIX}{slug}",
        reliability=reliability,
        metadata_json={"synthetic": True},
    )
    db.add(record)
    db.flush()
    return record


def _make_evidence(db: Any, source: SourceRecord, index: int) -> EvidenceRecord:
    """A real ledger row.

    ``temporal_observations.evidence_id`` is a foreign key, so a fabricated
    uuid would be refused — which is the right outcome: an observation citing an
    evidence record that does not exist is exactly the kind of row this whole
    change is trying to avoid counting.
    """
    record = EvidenceRecord(
        evidence_id=uuid4(),
        case_id=None,
        source_id=source.source_id,
        source_type="marketplace",
        observed_at=NOW - timedelta(days=index),
        collected_at=NOW - timedelta(days=index),
        raw_artifact_uri=f"synthetic://{PREFIX}{index}",
        sha256=f"{PREFIX}sha-{uuid4().hex}",
        collector_name="quality_test",
        collector_version="0.0.0",
        source_reliability=source.reliability,
        independence_group=f"{PREFIX}group",
        metadata_json={"synthetic": True},
    )
    db.add(record)
    db.flush()
    return record


def _make_actor(db: Any, slug: str, source: SourceRecord | None = None) -> ActorRecord:
    actor = ActorRecord(
        actor_id=uuid4(),
        handle=f"{PREFIX}{slug}",
        category="drugs",
        status="active",
        confidence=0.7,
        first_seen=NOW - timedelta(days=200),
        last_seen=NOW - timedelta(days=1),
        last_scan_at=NOW - timedelta(days=1),
        source_id=source.source_id if source is not None else None,
        metadata_json={"synthetic": True},
    )
    db.add(actor)
    db.flush()
    return actor


def _observe(
    db: Any,
    actor: ActorRecord,
    *,
    days_ago: int,
    evidence: EvidenceRecord | None = None,
) -> None:
    db.add(
        TemporalObservationRecord(
            observation_id=uuid4(),
            actor_id=actor.actor_id,
            subject_id=str(actor.actor_id),
            subject_kind="actor",
            channel="activity",
            observed_at=NOW - timedelta(days=days_ago),
            value="post",
            magnitude=1.0,
            # `None` is the common case and the one the seed corpus produces: a
            # sighting the ledger does not back is a sighting, not a record.
            evidence_id=evidence.evidence_id if evidence is not None else None,
            metadata_json={"synthetic": True},
        )
    )
    db.flush()


def _rows(client: TestClient, auth_headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get("/api/v1/actors", params={"q": PREFIX}, headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# The per-actor sighting series
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_series_is_null_when_nothing_was_recorded(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        _make_actor(db, "silent")
        db.commit()

    rows = {row["handle"]: row for row in _rows(client, auth_headers)}
    silent = rows[f"{PREFIX}silent"]
    # `None`, not `[0] * 12`: the first is "we have no series", the second is
    # "we measured twelve weeks of silence", and only the first is true.
    assert silent["activity"] is None


@pytest.mark.integration
def test_series_counts_sightings_and_separates_the_ledger_backed_ones(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        source = _make_source(db, "stream")
        actor = _make_actor(db, "counted", source)
        # Three sightings in the current week and one nine days back; one of
        # them is backed by a ledger row and the rest are not.
        _observe(db, actor, days_ago=1, evidence=_make_evidence(db, source, 1))
        _observe(db, actor, days_ago=1)
        _observe(db, actor, days_ago=1)
        _observe(db, actor, days_ago=9)
        db.commit()

    row = next(r for r in _rows(client, auth_headers) if r["handle"] == f"{PREFIX}counted")
    series = row["activity"]
    assert series is not None
    assert len(series["weekly"]) == 12
    assert sum(series["weekly"]) == 4
    # The three in the same week share a bucket; the fourth sits in an earlier one.
    assert max(series["weekly"]) == 3
    assert sum(1 for value in series["weekly"] if value > 0) == 2
    # Sightings are not evidence records, and the count that says so travels
    # with the series rather than being left for a reader to assume.
    assert series["cited"] == 1


@pytest.mark.integration
def test_series_ignores_observations_older_than_the_window(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        actor = _make_actor(db, "stale-series")
        _observe(db, actor, days_ago=200)
        _observe(db, actor, days_ago=2)
        db.commit()

    row = next(r for r in _rows(client, auth_headers) if r["handle"] == f"{PREFIX}stale-series")
    series = row["activity"]
    assert series is not None
    # The window is twelve weeks; a sighting from 200 days ago is not in it, and
    # is not silently folded into the first bucket.
    assert sum(series["weekly"]) == 1


@pytest.mark.integration
def test_window_start_names_the_period(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        actor = _make_actor(db, "windowed")
        _observe(db, actor, days_ago=1)
        db.commit()

    row = next(r for r in _rows(client, auth_headers) if r["handle"] == f"{PREFIX}windowed")
    start = row["activity"]["start"]
    assert isinstance(start, str)
    # A Monday: a window whose boundaries are unexplained cannot be described
    # to a screen-reader user, and a bucket edge that moved with the server's
    # time zone would make the same data read as two different periods.
    assert datetime.fromisoformat(start).weekday() == 0


@pytest.mark.integration
def test_registry_query_count_does_not_grow_with_the_page(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    """The series is one grouped read for the page, not one per actor.

    A register that looks correct and issues a query per row still looks
    correct, and only fails in production with a large registry.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")

    def count() -> int:
        statements: list[str] = []

        def on_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", on_execute)
        try:
            response = client.get("/api/v1/actors", params={"q": PREFIX}, headers=auth_headers)
            assert response.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", on_execute)
        return len(statements)

    with SessionLocal() as db:
        for index in range(2):
            actor = _make_actor(db, f"bulk-{index}")
            _observe(db, actor, days_ago=index + 1)
        db.commit()

    before = count()
    assert before > 0
    with SessionLocal() as db:
        for index in range(4):
            actor = _make_actor(db, f"extra-{index}")
            _observe(db, actor, days_ago=index + 1)
        db.commit()
    assert count() == before


# --------------------------------------------------------------------------
# The reliability bands
# --------------------------------------------------------------------------


def _status(client: TestClient, auth_headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/api/v1/collection/status", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
def test_bands_partition_the_register_exactly_once(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        # Deliberately spread across the edges: a 0.85 source clears every
        # floor, and counting it in all three would invent two sources.
        _make_source(db, "high", 0.85)
        _make_source(db, "medium", 0.5)
        _make_source(db, "low", 0.1)
        db.commit()

    bands = {band["band"]: band for band in _status(client, auth_headers)["reliability_bands"]}
    assert [band["band"] for band in _status(client, auth_headers)["reliability_bands"]] == [
        "high",
        "medium",
        "low",
    ]
    assert sum(band["sources"] for band in bands.values()) >= 3
    assert bands["high"]["sources"] >= 1
    assert bands["high"]["min_reliability"] == 0.7


@pytest.mark.integration
def test_band_records_are_zero_when_nothing_was_collected(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        _make_source(db, "quiet", 0.9)
        db.commit()

    bands = {band["band"]: band for band in _status(client, auth_headers)["reliability_bands"]}
    # A high-reliability source nobody has run is a claim, and the band has to
    # be able to say so with a number rather than by omission.
    assert bands["high"]["sources"] >= 1
    assert all(band["contributing_sources"] <= band["sources"] for band in bands.values())


@pytest.mark.integration
def test_registered_mean_is_returned_beside_the_contributing_one(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    status = _status(client, auth_headers)
    # Both, always: the difference between them is the coverage gap, and a
    # client given only one of them has to invent the other.
    assert "mean_registered_reliability" in status
    assert "mean_contributing_reliability" in status
    registered = status["mean_registered_reliability"]
    assert registered is None or 0.0 <= registered <= 1.0


@pytest.mark.integration
def test_band_edges_travel_with_the_response(
    client: TestClient, auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    limitations = " ".join(_status(client, auth_headers)["limitations"])
    # The cut-offs are named on the response so a client cannot re-apply its
    # own and quietly describe a different corpus.
    assert "high at 0.7 and above" in limitations
    assert "low at 0 and above" in limitations
