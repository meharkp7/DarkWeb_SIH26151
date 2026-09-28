from datetime import UTC, datetime
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

    body = workspace(Case.case_id, _DB(Case()))
    assert body["case"]["name"] == "demo"
    assert body["counts"] == {
        "evidence": 0,
        "entities": 0,
        "relationships": 0,
        "assessments": 0,
    }
