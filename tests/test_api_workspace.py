from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aegis.api.workspace import workspace
from aegis.schemas.workspace import WorkspaceResponse


class _ScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _DB:
    """Minimal session stand-in.

    The workspace endpoint runs five separate `scalars()` queries, so the
    fake has to answer per table rather than returning one list for all of
    them — otherwise the evidence rows get fed to the entity serializer.
    """

    def __init__(self, case, evidence=()):
        self.case = case
        self.evidence = list(evidence)

    def get(self, model, key):
        return self.case if key == self.case.case_id else None

    def scalars(self, statement):
        # Match on the FROM clause, not a bare substring: `entities` also has
        # an `evidence_id` column, so "evidence" appears in its projection too.
        sql = str(statement).lower()
        if "from evidence" in sql:
            return _ScalarResult(self.evidence)
        return _ScalarResult([])


def _case(**overrides):
    class Case:
        case_id = uuid4()
        name = "demo"
        description = "synthetic"
        status = "open"
        priority = "medium"
        severity = "medium"
        tags = ["demo"]
        assigned_to = None
        sla_due_at = None
        closed_at = None
        closure_reason = None
        created_at = datetime.now(UTC)
        updated_at = None

    for key, value in overrides.items():
        setattr(Case, key, value)
    return Case()


def test_workspace_empty_case() -> None:
    class Case:
        case_id = uuid4()
        name = "demo"
        description = "synthetic"
        status = "open"
        priority = "medium"
        severity = "medium"
        tags = ["demo"]
        assigned_to = None
        sla_due_at = None
        closed_at = None
        closure_reason = None
        created_at = datetime.now(UTC)
        updated_at = None

    body = workspace(Case.case_id, _DB(Case()))
    assert body["case"]["name"] == "demo"
    assert body["case"]["priority"] == "medium"
    assert body["case"]["tags"] == ["demo"]
    # No SLA deadline set, so it cannot be in breach.
    assert body["case"]["sla_overdue"] is False
    assert body["counts"] == {
        "evidence": 0,
        "entities": 0,
        "relationships": 0,
        "assessments": 0,
    }


def test_workspace_flags_sla_breach() -> None:
    class Case:
        case_id = uuid4()
        name = "overdue"
        description = None
        status = "active"
        priority = "critical"
        severity = "high"
        tags = []
        assigned_to = None
        sla_due_at = datetime.now(UTC) - timedelta(days=1)
        closed_at = None
        closure_reason = None
        created_at = datetime.now(UTC)
        updated_at = None

    body = workspace(Case.case_id, _DB(Case()))
    assert body["case"]["sla_overdue"] is True


def test_workspace_closed_case_is_not_overdue() -> None:
    """A closed case with a stale deadline in the past is not a breach."""

    class Case:
        case_id = uuid4()
        name = "closed"
        description = None
        status = "closed"
        priority = "low"
        severity = "low"
        tags = []
        assigned_to = None
        sla_due_at = datetime.now(UTC) - timedelta(days=30)
        closed_at = datetime.now(UTC) - timedelta(days=1)
        closure_reason = "Attributed and referred"
        created_at = datetime.now(UTC)
        updated_at = None

    body = workspace(Case.case_id, _DB(Case()))
    assert body["case"]["sla_overdue"] is False


def _evidence_row(**overrides):
    """A stand-in for the ORM row the workspace serializer reads."""

    class Row:
        evidence_id = uuid4()
        source_id = uuid4()
        source_type = "marketplace"
        observed_at = datetime(2026, 4, 7, 4, 12, 44, tzinfo=UTC)
        collected_at = datetime(2026, 4, 7, 7, 36, 44, tzinfo=UTC)
        entity_type = "domain"
        source_reliability = 0.79
        independence_group = "demo-source-1"
        sha256 = "a" * 64
        metadata_json = {"title": "Listing", "language": "en"}

    for key, value in overrides.items():
        setattr(Row, key, value)
    return Row()


def test_workspace_evidence_satisfies_the_declared_contract() -> None:
    """The payload must validate against `WorkspaceResponse`.

    This is the guard that was missing: the endpoint returned an untyped dict,
    so the serializer could omit fields the frontend's `WorkspaceEvidence`
    interface claimed were always present, and nothing noticed until a screen
    dereferenced one. Validating here makes that a test failure instead.
    """
    case = _case()
    body = workspace(case.case_id, _DB(case, evidence=[_evidence_row()]))

    parsed = WorkspaceResponse.model_validate(body)

    assert len(parsed.evidence) == 1
    assert parsed.evidence[0].independence_group == "demo-source-1"
    assert parsed.evidence[0].observed_at == datetime(2026, 4, 7, 4, 12, 44, tzinfo=UTC)
    assert parsed.evidence[0].entity_type == "domain"
    assert parsed.evidence[0].metadata["title"] == "Listing"


def test_workspace_evidence_keeps_fields_the_timeline_depends_on() -> None:
    """`observed_at` and `independence_group` must survive serialization.

    `observed_at` is what separates "seen on the source" from "collected by
    us"; without it the Timeline view cannot show collection latency and has
    to issue a second request for the same data. `independence_group` is what
    distinguishes genuinely separate corroboration from the same source
    restated, so a confidence figure without it is not interpretable.
    """
    case = _case()
    body = workspace(case.case_id, _DB(case, evidence=[_evidence_row()]))

    block = body["evidence"][0]
    assert "observed_at" in block
    assert "independence_group" in block
    assert "entity_type" in block
    assert "metadata" in block


def test_workspace_evidence_allows_null_observed_at() -> None:
    """`observed_at` is nullable, and a null must not break the contract."""
    case = _case()
    body = workspace(case.case_id, _DB(case, evidence=[_evidence_row(observed_at=None)]))

    parsed = WorkspaceResponse.model_validate(body)

    assert parsed.evidence[0].observed_at is None
