"""Tests for the actor registry API.

These assert the things a type signature cannot: that the filters actually
exclude the right rows, that a populated registry is served in a fixed number of
queries rather than one per actor, that a `NULL` confidence survives the round
trip as `null` rather than collapsing to zero, that a CSV export honours the
filters the analyst is looking at, and that an unknown actor is a 404 rather
than an empty profile.

The N+1 test is the one that matters most here. A registry screen that looks
correct and issues three hundred queries still looks correct, and the failure
only shows up in production with a large registry — so the assertion is not
"few queries" but "the *same* number of queries after the registry doubles".
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from aegis.api.app import app
from aegis.db.models import (
    ActorIdentifierRecord,
    ActorMarketplaceRecord,
    ActorRecord,
    CaseRecord,
    PersonaLinkageRecord,
    SourceRecord,
)
from aegis.db.session import SessionLocal, engine

NOW = datetime.now(UTC)

#: Every fixture row carries this prefix, so the purge is self-healing even if
#: an earlier run died before it could clean up.
PREFIX = "zz-actor-test-"

#: Identifies an actor created by a specific test, so a failing test purges
#: exactly its own rows.
_OWNED = f"{PREFIX}owned-"


def _source(db: Any) -> SourceRecord:
    source = db.scalar(select(SourceRecord).where(SourceRecord.name == f"{PREFIX}source"))
    if source is None:
        source = SourceRecord(
            source_id=uuid4(),
            source_type="marketplace",
            name=f"{PREFIX}source",
            reliability=0.6,
            metadata_json={"synthetic": True},
        )
        db.add(source)
        db.flush()
    return source


def _make_actor(
    db: Any,
    source: SourceRecord,
    *,
    slug: str,
    category: str = "fraud",
    status: str = "active",
    confidence: float | None = 0.9,
    last_scan_age_days: int | None = 1,
    identifiers: int = 2,
    marketplaces: int = 1,
    case_id: UUID | None = None,
) -> ActorRecord:
    handle = f"{_OWNED}{slug}"
    actor = ActorRecord(
        actor_id=uuid4(),
        handle=handle,
        category=category,
        status=status,
        # `confidence=None` is the case under test: "not assessed" must not be
        # stored as, or read back as, zero.
        confidence=confidence,
        first_seen=NOW - timedelta(days=120),
        last_seen=NOW - timedelta(days=2),
        last_scan_at=(
            None if last_scan_age_days is None else NOW - timedelta(days=last_scan_age_days)
        ),
        source_id=source.source_id,
        metadata_json={"synthetic": True},
    )
    db.add(actor)
    db.flush()

    kinds = ("handle", "pgp", "wallet", "onion", "clearnet", "jabber")
    for index in range(identifiers):
        kind = kinds[index % len(kinds)]
        db.add(
            ActorIdentifierRecord(
                identifier_id=uuid4(),
                actor_id=actor.actor_id,
                kind=kind,
                value=f"{handle}-{kind}-{index}",
                confidence=0.7,
                first_seen=NOW - timedelta(days=100),
                last_seen=NOW - timedelta(days=1),
                source_id=source.source_id,
                # Only the first identifier is case-linked, so `case_link_count`
                # is a count of distinct investigations rather than of rows.
                case_id=case_id if index == 0 else None,
                metadata_json={"synthetic": True},
            )
        )
    for index in range(marketplaces):
        db.add(
            ActorMarketplaceRecord(
                presence_id=uuid4(),
                actor_id=actor.actor_id,
                marketplace=f"{handle}-venue-{index}.example",
                role="vendor",
                first_seen=NOW - timedelta(days=90),
                last_seen=NOW - timedelta(days=3),
                listing_count=index + 1,
                source_id=source.source_id,
                metadata_json={"synthetic": True},
            )
        )
    db.flush()
    return actor


def _purge(db: Any) -> None:
    """Remove fixture rows, child-first.

    These fixtures deliberately write no audit rows: `audit_logs` is append-only
    by trigger, so a test row there could never be removed again and the fixture
    would pollute every later run.
    """
    actor_ids = select(ActorRecord.actor_id).where(ActorRecord.handle.like(f"{PREFIX}%"))
    db.execute(
        PersonaLinkageRecord.__table__.delete().where(
            PersonaLinkageRecord.actor_id.in_(actor_ids)
        )
    )
    db.execute(
        ActorIdentifierRecord.__table__.delete().where(
            ActorIdentifierRecord.actor_id.in_(actor_ids)
        )
    )
    db.execute(
        ActorMarketplaceRecord.__table__.delete().where(
            ActorMarketplaceRecord.actor_id.in_(actor_ids)
        )
    )
    db.execute(ActorRecord.__table__.delete().where(ActorRecord.actor_id.in_(actor_ids)))
    db.execute(
        SourceRecord.__table__.delete().where(SourceRecord.name == f"{PREFIX}source")
    )
    db.commit()


def _scoped(client: Any, headers: dict[str, str], **params: Any) -> list[dict[str, Any]]:
    """GET /actors restricted to this file's fixture population.

    The demo dataset is seeded into the same database these tests run against,
    so an unscoped list is 47 actors plus four fixtures. Scoping by the fixture
    handle prefix is what lets the count assertions be exact without asserting
    that the database is empty.
    """
    query = {"q": PREFIX, **params}
    response = client.get("/api/v1/actors", params=query, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def registry(db_available: bool) -> Iterator[dict[str, Any]]:
    """A small, deterministic registry plus the ids a test needs."""
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        _purge(db)
        source = _source(db)
        scored = _make_actor(db, source, slug="scored", category="drugs", confidence=0.82)
        unscored = _make_actor(db, source, slug="unscored", category="drugs", confidence=None)
        other = _make_actor(
            db, source, slug="other", category="arms", status="dormant", confidence=0.31
        )
        stale = _make_actor(
            db,
            source,
            slug="stale",
            category="extortion",
            last_scan_age_days=90,
            identifiers=4,
            marketplaces=3,
        )
        db.commit()
        payload = {
            "source_id": source.source_id,
            "scored": scored.actor_id,
            "unscored": unscored.actor_id,
            "other": other.actor_id,
            "stale": stale.actor_id,
        }
    try:
        yield payload
    finally:
        with SessionLocal() as db:
            _purge(db)


@pytest.fixture(autouse=True)
def _clean_fixture_rows(db_available: bool) -> Iterator[None]:
    """Purge before *and* after, so an aborted run does not poison the next."""
    if db_available:
        with SessionLocal() as db:
            _purge(db)
            _purge(db)
    yield
    if db_available:
        with SessionLocal() as db:
            _purge(db)


# --------------------------------------------------------------------------
# Pure helpers — no database
# --------------------------------------------------------------------------


def test_csv_column_set_is_declared() -> None:
    """The CSV header is a contract with the analyst, so it is importable."""
    from aegis.api.actors import _CSV_FIELDS

    assert "handle" in _CSV_FIELDS
    assert "confidence" in _CSV_FIELDS
    assert "last_scan_at" in _CSV_FIELDS
    assert "source_name" in _CSV_FIELDS
    assert len(set(_CSV_FIELDS)) == len(_CSV_FIELDS)


def test_sort_vocabulary_is_explicit() -> None:
    """A sort key is a whitelist, not a column name from the query string."""
    from aegis.api.actors import SORT_KEYS

    assert SORT_KEYS == (
        "handle",
        "category",
        "confidence",
        "identifiers",
        "last_seen",
        "last_scan",
    )


# --------------------------------------------------------------------------
# Behaviour — requires PostgreSQL
# --------------------------------------------------------------------------


def test_unknown_actor_is_404_everywhere(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    client = TestClient(app)
    unknown = uuid4()
    for path in (
        f"/api/v1/actors/{unknown}",
        f"/api/v1/actors/{unknown}/identifiers",
        f"/api/v1/actors/{unknown}/marketplaces",
    ):
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 404, f"{path} returned {response.status_code}"
        # A 404 body says what was missing; it must not leak a stack trace.
        assert "not found" in response.json()["detail"].lower()


def test_category_and_status_filters(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    client = TestClient(app)
    drugs = _scoped(client, auth_headers, category="drugs")
    assert {row["handle"] for row in drugs} == {f"{_OWNED}scored", f"{_OWNED}unscored"}

    dormant = _scoped(client, auth_headers, status="dormant")
    assert {row["handle"] for row in dormant} == {f"{_OWNED}other"}

    both = _scoped(client, auth_headers, category="drugs", status="active")
    assert {row["handle"] for row in both} == {f"{_OWNED}scored", f"{_OWNED}unscored"}

    # A category nothing carries must return nothing, not everything.
    assert _scoped(client, auth_headers, category="terror financing") == []


def test_min_confidence_excludes_unassessed_actors(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """`null` is not `0`, so a threshold filter drops the unscored rather than
    ranking them last."""
    client = TestClient(app)
    rows = _scoped(client, auth_headers, min_confidence=0.5)
    # `scored` (0.82) and `stale` (0.90) clear the threshold; `other` (0.31)
    # does not, and `unscored` has no score to clear it with.
    assert {row["handle"] for row in rows} == {f"{_OWNED}scored", f"{_OWNED}stale"}
    assert f"{_OWNED}unscored" not in {row["handle"] for row in rows}

    # Lowering the threshold to zero still excludes the unscored actor: a
    # threshold is a statement about *assessed* scores, not about "at least 0".
    zero = _scoped(client, auth_headers, min_confidence=0.0)
    assert f"{_OWNED}unscored" not in {row["handle"] for row in zero}
    assert {row["handle"] for row in zero} == {
        f"{_OWNED}scored",
        f"{_OWNED}stale",
        f"{_OWNED}other",
    }


def test_confidence_null_survives_the_round_trip(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    client = TestClient(app)
    by_handle = {row["handle"]: row for row in _scoped(client, auth_headers)}

    unscored = by_handle[f"{_OWNED}unscored"]
    assert unscored["confidence"] is None, (
        "an unassessed actor must round-trip as null, not as 0.0"
    )

    scored = by_handle[f"{_OWNED}scored"]
    assert scored["confidence"] == pytest.approx(0.82)

    # The profile carries the same value, so a row and the page it opens cannot
    # disagree about whether the actor has been assessed.
    profile = client.get(f"/api/v1/actors/{unscored['actor_id']}", headers=auth_headers).json()
    assert profile["actor"]["confidence"] is None


def test_search_matches_an_identifier_value(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """`q` reaches identifiers, not just handles.

    "Where have I seen this onion address" is the question a registry exists to
    answer, and an actor whose handle differs from every one of its identifiers
    would be unreachable by it otherwise.
    """
    client = TestClient(app)
    identifiers = client.get(
        f"/api/v1/actors/{registry['stale']}/identifiers", headers=auth_headers
    ).json()
    onion = next(row["value"] for row in identifiers if row["kind"] == "onion")

    hits = client.get("/api/v1/actors", params={"q": onion[:24]}, headers=auth_headers).json()
    assert {row["handle"] for row in hits} == {f"{_OWNED}stale"}

    # The actor's own handle is searchable too.
    by_handle = client.get(
        "/api/v1/actors", params={"q": _OWNED}, headers=auth_headers
    ).json()
    assert len(by_handle) == 4


def test_counts_are_populated_and_case_links_are_distinct(
    auth_headers: dict[str, str], db_available: bool, registry: dict[str, Any]
) -> None:
    client = TestClient(app)
    by_handle = {row["handle"]: row for row in _scoped(client, auth_headers)}

    stale = by_handle[f"{_OWNED}stale"]
    assert stale["identifier_count"] == 4
    assert stale["marketplace_count"] == 3
    assert sum(stale["identifier_kinds"].values()) == 4
    assert stale["identifier_kinds"]["pgp"] == 1

    scored = by_handle[f"{_OWNED}scored"]
    assert scored["identifier_count"] == 2
    assert scored["marketplace_count"] == 1
    assert scored["source_name"] == f"{PREFIX}source"

    # Sorting by identifier count must therefore be a real ordering.
    ordered = _scoped(client, auth_headers, sort="identifiers", dir="desc")
    counts = [row["identifier_count"] for row in ordered]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 4


def test_case_links_are_counted_per_investigation(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """One investigation cited twice is one link, not two."""
    client = TestClient(app)
    with SessionLocal() as db:
        case = CaseRecord(
            case_id=uuid4(),
            name=f"{PREFIX}linked case",
            status="open",
            priority="medium",
            severity="medium",
            tags=[],
        )
        db.add(case)
        db.flush()
        source = db.scalar(select(SourceRecord).where(SourceRecord.name == f"{PREFIX}source"))
        assert source is not None
        actor = _make_actor(db, source, slug="linked", case_id=case.case_id, identifiers=3)
        # A second identifier on the same case: still one distinct link.
        db.execute(
            ActorIdentifierRecord.__table__.update()
            .where(ActorIdentifierRecord.actor_id == actor.actor_id)
            .values(case_id=case.case_id)
        )
        db.commit()
        actor_id = actor.actor_id
        case_id = case.case_id

    try:
        linked = next(
            row for row in _scoped(client, auth_headers) if row["actor_id"] == str(actor_id)
        )
        assert linked["case_link_count"] == 1

        profile = client.get(f"/api/v1/actors/{actor_id}", headers=auth_headers).json()
        assert [link["case_id"] for link in profile["linked_cases"]] == [str(case_id)]
        assert profile["linked_cases"][0]["identifier_count"] == 3
    finally:
        with SessionLocal() as db:
            # Actors first: their identifiers carry the case foreign key, and
            # deleting the case while they still reference it is refused.
            _purge(db)
            db.execute(CaseRecord.__table__.delete().where(CaseRecord.case_id == case_id))
            db.commit()


def test_registry_list_does_not_n_plus_one(
    auth_headers: dict[str, str], db_available: bool, registry: dict[str, Any]
) -> None:
    """Doubling the registry must not add a single query.

    The naive implementation issues one identifier query and one marketplace
    query per row, so the statement count scales with the page. Asserting a
    fixed count against a known population would pass for the wrong reasons
    (a small registry hides the problem), so the assertion is comparative: the
    same number of statements before and after the actors are added.
    """
    client = TestClient(app)

    def count_statements(path: str) -> int:
        statements: list[str] = []

        def on_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", on_execute)
        try:
            response = client.get(path, headers=auth_headers)
            assert response.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", on_execute)
        return len(statements)

    before = count_statements("/api/v1/actors")
    assert before > 0

    with SessionLocal() as db:
        source = db.scalar(select(SourceRecord).where(SourceRecord.name == f"{PREFIX}source"))
        assert source is not None
        # Eight extra actors, each with the same identifiers and marketplaces
        # the original four have. If any of it were per-row, this would add
        # roughly sixteen more statements.
        for index in range(8):
            _make_actor(
                db,
                source,
                slug=f"bulk-{index}",
                identifiers=2,
                marketplaces=1,
            )
        db.commit()

    try:
        after = count_statements("/api/v1/actors")
        assert after == before, (
            f"registry list issued {after} statements for 12 actors and "
            f"{before} for 4 — that is an N+1, not a fixed query plan"
        )
    finally:
        with SessionLocal() as db:
            _purge(db)


def test_populated_registry_returns_real_counts(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """A populated registry must return per-row counts, not zeros.

    Paired with the comparative N+1 test above: this says the aggregate is
    there, that one says it is not computed per row.
    """
    client = TestClient(app)
    rows = _scoped(client, auth_headers)
    assert len(rows) == 4
    assert any(row["identifier_count"] > 0 for row in rows)
    assert any(row["marketplace_count"] > 0 for row in rows)
    assert any(row["identifier_kinds"] for row in rows)
    # Every row carries the columns the problem statement names.
    for row in rows:
        assert {"handle", "category", "status", "confidence", "identifier_count",
                "marketplace_count", "last_scan_at", "source_name", "last_seen"} <= set(row)


def test_csv_export_respects_the_active_filters(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """The export must be the table the analyst was looking at."""
    client = TestClient(app)
    response = client.get(
        "/api/v1/actors/export",
        params={"format": "csv", "category": "drugs", "q": PREFIX},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    parsed = list(csv.DictReader(io.StringIO(response.text)))
    assert {row["handle"] for row in parsed} == {f"{_OWNED}scored", f"{_OWNED}unscored"}

    # The unassessed actor writes an empty cell — not `0`, not `null`, both of
    # which would read as a score.
    blank = next(row for row in parsed if row["handle"] == f"{_OWNED}unscored")
    assert blank["confidence"] == ""
    scored = next(row for row in parsed if row["handle"] == f"{_OWNED}scored")
    assert float(scored["confidence"]) == pytest.approx(0.82)
    # Counts and the source travel with the row, so the file stands alone.
    assert int(scored["identifier_count"]) == 2
    assert scored["source_name"] == f"{PREFIX}source"

    # A second filter narrows the file again, rather than the first one having
    # been applied and the rest ignored.
    narrowed = client.get(
        "/api/v1/actors/export",
        params={
            "format": "csv",
            "category": "drugs",
            "status": "active",
            "min_confidence": 0.5,
            "q": PREFIX,
        },
        headers=auth_headers,
    )
    assert {row["handle"] for row in csv.DictReader(io.StringIO(narrowed.text))} == {
        f"{_OWNED}scored"
    }

    # And a filter matching nothing exports a header and no rows, rather than
    # silently exporting the whole registry.
    empty = client.get(
        "/api/v1/actors/export",
        params={"format": "csv", "category": "terror financing", "q": PREFIX},
        headers=auth_headers,
    )
    assert empty.text.strip().splitlines() == [
        "actor_id,handle,category,status,confidence,identifier_count,marketplace_count,"
        "case_link_count,identifier_kinds,first_seen,last_seen,last_scan_at,source_name,notes"
    ]


def test_json_and_stix_exports_state_their_denominator(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """A truncated export says so rather than presenting itself as complete."""
    client = TestClient(app)
    payload = client.get(
        "/api/v1/actors/export",
        params={"format": "json", "category": "drugs", "limit": 1, "q": PREFIX},
        headers=auth_headers,
    ).json()
    assert payload["total"] == 2
    assert payload["returned"] == 1
    assert payload["filters"]["category"] == "drugs"
    assert payload["actors"][0]["confidence"] is None or isinstance(
        payload["actors"][0]["confidence"], float
    )

    bundle = client.get(
        "/api/v1/actors/export", params={"format": "stix", "q": PREFIX}, headers=auth_headers
    ).json()
    assert bundle["type"] == "bundle"
    assert bundle["x_aegis_matched"] == bundle["x_aegis_returned"] == 4
    assert len(bundle["objects"]) == 4
    assert all(obj["type"] == "threat-actor" for obj in bundle["objects"])
    # No identity object is asserted: a registry row is a hypothesis about who
    # someone is, not a finding that they are.
    assert not any(obj["type"] == "identity" for obj in bundle["objects"])


def test_summary_counts_categories_and_stale_actors(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """The filter control's vocabulary, and the backlog it exists to surface."""
    client = TestClient(app)
    summary = client.get("/api/v1/actors/summary", headers=auth_headers).json()

    # The summary is registry-wide, so it is asserted for internal consistency
    # and for the fixtures' own contribution rather than against exact totals:
    # the seeded demo registry shares this database.
    assert summary["total"] >= 4
    assert sum(row["count"] for row in summary["by_status"]) == summary["total"]
    assert sum(row["count"] for row in summary["by_category"]) == summary["total"]

    by_category = {row["category"]: row["count"] for row in summary["by_category"]}
    assert by_category["drugs"] >= 2
    assert by_category["arms"] >= 1
    assert by_category["extortion"] >= 1

    # One fixture actor carries no score at all.
    assert summary["unassessed"] >= 1
    assert summary["identifiers"] >= 11
    assert summary["marketplaces"] >= 6
    assert {row["kind"] for row in summary["identifier_kinds"]} >= {"handle", "pgp", "onion"}

    # A fixture actor was last scanned 90 days ago, so it is in the stale set at
    # the default 30-day threshold.
    assert summary["stale_days"] == 30
    assert summary["stale"] >= 1
    assert summary["stale"] <= summary["total"]

    # `stale_days` is the threshold, not the lookback: "no scan in N days". A
    # larger N is a laxer definition, so the population can only shrink.
    wide = client.get(
        "/api/v1/actors/summary", params={"stale_days": 365}, headers=auth_headers
    ).json()
    assert wide["stale_days"] == 365
    assert wide["stale"] <= summary["stale"]


