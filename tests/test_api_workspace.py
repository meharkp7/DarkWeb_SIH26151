from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aegis.api.workspace import workspace


class _ScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _DB:
    def __init__(self, case):
        self.case = case

    def get(self, model, key):
        return self.case if key == self.case.case_id else None

    def scalars(self, statement):
        return _ScalarResult([])


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
