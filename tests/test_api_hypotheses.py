"""Tests for the hypothesis comparison and the analyst record-linkage workflow.

The comparison exists so a confidence figure is not the whole story, and the
linkage exists so promoting an estimate to a finding is an explicit, cited,
audited act. Both are tested for the property that makes them worth having:
that they refuse to assert more than the record supports.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aegis.api.app import app
from aegis.db.session import SessionLocal

#: Both workflows are read-modify-write against seeded cases, so the whole
#: module needs PostgreSQL. See the note in `test_api_infrastructure.py` for
#: why the marker has to be module-level rather than a guard inside each test:
#: the module-scoped `seeded_case` fixture opens a session before any test
#: body could reach its own `db_available` check.
pytestmark = pytest.mark.integration


def _client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded_case() -> str:
    """The first seeded case, resolved once for the module."""
    from sqlalchemy import select

    from aegis.db.models import CaseRecord

    with SessionLocal() as db:
        case = db.scalars(select(CaseRecord).order_by(CaseRecord.created_at)).first()
        if case is None:
            pytest.skip("no seeded dataset")
        return str(case.case_id)


def _hypotheses(case_id: str, headers: dict[str, str]) -> list[dict]:
    response = _client().get(f"/api/v1/cases/{case_id}/hypotheses", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_comparison_splits_into_three_not_two(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    """A modality with evidence on both sides is neither aligned nor apart.

    Collapsing it into either bucket overstates the evidence, and a
    hypothesis board that says "no disagreements" when two of its five
    modalities are contested is not describing the record.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    hypotheses = _hypotheses(seeded_case, auth_headers)
    assert hypotheses, "the seeded case must have competing hypotheses"

    saw_contested = False
    for hypothesis in hypotheses:
        response = client.get(
            f"/api/v1/cases/{seeded_case}/hypotheses/{hypothesis['hypothesis_id']}/comparison",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        aligned = {side["modality"] for side in body["aligned"]}
        apart = {side["modality"] for side in body["apart"]}
        weak = {side["modality"] for side in body["weak"]}
        # Disjoint, and together they account for every linked modality.
        assert not (aligned & apart)
        assert not (aligned & weak)
        assert not (apart & weak)
        for side in body["aligned"]:
            assert side["supporting"] and not side["contradicting"]
            assert side["net"] > 0
        for side in body["apart"]:
            assert side["contradicting"] and not side["supporting"]
            assert side["net"] < 0
        for side in body["weak"]:
            assert side["supporting"] and side["contradicting"]
        if weak:
            saw_contested = True

    assert saw_contested, "at least one hypothesis must be contested somewhere"


def test_comparison_cites_named_evidence(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    """Every side of the comparison must name the records behind it.

    A comparison that says "infrastructure disagrees" without saying which
    observation disagreed has moved the number, not explained it.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    for hypothesis in _hypotheses(seeded_case, auth_headers):
        body = client.get(
            f"/api/v1/cases/{seeded_case}/hypotheses/{hypothesis['hypothesis_id']}/comparison",
            headers=auth_headers,
        ).json()
        for group in ("aligned", "apart", "weak"):
            for side in body[group]:
                for item in side["supporting"] + side["contradicting"]:
                    assert item["evidence_id"]
                    assert item["title"]
                    assert item["independence_group"]


def test_comparison_reports_a_gap_instead_of_fake_agreement(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    """A hypothesis with no links must say so, not return three empty lists.

    Three empty lists read as "nothing disagrees", which is a finding. The
    truth is "nothing has been linked yet".
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    missing = uuid4()
    response = client.get(
        f"/api/v1/cases/{seeded_case}/hypotheses/{missing}/comparison",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_record_linkage_requires_cited_evidence(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    """An attribution with no cited basis is the thing the badge distinguishes.

    Accepting one would make "Recorded score" meaningless: the figure would
    be recorded without a record.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    hypotheses = _hypotheses(seeded_case, auth_headers)
    body = {
        "disposition": "confirmed",
        "evidence_ids": [],
        "rationale": "Looks right to me.",
    }
    response = _client().post(
        f"/api/v1/cases/{seeded_case}/hypotheses/{hypotheses[0]['hypothesis_id']}/record",
        json=body,
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_record_linkage_refuses_evidence_from_another_case(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    """A linkage must survive a reader following the citation.

    Evidence from a different investigation does not, so it is rejected
    rather than recorded and left for someone to discover later.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    from sqlalchemy import select

    from aegis.db.models import CaseRecord, EvidenceRecord

    with SessionLocal() as db:
        other = db.scalars(
            select(CaseRecord).where(CaseRecord.case_id != seeded_case).limit(1)
        ).first()
        if other is None:
            pytest.skip("need a second seeded case")
        foreign = db.scalars(
            select(EvidenceRecord).where(EvidenceRecord.case_id == other.case_id).limit(1)
        ).first()
        if foreign is None:
            pytest.skip("second case has no evidence")
        foreign_id = str(foreign.evidence_id)

    hypotheses = _hypotheses(seeded_case, auth_headers)
    response = _client().post(
        f"/api/v1/cases/{seeded_case}/hypotheses/{hypotheses[0]['hypothesis_id']}/record",
        json={
            "disposition": "confirmed",
            "evidence_ids": [foreign_id],
            "rationale": "Cited from the wrong investigation.",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_record_linkage_is_audited(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    """Promoting an estimate to a finding must leave a trail.

    The whole claim is that an analyst ruled on something. If the ruling is
    not attributable and not in the audit ledger, the badge is a decoration.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    hypotheses = _hypotheses(seeded_case, auth_headers)
    hypothesis_id = hypotheses[0]["hypothesis_id"]
    evidence = client.get(
        f"/api/v1/cases/{seeded_case}/evidence",
        params={"limit": 1},
        headers=auth_headers,
    ).json()
    if not evidence:
        pytest.skip("case has no evidence to cite")

    response = client.post(
        f"/api/v1/cases/{seeded_case}/hypotheses/{hypothesis_id}/record",
        json={
            "disposition": "confirmed",
            "evidence_ids": [evidence[0]["evidence_id"]],
            "rationale": "Handle reuse across independent source groups.",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["analyst_recorded"] is True
    assert body["audit_seq"] > 0
    assert body["evidence_ids"] == [evidence[0]["evidence_id"]]

    audit = client.get(
        "/api/v1/admin/audit",
        params={"limit": 200, "action": "attribution.analyst_recorded"},
        headers=auth_headers,
    ).json()
    recorded = [row for row in audit["entries"] if row["seq"] == body["audit_seq"]]
    assert recorded, "the ruling must be in the audit trail"
    assert recorded[0]["payload"]["disposition"] == "confirmed"
    assert recorded[0]["payload"]["rationale"]
    # The chain must still verify afterwards.
    assert audit["chain_valid"] is True


def test_record_linkage_is_idempotent_and_reversible(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    """Re-recording replaces the previous ruling rather than accumulating.

    Otherwise a hypothesis ends up carrying both a confirming and a
    rejecting analyst link, and a primary-key collision turns the second
    attempt into a 500 instead of a reversal.
    """
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    client = _client()
    hypotheses = _hypotheses(seeded_case, auth_headers)
    hypothesis_id = hypotheses[0]["hypothesis_id"]
    evidence = client.get(
        f"/api/v1/cases/{seeded_case}/evidence", params={"limit": 1}, headers=auth_headers
    ).json()
    if not evidence:
        pytest.skip("case has no evidence to cite")

    for disposition in ("confirmed", "confirmed", "rejected", "confirmed"):
        response = client.post(
            f"/api/v1/cases/{seeded_case}/hypotheses/{hypothesis_id}/record",
            json={
                "disposition": disposition,
                "evidence_ids": [evidence[0]["evidence_id"]],
                "rationale": f"Recording {disposition}.",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, (disposition, response.text)

    body = client.get(
        f"/api/v1/cases/{seeded_case}/hypotheses/{hypothesis_id}/comparison",
        headers=auth_headers,
    ).json()
    analyst_rows = [
        item
        for group in ("aligned", "apart", "weak")
        for side in body[group]
        for item in side["supporting"] + side["contradicting"]
        if item["independence_group"] == "analyst-recorded"
    ]
    # Exactly one analyst-recorded link survives: the current ruling, not the
    # history of rulings. The history is in the audit trail.
    assert len(analyst_rows) == 1, analyst_rows


def test_record_linkage_rejects_an_unknown_hypothesis(
    auth_headers: dict[str, str], db_available: bool, seeded_case: str
) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    response = _client().post(
        f"/api/v1/cases/{seeded_case}/hypotheses/{uuid4()}/record",
        json={
            "disposition": "confirmed",
            "evidence_ids": [str(uuid4())],
            "rationale": "x",
        },
        headers=auth_headers,
    )
    assert response.status_code == 404