def test_never_scanned_actors_count_as_stale(
    auth_headers: dict[str, str], db_available: bool, registry: dict[str, Any]
) -> None:
    """`last_scan_at IS NULL` is the back of the backlog, not an exemption."""
    client = TestClient(app)
    # Deltas, not absolutes: the summary is registry-wide and the demo registry
    # is in the same database. What is under test is that one more unscanned
    # actor makes the backlog exactly one larger.
    before = client.get("/api/v1/actors/summary", headers=auth_headers).json()

    with SessionLocal() as db:
        source = db.scalar(select(SourceRecord).where(SourceRecord.name == f"{PREFIX}source"))
        assert source is not None
        _make_actor(db, source, slug="never-scanned", last_scan_age_days=None)
        db.commit()

    try:
        after = client.get("/api/v1/actors/summary", headers=auth_headers).json()
        assert after["total"] == before["total"] + 1
        assert after["stale"] == before["stale"] + 1

        row = next(
            row
            for row in _scoped(client, auth_headers)
            if row["handle"] == f"{_OWNED}never-scanned"
        )
        assert row["last_scan_at"] is None
    finally:
        with SessionLocal() as db:
            _purge(db)


def test_categories_endpoint_matches_the_summary(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """Two endpoints, one vocabulary — a filter that can select nothing is a lie."""
    client = TestClient(app)
    categories = client.get("/api/v1/actors/categories", headers=auth_headers).json()
    summary = client.get("/api/v1/actors/summary", headers=auth_headers).json()
    assert {row["category"]: row["count"] for row in categories} == {
        row["category"]: row["count"] for row in summary["by_category"]
    }
    assert sum(row["count"] for row in categories) == summary["total"]


def test_profile_resolves_identifiers_marketplaces_and_empty_linkages(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    client = TestClient(app)
    profile = client.get(f"/api/v1/actors/{registry['stale']}", headers=auth_headers).json()

    assert profile["actor"]["handle"] == f"{_OWNED}stale"
    assert sum(len(rows) for rows in profile["identifiers_by_kind"].values()) == 4
    assert set(profile["identifiers_by_kind"]) == {"handle", "pgp", "wallet", "onion"}
    assert len(profile["marketplaces"]) == 3
    # The fixture links no personas: an empty list must mean "no rows", which is
    # what the API returns rather than an error or an invented linkage.
    assert profile["persona_linkages"] == []

    venues = client.get(
        f"/api/v1/actors/{registry['stale']}/marketplaces", headers=auth_headers
    ).json()
    assert len(venues) == 3
    assert all(row["first_seen"] is not None and row["last_seen"] is not None for row in venues)

    identifiers = client.get(
        f"/api/v1/actors/{registry['stale']}/identifiers", headers=auth_headers
    ).json()
    assert len(identifiers) == 4


def test_persona_linkages_are_returned_when_present(
    auth_headers: dict[str, str], db_available: bool, registry: dict[str, Any]
) -> None:
    """The linkage section is real data or an empty list — never a stub."""
    client = TestClient(app)
    with SessionLocal() as db:
        db.add(
            PersonaLinkageRecord(
                linkage_id=uuid4(),
                actor_id=registry["other"],
                candidate_handle=f"{PREFIX}candidate",
                method="stylometry",
                score=0.77,
                status="proposed",
                aligned_features=["posting_cadence"],
                apart_features=["topic shift"],
                contested_features=[],
                limitations=["synthetic"],
                case_id=None,
                metadata_json={"synthetic": True},
            )
        )
        db.commit()

    try:
        profile = client.get(f"/api/v1/actors/{registry['other']}", headers=auth_headers).json()
        assert len(profile["persona_linkages"]) == 1
        linkage = profile["persona_linkages"][0]
        assert linkage["candidate_handle"] == f"{PREFIX}candidate"
        assert linkage["aligned_features"] == ["posting_cadence"]
        assert linkage["apart_features"] == ["topic shift"]
        assert linkage["status"] == "proposed"
        assert linkage["adjudicated_by"] is None
    finally:
        with SessionLocal() as db:
            _purge(db)


def test_no_credential_field_is_ever_returned(
    auth_headers: dict[str, str], registry: dict[str, Any]
) -> None:
    """`password_hash` must not be reachable from any route on this router."""
    client = TestClient(app)
    actor_id = registry["scored"]
    bodies = [
        client.get("/api/v1/actors", headers=auth_headers).text,
        client.get("/api/v1/actors/summary", headers=auth_headers).text,
        client.get("/api/v1/actors/categories", headers=auth_headers).text,
        client.get(f"/api/v1/actors/{actor_id}", headers=auth_headers).text,
        client.get(f"/api/v1/actors/{actor_id}/identifiers", headers=auth_headers).text,
        client.get(f"/api/v1/actors/{actor_id}/marketplaces", headers=auth_headers).text,
        client.get("/api/v1/actors/export", params={"format": "json"}, headers=auth_headers).text,
    ]
    for body in bodies:
        assert "password" not in body.lower()
        assert "totp_secret" not in body.lower()


def test_actor_routes_require_authentication(registry: dict[str, Any]) -> None:
    client = TestClient(app)
    assert client.get("/api/v1/actors").status_code == 401
    assert client.get(f"/api/v1/actors/{registry['scored']}").status_code == 401