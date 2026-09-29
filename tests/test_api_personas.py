"""The persona linkage surface, against a real database.

Two claims are worth testing harder than the rest, because they are the ones a
reader of the register would otherwise have to take on trust:

* the score on a proposal is *computed here*, by the platform's own stylometry
  and behaviour functions, and a caller cannot supply one; and
* the observed-error pair in the summary is derived from rows rather than
  asserted by the thing being measured.

Everything else — filters, export shape, the three-way split — is asserted
against the same code paths the API uses, so a test that passes is evidence
about the shipped endpoint rather than about a stand-in.
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
from aegis.api.persona_scoring import (
    MIN_STYLOMETRY_WORDS,
    MethodNotScorable,
    score_sample,
)
from aegis.api.personas import SCORE_THRESHOLD
from aegis.db.audit import AuditService
from aegis.db.models import (
    ActorRecord,
    AuditLogRecord,
    CaseRecord,
    PersonaLinkageRecord,
    RoleRecord,
    UserRecord,
)
from aegis.db.session import SessionLocal
from aegis.stylometry.features import FEATURE_NAMES as STYLOMETRIC_FEATURE_NAMES
from aegis.stylometry.features import StylometricFeatures, stylometric_similarity
from aegis.stylometry.ngrams import tokenize_words
from aegis.stylometry.transforms import apply_transform

pytestmark = pytest.mark.integration

#: Every handle this module creates carries the prefix, so teardown can find its
#: own rows and nothing else.
HANDLE_PREFIX = "test-persona-"

#: One suffix for the whole module. The analyst fixture rows are *not* deleted
#: in teardown — `audit_logs` carries a BEFORE DELETE trigger, so the entries
#: this module writes could not be removed with them, and a dangling
#: `adjudicated_by` would fail the next run's foreign key. A unique suffix per
#: module keeps repeat runs conflict-free, and `seed_demo_data.py --reset`
#: truncates both tables.
RUN_ID = uuid.uuid4().hex[:8]

ACTOR_SAMPLE = (
    "The escrow service accepts bitcoin only and I do not make exceptions for wires. "
    "I have been running this channel since 2019 and the same rules apply to every order "
    "placed through it. Message me directly if you want the current price list; I do not "
    "answer questions in public threads because it wastes everyone's time. Payment is "
    "final the moment the address is released, so please read the terms before you send "
    "anything. I ship to an office address only, never to a PO box, and the vendor list "
    "updates every Monday morning without exception. Ask about the mirror domains in "
    "private if the main one is slow for you. Everything else is in the pinned thread, and "
    "the rules posted there are the same rules you get from me in private."
)

CANDIDATE_SAMPLE = (
    "btc only on this desk. no wires, no exceptions, not for anyone. been running the "
    "same channel since 2019 and the rules have not moved once. ping me direct if you "
    "want the current price list because i will not answer in public threads and it "
    "wastes everyones time. payment is final the second the address drops so read the "
    "terms first. office address only, never a po box. the vendor list refreshes every "
    "monday morning, no exceptions. ask about the mirror domains in private when the "
    "main one is slow. everything else is in the pinned thread, and the rules posted "
    "there are the same rules you get from me in private, not a shortened version of them "
    "and not a summary written afterwards for people who did not read the original."
)

#: The same candidate text after the platform's own adversarial rewrite pipeline.
#: Used where a fixture needs a genuinely *low* score: the number comes from
#: :mod:`aegis.stylometry.transforms` plus the real scorer, so it cannot drift
#: away from what the endpoint would actually produce.
REWRITTEN_SAMPLE = apply_transform(
    apply_transform(
        apply_transform(CANDIDATE_SAMPLE, "punctuation_removal"),
        "case_change",
    ),
    "noise",
)


def _events(prefix: str, hours: list[int]) -> list[dict[str, Any]]:
    """Posting events spanning several days at fixed hours."""
    base = datetime(2026, 3, 1, tzinfo=UTC)
    return [
        {
            "event_id": f"{prefix}:{index}",
            "posted_at": (
                base + timedelta(hours=hours[index % len(hours)], days=index)
            ).isoformat(),
            "platform": ("forum" if index % 3 else "market"),
            "text": "escrow listing dump fees rotation",
        }
        for index in range(12)
    ]


class _Fixture:
    """Identifiers the API needs, created once for the module."""

    def __init__(self) -> None:
        self.actor_id: uuid.UUID
        self.other_actor_id: uuid.UUID
        #: Used only by the summary tests. The summary filters are status,
        #: method, actor, score and date — there is no handle filter — so an
        #: actor of its own is what lets the counts be asserted exactly rather
        #: than as "at least".
        self.summary_actor_id: uuid.UUID
        self.analyst_id: uuid.UUID
        self.case_id: uuid.UUID


@pytest.fixture(scope="module")
def world() -> Iterator[_Fixture]:
    db = SessionLocal()
    fixture = _Fixture()
    role = RoleRecord(
        role_id=uuid.uuid4(),
        name=f"test-persona-role-{RUN_ID}",
        description="Fixture role for tests/test_api_personas.py",
        permissions=["linkage.adjudicate"],
    )
    analyst = UserRecord(
        user_id=uuid.uuid4(),
        email=f"persona-{RUN_ID}@aegis.test",
        display_name="Persona Test Analyst",
        password_hash="not-a-real-hash-fixture",
        role_id=role.role_id,
    )
    actor = ActorRecord(
        actor_id=uuid.uuid4(),
        handle=f"test-persona-actor-{RUN_ID}",
        category="test",
        status="active",
    )
    other = ActorRecord(
        actor_id=uuid.uuid4(),
        handle=f"test-persona-other-{RUN_ID}",
        category="test",
        status="active",
    )
    summary_actor = ActorRecord(
        actor_id=uuid.uuid4(),
        handle=f"test-persona-summary-{RUN_ID}",
        category="test",
        status="active",
    )
    case = CaseRecord(name=f"Persona linkage fixture {RUN_ID}", status="open")
    db.add_all([role, analyst, actor, other, summary_actor, case])
    db.commit()
    fixture.actor_id = actor.actor_id
    fixture.other_actor_id = other.actor_id
    fixture.summary_actor_id = summary_actor.actor_id
    fixture.analyst_id = analyst.user_id
    fixture.case_id = case.case_id
    try:
        yield fixture
    finally:
        # Only the rows this module owns outright are removed. The actor
        # fixtures go; the role, the analyst and the case stay, because the
        # audit entries written above name all three and `audit_logs` carries a
        # BEFORE DELETE trigger, so the rows they point at cannot be removed
        # without the entries that would let anyone audit this run. A unique
        # suffix keeps repeat runs conflict-free and `seed_demo_data.py --reset`
        # truncates all of them.
        db.execute(
            delete(PersonaLinkageRecord).where(
                PersonaLinkageRecord.candidate_handle.like(f"{HANDLE_PREFIX}%")
            )
        )
        db.execute(
            delete(ActorRecord).where(
                ActorRecord.actor_id.in_(
                    [actor.actor_id, other.actor_id, summary_actor.actor_id]
                )
            )
        )
        db.commit()
        db.close()


@pytest.fixture
def client(auth_headers: dict[str, str]) -> Iterator[TestClient]:
    with TestClient(app, headers=auth_headers) as test_client:
        yield test_client


def _proposal(world: _Fixture, handle: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "actor_id": str(world.actor_id),
        "candidate_handle": handle,
        "method": "stylometry",
        "case_id": str(world.case_id),
        "actor_sample": ACTOR_SAMPLE,
        "candidate_sample": CANDIDATE_SAMPLE,
    }
    payload.update(overrides)
    return payload


def _row(handle: str) -> PersonaLinkageRecord:
    db = SessionLocal()
    try:
        row = db.scalar(
            select(PersonaLinkageRecord).where(
                PersonaLinkageRecord.candidate_handle == handle
            )
        )
        assert row is not None, f"no linkage row for {handle}"
        return row
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The score is computed here, and cannot be supplied
# ---------------------------------------------------------------------------


def test_proposal_score_is_computed_server_side(client: TestClient, world: _Fixture) -> None:
    """The stored score is the real function's return value, not a request field.

    The expected number is computed here, in the test, by importing the same
    platform function the endpoint calls. If the endpoint ever stopped using it —
    or grew a private scorer of its own — this assertion fails.
    """
    handle = f"{HANDLE_PREFIX}computed"
    response = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    assert response.status_code == 201, response.text
    body = response.json()

    expected = stylometric_similarity(
        StylometricFeatures.from_text(ACTOR_SAMPLE),
        StylometricFeatures.from_text(CANDIDATE_SAMPLE),
    )
    assert body["score"] == pytest.approx(expected, abs=1e-6)
    assert body["scorer"] == "aegis.stylometry.features.stylometric_similarity"
    # Nothing is a finding until an analyst says so.
    assert body["status"] == "proposed"
    assert body["analyst_recorded"] is False
    assert body["adjudicated_by"] is None


def test_caller_supplied_score_is_rejected_not_ignored(
    client: TestClient, world: _Fixture
) -> None:
    """A body carrying ``score`` is refused, and nothing is written.

    Ignoring it silently would leave a caller believing they had set the score
    the platform will later read as its own output.
    """
    handle = f"{HANDLE_PREFIX}caller-score"
    response = client.post(
        "/api/v1/personas/linkages",
        json=_proposal(world, handle, score=0.99, status="confirmed"),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    # The refusal names the offending fields rather than a generic validation error.
    assert "Extra inputs are not permitted" in str(detail)
    assert "score" in str(detail)

    db = SessionLocal()
    try:
        assert (
            db.scalar(
                select(PersonaLinkageRecord).where(
                    PersonaLinkageRecord.candidate_handle == handle
                )
            )
            is None
        )
    finally:
        db.close()


def test_per_feature_split_decomposes_the_real_score() -> None:
    """The aligned/apart/contested terms average back to the platform's score.

    This is what makes the three-way split a *decomposition* of the score rather
    than a second opinion about it.
    """
    result = score_sample(
        "stylometry", actor_sample=ACTOR_SAMPLE, candidate_sample=CANDIDATE_SAMPLE
    )
    terms = result.metadata["feature_agreement"]
    assert len(terms) == 14
    assert sum(terms.values()) / len(terms) == pytest.approx(result.score, abs=1e-4)
    # Every name is one the stylometry module actually measures.
    assert set(terms) == set(STYLOMETRIC_FEATURE_NAMES)
    # The three lists partition the vocabulary: a feature is never counted twice
    # and never silently dropped.
    assert set(result.aligned) | set(result.apart) | set(result.contested) == set(terms)
    assert not (set(result.aligned) & set(result.apart))
    # Document length is never reported as a shared writing habit.
    assert not set(result.aligned) & {"char_count", "word_count", "sentence_count"}


def test_unmeasurable_feature_is_contested_not_aligned() -> None:
    """A feature that is zero on both sides is absence of evidence.

    The similarity function scores two zeros as perfect agreement; the split
    must not hand that to the aligned list.
    """
    plain = "the quick brown fox jumps over the lazy dog and then it goes back again"
    result = score_sample("stylometry", actor_sample=plain * 12, candidate_sample=plain * 12)
    # `digit_ratio` is 0.0 on both sides of prose with no digits.
    assert result.metadata["feature_agreement"]["digit_ratio"] == 1.0
    assert "digit_ratio" in result.contested
    assert "digit_ratio" not in result.aligned


# ---------------------------------------------------------------------------
# A short sample is refused, never scored
# ---------------------------------------------------------------------------


def test_too_short_sample_is_refused_rather_than_scored(
    client: TestClient, world: _Fixture
) -> None:
    handle = f"{HANDLE_PREFIX}too-short"
    short_sample = "btc only, dm me"
    response = client.post(
        "/api/v1/personas/linkages",
        json=_proposal(world, handle, candidate_sample=short_sample),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    # The refusal says what was supplied and what is needed, and does not
    # offer a number in its place.
    assert f"{len(tokenize_words(short_sample))} words" in detail
    assert str(MIN_STYLOMETRY_WORDS) in detail
    assert "no score was computed" in detail

    db = SessionLocal()
    try:
        assert (
            db.scalar(
                select(PersonaLinkageRecord).where(
                    PersonaLinkageRecord.candidate_handle == handle
                )
            )
            is None
        )
    finally:
        db.close()


def test_unscorable_method_returns_not_supported() -> None:
    """A method no platform function can score is refused, not substituted."""
    with pytest.raises(MethodNotScorable) as caught:
        score_sample("infrastructure", actor_sample=ACTOR_SAMPLE)
    message = str(caught.value)
    assert "cannot score it" in message
    assert "stylometry" in message and "behavioural" in message


def test_behavioural_short_sample_is_refused(client: TestClient, world: _Fixture) -> None:
    handle = f"{HANDLE_PREFIX}few-events"
    response = client.post(
        "/api/v1/personas/linkages",
        json=_proposal(
            world,
            handle,
            method="behavioural",
            actor_sample="",
            candidate_sample="",
            actor_events=_events("actor", [2, 3])[:3],
            candidate_events=_events("cand", [2, 3]),
        ),
    )
    assert response.status_code == 422
    assert "3 events" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------


def test_adjudication_requires_a_rationale(client: TestClient, world: _Fixture) -> None:
    handle = f"{HANDLE_PREFIX}needs-rationale"
    created = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    assert created.status_code == 201
    linkage_id = created.json()["linkage_id"]

    # Schema-level: an empty rationale never reaches the handler.
    empty = client.post(
        f"/api/v1/personas/linkages/{linkage_id}/adjudicate",
        json={"status": "confirmed", "analyst_id": str(world.analyst_id), "rationale": ""},
    )
    assert empty.status_code == 422

    # Whitespace is not a rationale either: the CHECK constraint would accept
    # the row, so the refusal has to come from here.
    blank = client.post(
        f"/api/v1/personas/linkages/{linkage_id}/adjudicate",
        json={"status": "confirmed", "analyst_id": str(world.analyst_id), "rationale": "   "},
    )
    assert blank.status_code == 422
    assert "rationale" in blank.json()["detail"]

    # Still a proposal: a refused decision changes nothing.
    assert _row(handle).status == "proposed"
    assert _row(handle).adjudicated_by is None


def test_adjudication_requires_a_known_analyst(client: TestClient, world: _Fixture) -> None:
    handle = f"{HANDLE_PREFIX}unknown-analyst"
    created = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    linkage_id = created.json()["linkage_id"]
    response = client.post(
        f"/api/v1/personas/linkages/{linkage_id}/adjudicate",
        json={
            "status": "confirmed",
            "analyst_id": str(uuid.uuid4()),
            "rationale": "Confirmed on the shared vendor list.",
        },
    )
    assert response.status_code == 422
    assert "analyst account" in response.json()["detail"]
    assert _row(handle).status == "proposed"


def test_readjudication_replaces_rather_than_accumulates(
    client: TestClient, world: _Fixture
) -> None:
    """A reversal overwrites the ruling; it does not add a second one.

    A row that read as both confirmed and rejected would be a contradictory
    record, and the only history that survives is the audit trail's.
    """
    handle = f"{HANDLE_PREFIX}reversal"
    created = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    linkage_id = created.json()["linkage_id"]
    original_score = created.json()["score"]

    first = client.post(
        f"/api/v1/personas/linkages/{linkage_id}/adjudicate",
        json={
            "status": "confirmed",
            "analyst_id": str(world.analyst_id),
            "rationale": "Confirmed on the shared vendor list and payment address.",
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["linkage"]["status"] == "confirmed"
    assert first_body["previous_status"] == "proposed"
    assert first_body["linkage"]["adjudicated_by_name"] == "Persona Test Analyst"

    second = client.post(
        f"/api/v1/personas/linkages/{linkage_id}/adjudicate",
        json={
            "status": "rejected",
            "analyst_id": str(world.analyst_id),
            "rationale": "Reversed: both handles are the same relisting bot, not one author.",
        },
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["linkage"]["status"] == "rejected"
    assert second_body["previous_status"] == "confirmed"
    assert second_body["previous_rationale"] == first_body["linkage"]["rationale"]

    # One row, one ruling, and the model's number untouched throughout.
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(PersonaLinkageRecord).where(
                PersonaLinkageRecord.candidate_handle == handle
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "rejected"
        assert rows[0].score == pytest.approx(original_score)
        assert rows[0].rationale == second_body["linkage"]["rationale"]
    finally:
        db.close()


def test_decision_is_in_the_audit_trail(client: TestClient, world: _Fixture) -> None:
    """Each ruling appends an entry naming the analyst and what it replaced."""
    handle = f"{HANDLE_PREFIX}audited"
    created = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    linkage_id = created.json()["linkage_id"]

    ruled = client.post(
        f"/api/v1/personas/linkages/{linkage_id}/adjudicate",
        json={
            "status": "confirmed",
            "analyst_id": str(world.analyst_id),
            "rationale": "Confirmed on the shared vendor list and payment address.",
        },
    )
    audit_seq = ruled.json()["audit_seq"]

    db = SessionLocal()
    try:
        entries = db.scalars(
            select(AuditLogRecord)
            .where(AuditLogRecord.entity_id == linkage_id)
            .order_by(AuditLogRecord.seq.asc())
        ).all()
        actions = [entry.action for entry in entries]
        assert "persona.linkage_proposed" in actions
        assert actions.count("persona.linkage_adjudicated") == 1
        entry = next(e for e in entries if e.action == "persona.linkage_adjudicated")
        assert entry.seq == audit_seq
        assert entry.actor_id == world.analyst_id
        assert entry.payload_json["to_status"] == "confirmed"
        assert entry.payload_json["from_status"] == "proposed"
        assert entry.payload_json["analyst"] == "Persona Test Analyst"
        # The model's score at the moment of the decision is on file, so a later
        # reader can see what was being accepted.
        decided_score = ruled.json()["linkage"]["score"]
        assert entry.payload_json["score_at_decision"] == pytest.approx(decided_score)
        assert AuditService(db).verify_chain() is True
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The observed-error pair
# ---------------------------------------------------------------------------


def test_summary_error_pair_is_computed_from_rows(client: TestClient, world: _Fixture) -> None:
    """The honest headline is derived, so it can be checked against the rows.

    The endpoint is filtered to the two handles this test creates, so the counts
    are the test's own and the arithmetic can be verified by hand.
    """
    from aegis.api.personas import _summarize

    def summary_proposal(handle: str, **overrides: Any) -> dict[str, Any]:
        return _proposal(world, handle, actor_id=str(world.summary_actor_id), **overrides)

    handles: list[str] = []
    # Confirmed with a low score: the model's false negative. The candidate
    # sample is put through the platform's own adversarial transform pipeline,
    # so the low score is one the real scorer produced on genuinely rewritten
    # text rather than a fixture hand-tuned to land under the line.
    low = client.post(
        "/api/v1/personas/linkages",
        json=summary_proposal(f"{HANDLE_PREFIX}sum-low", candidate_sample=REWRITTEN_SAMPLE),
    )
    handles.append(f"{HANDLE_PREFIX}sum-low")
    client.post(
        f"/api/v1/personas/linkages/{low.json()['linkage_id']}/adjudicate",
        json={
            "status": "confirmed",
            "analyst_id": str(world.analyst_id),
            "rationale": "Confirmed on the shared vendor list, not on style.",
        },
    )
    # Rejected with a high score: the model's false positive.
    high = client.post(
        "/api/v1/personas/linkages",
        json=summary_proposal(f"{HANDLE_PREFIX}sum-high", candidate_sample=ACTOR_SAMPLE),
    )
    handles.append(f"{HANDLE_PREFIX}sum-high")
    client.post(
        f"/api/v1/personas/linkages/{high.json()['linkage_id']}/adjudicate",
        json={
            "status": "rejected",
            "analyst_id": str(world.analyst_id),
            "rationale": "Rejected: both handles run the same relisting bot.",
        },
    )
    # A third row left unadjudicated, so "proposed" is non-zero too.
    client.post("/api/v1/personas/linkages", json=summary_proposal(f"{HANDLE_PREFIX}sum-open"))
    handles.append(f"{HANDLE_PREFIX}sum-open")

    assert low.json()["score"] < SCORE_THRESHOLD, "the low-score fixture must be low"
    assert high.json()["score"] >= SCORE_THRESHOLD, "the high-score fixture must be high"

    # Scoped to this test's own actor, whose only rows are the three created
    # above, so the counts below are exact rather than "at least".
    filters = {"actor_id": str(world.summary_actor_id), "method": "stylometry", "limit": 1000}
    response = client.get("/api/v1/personas/linkages/summary", params=filters)
    assert response.status_code == 200
    summary = response.json()
    listed = client.get("/api/v1/personas/linkages", params=filters).json()
    assert summary["total"] == len(listed) == 3

    db = SessionLocal()
    try:
        mine = db.scalars(
            select(PersonaLinkageRecord).where(
                PersonaLinkageRecord.candidate_handle.in_(handles)
            )
        ).all()
        expected = _summarize(mine)
        assert {row.candidate_handle for row in mine} == {row["candidate_handle"] for row in listed}
        assert summary["confirmed_low_score"] == sum(
            1 for row in mine if row.status == "confirmed" and row.score < SCORE_THRESHOLD
        )
        assert summary["rejected_high_score"] == sum(
            1 for row in mine if row.status == "rejected" and row.score >= SCORE_THRESHOLD
        )
    finally:
        db.close()

    # The denominators travel with the pair, so no rate is printed against an
    # implied one, and the threshold is returned rather than implied.
    assert summary["confirmed_low_score"] == 1
    assert summary["rejected_high_score"] == 1
    assert summary["confirmed_total"] == summary["confirmed"]
    assert summary["rejected_total"] == summary["rejected"]
    assert summary["score_threshold"] == SCORE_THRESHOLD
    assert summary["proposed"] == expected.proposed == 1
    assert summary["confirmed_total"] == 1
    assert summary["rejected_total"] == 1
    assert summary["adjudicated"] == 2
    assert set(summary["by_status"]) == {"proposed", "confirmed", "rejected"}
    assert summary["by_method"]["stylometry"] == summary["total"]


def test_summary_reports_a_gap_when_nothing_is_adjudicated(
    client: TestClient, world: _Fixture
) -> None:
    """An empty denominator is stated, not reported as a clean error rate."""
    handle = f"{HANDLE_PREFIX}unadjudicated"
    client.post(
        "/api/v1/personas/linkages",
        json=_proposal(world, handle, actor_id=str(world.summary_actor_id)),
    )
    response = client.get(
        "/api/v1/personas/linkages/summary",
        params={"actor_id": str(world.summary_actor_id), "status": "proposed", "limit": 1000},
    )
    summary = response.json()
    assert summary["adjudicated"] == 0
    assert summary["confirmed_low_score"] == 0
    assert summary["rejected_high_score"] == 0
    assert summary["gap"] is not None
    assert "never been overruled" in summary["gap"]


# ---------------------------------------------------------------------------
# Read surface
# ---------------------------------------------------------------------------


def test_list_filters_and_resolves_names(client: TestClient, world: _Fixture) -> None:
    handle = f"{HANDLE_PREFIX}filters"
    created = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    linkage_id = created.json()["linkage_id"]

    listed = client.get(
        "/api/v1/personas/linkages",
        params={"actor_id": str(world.actor_id), "status": "proposed", "limit": 50},
    )
    assert listed.status_code == 200
    rows = [row for row in listed.json() if row["linkage_id"] == linkage_id]
    assert len(rows) == 1
    row = rows[0]
    # The register resolves the actor handle, the case name and the analyst
    # rather than shipping bare UUIDs an analyst has to look up.
    assert row["actor_handle"] == f"test-persona-actor-{RUN_ID}"
    assert row["case_name"] == f"Persona linkage fixture {RUN_ID}"
    assert row["adjudicated_by_name"] is None
    assert row["limitations"], "every row must say what the analysis cannot see"

    scored_out = client.get(
        "/api/v1/personas/linkages", params={"min_score": 1.5, "limit": 5}
    )
    assert scored_out.status_code == 422
    empty = client.get(
        "/api/v1/personas/linkages", params={"actor_id": str(world.other_actor_id)}
    )
    assert empty.status_code == 200


def test_duplicate_pair_is_refused(client: TestClient, world: _Fixture) -> None:
    handle = f"{HANDLE_PREFIX}duplicate"
    first = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    assert first.status_code == 201
    second = client.post("/api/v1/personas/linkages", json=_proposal(world, handle))
    assert second.status_code == 409
    assert handle in second.json()["detail"]


def test_export_carries_the_summary_with_the_rows(client: TestClient, world: _Fixture) -> None:
    handle = f"{HANDLE_PREFIX}export"
    client.post("/api/v1/personas/linkages", json=_proposal(world, handle))

    as_json = client.get(
        "/api/v1/personas/export",
        params={"format": "json", "actor_id": str(world.actor_id), "limit": 100},
    )
    assert as_json.status_code == 200
    payload = as_json.json()
    assert "summary" in payload
    assert "confirmed_low_score" in payload["summary"]
    assert any(row["candidate_handle"] == handle for row in payload["linkages"])

    as_csv = client.get(
        "/api/v1/personas/export",
        params={"format": "csv", "actor_id": str(world.actor_id), "limit": 100},
    )
    assert as_csv.status_code == 200
    lines = [line for line in as_csv.text.splitlines() if line]
    assert lines[0].startswith("linkage_id,actor_handle,candidate_handle,method,score,status")
    assert any(handle in line for line in lines[1:])


def test_unknown_linkage_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/personas/linkages/{uuid.uuid4()}").status_code == 404
