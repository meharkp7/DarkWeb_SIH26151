"""Tests for the Command Center and Administration analytics.

These assert behaviour that a type signature cannot: that the queue score is
*explainable*, that the velocity window includes the current month, that the
SLA indicator fires before the deadline rather than after it, and that the
audit endpoint derives its integrity verdict instead of asserting it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aegis.api.app import app
from aegis.api.dashboard_analytics import _band, _sla_state
from aegis.db.audit import AuditService
from aegis.db.models import (
    AssessmentRecord,
    AuditLogRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    HypothesisLinkRecord,
    HypothesisRecord,
    RelationshipRecord,
    SourceRecord,
)
from aegis.db.session import SessionLocal

NOW = datetime.now(UTC)


def _case(**overrides: object) -> CaseRecord:
    defaults: dict[str, object] = {
        "case_id": uuid4(),
        "name": "Test investigation",
        "description": "synthetic",
        "status": "active",
        "priority": "medium",
        "severity": "medium",
        "tags": [],
    }
    defaults.update(overrides)
    return CaseRecord(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.9, "HIGH"), (0.72, "HIGH"), (0.71, "MEDIUM"), (0.48, "MEDIUM"), (0.47, "LOW")],
)
def test_band_boundaries(value: float, expected: str) -> None:
    assert _band(value) == expected


@pytest.mark.parametrize(
    ("sla", "status", "offset_hours", "expected"),
    [
        (timedelta(hours=-1), "active", 0.0, "breached"),
        (timedelta(hours=4), "active", 0.0, "at_risk"),
        (timedelta(days=5), "active", 0.0, "ok"),
        (None, "active", 0.0, "none"),
        # A closed case is never "at risk" no matter what its deadline says.
        (timedelta(hours=2), "closed", 0.0, "none"),
    ],
)
def test_sla_state_classification(
    sla: timedelta | None, status: str, offset_hours: float, expected: str
) -> None:
    case = _case(status=status, sla_due_at=None if sla is None else NOW + sla)
    assert _sla_state(case, overdue=sla is not None and sla < timedelta(0), now=NOW) == expected


# --------------------------------------------------------------------------
# Integration behaviour (requires PostgreSQL)
# --------------------------------------------------------------------------


def _seed(db, **overrides: object) -> CaseRecord:
    source = SourceRecord(
        source_id=uuid4(),
        source_type="forum",
        name="Test source",
        reliability=0.8,
        metadata_json={"independence_group": "test-group"},
    )
    db.add(source)
    case = _case(**overrides)
    db.add(case)
    db.flush()

    evidence_id = uuid4()
    db.add(
        EvidenceRecord(
            evidence_id=evidence_id,
            case_id=case.case_id,
            source_id=source.source_id,
            source_type="forum",
            observed_at=NOW - timedelta(days=2),
            collected_at=NOW - timedelta(hours=1),
            entity_type="domain",
            entity_value_hash="a" * 64,
            context_hash="b" * 64,
            raw_artifact_uri="synthetic://test",
            artifact_id=None,
            sha256="c" * 64,
            collector_name="test",
            collector_version="1",
            source_reliability=0.8,
            independence_group="test-group",
            metadata_json={"title": "Test observation"},
        )
    )
    # Flushed before the entities: ``entities.evidence_id`` is NOT NULL and is
    # a real foreign key, so the ledger has to exist on disk first. This is the
    # same ordering rule the demo seeder is built around.
    db.flush()

    entity = EntityRecord(
        entity_id=uuid4(),
        case_id=case.case_id,
        evidence_id=evidence_id,
        entity_type="domain",
        surface_form="example.test",
        normalized_form="example.test",
        confidence=0.9,
    )
    other = EntityRecord(
        entity_id=uuid4(),
        case_id=case.case_id,
        evidence_id=evidence_id,
        entity_type="actor",
        surface_form="Operator Test",
        normalized_form="operator-test",
        confidence=0.8,
    )
    db.add_all([entity, other])
    db.flush()

    db.add(
        RelationshipRecord(
            relationship_id=uuid4(),
            case_id=case.case_id,
            subject_entity_id=entity.entity_id,
            object_entity_id=other.entity_id,
            relationship_type="controls",
            first_seen=NOW - timedelta(days=10),
            last_seen=NOW - timedelta(hours=1),
            valid_from=NOW - timedelta(days=10),
            valid_until=NOW - timedelta(hours=1),
            confidence=0.8,
            evidence_ids=[evidence_id],
            metadata_json={},
        )
    )

    hypothesis = HypothesisRecord(
        hypothesis_id=uuid4(),
        case_id=case.case_id,
        subject_entity_id=entity.entity_id,
        object_entity_id=other.entity_id,
        kind="attribution",
        status="candidate",
        missing_evidence=[],
        analyst_disposition="synthetic test",
        metadata_json={},
    )
    db.add(hypothesis)
    db.flush()
    db.add(
        HypothesisLinkRecord(
            link_id=uuid4(),
            hypothesis_id=hypothesis.hypothesis_id,
            evidence_id=evidence_id,
            role="supporting",
            modality="infrastructure",
            independence_group="test-group",
            weight=0.8,
        )
    )
    db.add(
        AssessmentRecord(
            assessment_id=uuid4(),
            hypothesis_id=hypothesis.hypothesis_id,
            case_id=case.case_id,
            model_id="test-model",
            model_version="1.0",
            raw_score=0.7,
            calibrated_confidence=0.64,
            calibration_version="test",
            signals_json={"infrastructure": 0.8, "behavioral": 0.5},
            supporting_evidence_ids=[evidence_id],
            contradictory_evidence_ids=[],
            explanations=["synthetic"],
            limitations=["synthetic"],
        )
    )
    db.flush()
    # No audit entry is written for the fixture. `audit_logs` is append-only by
    # database trigger and its `case_id` foreign key has no ON DELETE CASCADE,
    # so a test row there could never be removed again — the fixture would
    # permanently pollute the dataset every run touches. The audit surfaces
    # are exercised against real seeded history instead.
    # Committed, not just flushed: the assertions below go through the API,
    # which opens its own session and cannot see this transaction.
    db.commit()
    return case


_TEST_CASE = select(CaseRecord.case_id).where(CaseRecord.name == "Test investigation")
_TEST_SOURCE = select(SourceRecord.source_id).where(SourceRecord.name == "Test source")


def _purge(db, case: CaseRecord | None = None) -> None:
    """Remove fixture rows, child-first, and tolerate earlier aborted runs.

    A test that leaves rows behind when it fails is worse than no test: the
    next run trips over them and the failure gets attributed to the wrong
    code. Purging by name rather than by the current test's id makes this
    self-healing, which matters because ``audit_logs`` cannot be cleaned by
    ``DELETE`` at all and these fixtures deliberately write none.
    """
    if case is None:
        case_ids = _TEST_CASE
    else:
        case_ids = _TEST_CASE.union(
            select(CaseRecord.case_id).where(CaseRecord.case_id == case.case_id)
        )
    hypothesis_ids = select(HypothesisRecord.hypothesis_id).where(
        HypothesisRecord.case_id.in_(case_ids)
    )
    db.execute(
        HypothesisLinkRecord.__table__.delete().where(
            HypothesisLinkRecord.hypothesis_id.in_(hypothesis_ids)
        )
    )
    for model in (
        AssessmentRecord,
        HypothesisRecord,
        RelationshipRecord,
        EntityRecord,
    ):
        db.execute(model.__table__.delete().where(model.case_id.in_(case_ids)))
    # Evidence is removed by source as well as by case, so rows left behind
    # by a run that died before its case could be cleaned still go away.
    db.execute(
        EvidenceRecord.__table__.delete().where(
            EvidenceRecord.case_id.in_(case_ids) | EvidenceRecord.source_id.in_(_TEST_SOURCE)
        )
    )
    # A case that an earlier version of this fixture wrote audit rows for can
    # never be deleted: `audit_logs` is append-only by database trigger and its
    # `case_id` foreign key has no ON DELETE CASCADE. Those cases are excluded
    # rather than left to abort the whole purge. This is precisely why the
    # fixture itself writes no audit rows.
    deletable = select(CaseRecord.case_id).where(
        CaseRecord.case_id.in_(case_ids),
        ~CaseRecord.case_id.in_(
            select(AuditLogRecord.case_id).where(AuditLogRecord.case_id.is_not(None))
        ),
    )
    db.execute(CaseRecord.__table__.delete().where(CaseRecord.case_id.in_(deletable)))
    db.execute(SourceRecord.__table__.delete().where(SourceRecord.source_id.in_(_TEST_SOURCE)))
    db.commit()


@pytest.fixture(autouse=True)
def _clean_fixture_rows(db_available: bool) -> Iterator[None]:
    if db_available:
        with SessionLocal() as db:
            _purge(db)
            _purge(db)
    yield
    if db_available:
        with SessionLocal() as db:
            _purge(db)


def test_queue_entry_explains_its_score(db_available: bool) -> None:
    from aegis.api.dashboard_analytics import queue_entry

    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        case = _seed(db, priority="critical", severity="critical")
        try:
            entry = queue_entry(
                case,
                {"contradictions": 2, "recent_evidence": 60, "relationships": 300},
                last_activity=None,
                attribution=0.64,
                now=datetime.now(UTC),
            )
            assert entry.queue_score > 0
            keys = {reason.key for reason in entry.reasons}
            # Every contributor named in the plan must be present and summed.
            assert {"priority", "severity", "contradictions", "evidence_velocity"} <= keys
            # The declared score is exactly the sum of the declared reasons.
            assert entry.queue_score == min(100, sum(reason.weight for reason in entry.reasons))
            assert entry.queue_reason == entry.reasons[0].label
        finally:
            _purge(db, case)


def test_dashboard_endpoints_are_typed(auth_headers: dict[str, str], db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = TestClient(app)
    snapshot = client.get("/api/v1/dashboard/summary", headers=auth_headers).json()
    assert set(snapshot["command_posture"]) >= {
        "active_investigations",
        "critical",
        "sla_at_risk",
        "pressure_index",
    }
    assert isinstance(snapshot["investigation_pressure"], list)
    for indicator in snapshot["investigation_pressure"]:
        # The score must be readable as a fraction of a stated ceiling.
        assert 0 <= indicator["score"] <= 100
        assert indicator["ceiling"] > 0
    # The window must end with the current month, or today's collection is
    # invisible on the chart.
    current = datetime.now(UTC).strftime("%b %Y")
    assert snapshot["evidence_velocity"][-1]["label"] == current

    cases = client.get("/api/v1/dashboard/cases", headers=auth_headers).json()
    for row in cases:
        assert row["sla_state"] in {"breached", "at_risk", "ok", "none"}
        assert row["reasons"], "every queue row must be able to explain itself"


def test_case_graph_and_hypotheses_are_case_scoped(
    auth_headers: dict[str, str], db_available: bool
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    with SessionLocal() as db:
        case = _seed(db)
        case_id = case.case_id
        try:
            client = TestClient(app)
            graph = client.get(f"/api/v1/cases/{case_id}/graph", headers=auth_headers).json()
            assert graph["case_id"] == str(case_id)
            assert {node["type"] for node in graph["nodes"]} == {"domain", "actor"}
            assert graph["edges"][0]["type"] == "controls"
            # Degree is resolved server-side so the inspector can always
            # describe the node it is showing.
            assert all(node["degree"] >= 1 for node in graph["nodes"])

            # Filtering nodes must also drop edges into the hidden nodes.
            filtered = client.get(
                f"/api/v1/cases/{case_id}/graph",
                params={"node_type": "actor"},
                headers=auth_headers,
            ).json()
            assert [node["type"] for node in filtered["nodes"]] == ["actor"]
            assert filtered["edges"] == []

            hypotheses = client.get(
                f"/api/v1/cases/{case_id}/hypotheses", headers=auth_headers
            ).json()
            assert len(hypotheses) == 1
            assert hypotheses[0]["calibrated_confidence"] == pytest.approx(0.64)
            assert hypotheses[0]["independent_source_groups"] == 1

            metrics = client.get(f"/api/v1/cases/{case_id}/metrics", headers=auth_headers).json()
            assert metrics["evidence"] == 1
            assert metrics["attribution"] == pytest.approx(0.64)
            assert metrics["independent_sources"] == 1

            signals = client.get(f"/api/v1/cases/{case_id}/signals", headers=auth_headers).json()
            assert {row["modality"] for row in signals} == {
                "Behavioral",
                "Infrastructure",
                "Financial",
                "Stylometry",
                "Temporal",
            }
            for row in signals:
                assert 0.0 <= row["support_value"] <= 1.0
                assert 0.0 <= row["freshness"] <= 100.0
        finally:
            _purge(db, case)


def test_admin_surfaces(auth_headers: dict[str, str], db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = TestClient(app)

    team = client.get("/api/v1/admin/team", headers=auth_headers).json()
    assert "members" in team and "roles" in team

    audit = client.get("/api/v1/admin/audit", headers=auth_headers, params={"limit": 5}).json()
    assert audit["total"] >= 0
    # The verdict is recomputed by AuditService, not read from a stored flag.
    # A tampered row anywhere in the chain must flip it.
    assert isinstance(audit["chain_valid"], bool)
    with SessionLocal() as db:
        assert audit["chain_valid"] == AuditService(db).verify_chain()

    system = client.get("/api/v1/admin/system", headers=auth_headers).json()
    assert system["database_status"] == "ok"
    assert system["api_status"] == "ok"
    assert system["auth_mode"] in {"session-token", "api-key"}
    assert "opensearch" in system["adapters"]

    models = client.get("/api/v1/models", headers=auth_headers).json()
    assert "runs" in models


def test_workspace_case_must_exist(auth_headers: dict[str, str], db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = TestClient(app)
    missing = uuid4()
    for suffix in ("workspace", "graph", "hypotheses", "signals", "timeline", "metrics"):
        response = client.get(f"/api/v1/cases/{missing}/{suffix}", headers=auth_headers)
        assert response.status_code == 404, suffix


def test_password_hashing_round_trips() -> None:
    from aegis.api.security import hash_password, verify_password

    encoded = hash_password("correct horse", iterations=1_000)
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong horse", encoded)
    # A malformed stored value must fail closed, not raise.
    assert not verify_password("anything", "not-a-hash")
    assert not verify_password("anything", "")
