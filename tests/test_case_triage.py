"""Case triage: PATCH semantics, closure discipline, notes, hypothesis scoping.

These are pure unit tests over the handler functions with a stub session, so
they run without PostgreSQL. The DB-level CHECK constraints added by
migration 0004 are exercised separately in ``test_case_triage_migration``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from aegis.api.case_triage import case_is_overdue
from aegis.api.workspace import create_case_note, list_case_notes
from aegis.db.models import CaseRecord
from aegis.schemas.evidence import CaseNoteCreate, CaseUpdate


class _Stub:
    """Minimal stand-in for a CaseRecord row."""

    def __init__(self, **overrides):
        self.case_id = overrides.get("case_id", uuid4())
        self.name = overrides.get("name", "demo")
        self.description = overrides.get("description", None)
        self.status = overrides.get("status", "open")
        self.priority = overrides.get("priority", "medium")
        self.severity = overrides.get("severity", "medium")
        self.tags = overrides.get("tags", [])
        self.assigned_to = overrides.get("assigned_to", None)
        self.sla_due_at = overrides.get("sla_due_at", None)
        self.closed_at = overrides.get("closed_at", None)
        self.closure_reason = overrides.get("closure_reason", None)
        self.created_at = overrides.get("created_at", datetime.now(UTC))
        self.updated_at = overrides.get("updated_at", None)


# ---------------------------------------------------------------------------
# case_is_overdue
# ---------------------------------------------------------------------------


def test_overdue_requires_a_deadline() -> None:
    assert case_is_overdue(_Stub()) is False


def test_overdue_when_deadline_passed() -> None:
    record = _Stub(sla_due_at=datetime.now(UTC) - timedelta(minutes=1))
    assert case_is_overdue(record) is True


def test_not_overdue_when_deadline_in_future() -> None:
    record = _Stub(sla_due_at=datetime.now(UTC) + timedelta(days=1))
    assert case_is_overdue(record) is False


def test_closed_case_never_overdue_even_with_stale_deadline() -> None:
    record = _Stub(
        status="closed",
        closure_reason="referred",
        closed_at=datetime.now(UTC),
        sla_due_at=datetime.now(UTC) - timedelta(days=90),
    )
    assert case_is_overdue(record) is False


def test_archived_case_never_overdue() -> None:
    record = _Stub(status="archived", sla_due_at=datetime.now(UTC) - timedelta(days=90))
    assert case_is_overdue(record) is False


def test_overdue_uses_injected_now() -> None:
    """`now` is injectable so the boundary is testable without clock games."""
    deadline = datetime(2026, 1, 1, tzinfo=UTC)
    record = _Stub(sla_due_at=deadline)
    # One second before the deadline the case is not yet in breach.
    assert case_is_overdue(record, now=deadline - timedelta(seconds=1)) is False
    # One second after, it is.
    assert case_is_overdue(record, now=deadline + timedelta(seconds=1)) is True


# ---------------------------------------------------------------------------
# CaseUpdate payload semantics
# ---------------------------------------------------------------------------


def test_update_reports_only_supplied_fields() -> None:
    assert CaseUpdate(priority="high").supplied() == {"priority"}


def test_update_excludes_injected_schema_version() -> None:
    """CanonicalModel injects schema_version in a before-validator.

    It is always "set", so it must not be reported as a changed field.
    """
    assert "schema_version" not in CaseUpdate().supplied()
    assert "schema_version" not in CaseUpdate(priority="low").supplied()


def test_update_with_nothing_supplied_is_empty() -> None:
    assert CaseUpdate().supplied() == set()


def test_update_ignores_non_updatable_keys() -> None:
    assert CaseUpdate().UPDATABLE.isdisjoint({"schema_version", "case_id"})


def test_update_tags_replace_rather_than_merge() -> None:
    """tags is a whole-list replacement so the last tag can be removed."""
    payload = CaseUpdate(tags=("solo",))
    assert payload.tags == ("solo",)
    assert payload.supplied() == {"tags"}


def test_note_body_rejects_blank() -> None:
    with pytest.raises(ValueError):
        CaseNoteCreate(body="   ")


def test_note_body_accepts_surrounding_whitespace_with_content() -> None:
    assert CaseNoteCreate(body="  observed wallet reuse  ").body.strip()


# ---------------------------------------------------------------------------
# Notes endpoint scoping
# ---------------------------------------------------------------------------


class _NoteDB:
    """Stub session recording the queries the notes endpoints issue."""

    def __init__(self, case: _Stub) -> None:
        self.case = case
        self.added: list[object] = []
        self.wheres: list[object] = []

    def get(self, model, key):
        return self.case if key == self.case.case_id else None

    def scalars(self, statement):
        self.wheres.append(statement)
        return _Rows([])

    def add(self, record):
        self.added.append(record)

    def flush(self) -> None:
        # Emulate SQLAlchemy applying column defaults on INSERT, which is
        # what populates `default=uuid4` / `server_default=func.now()`.
        for record in self.added:
            for column, value in list(
                (column, getattr(record, column.key, None)) for column in record.__table__.columns
            ):
                if value is None and column.default is not None:
                    setattr(record, column.key, column.default.arg(None))

    def commit(self) -> None:
        return None

    def refresh(self, record) -> None:
        # Emulate server_default=func.now() for `created_at`.
        if getattr(record, "created_at", None) is None:
            record.created_at = datetime.now(UTC)


class _Rows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


@pytest.fixture
def stub_audit(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace AuditService with a recorder.

    AuditService opens a real advisory-lock transaction against the bound
    session, which a stub session cannot satisfy. The audit side effect is
    asserted separately, so here we only need to observe that the handler
    *attempts* an audit write without touching the chain.
    """
    calls: list[str] = []

    class _RecordingAudit:
        def __init__(self, db):
            self.db = db

        def record(self, action: str, **kwargs):
            calls.append(action)

    monkeypatch.setattr("aegis.api.workspace.AuditService", _RecordingAudit)
    return calls


def test_notes_reject_unknown_case() -> None:
    db = _NoteDB(_Stub(case_id=uuid4()))
    with pytest.raises(HTTPException) as excinfo:
        list_case_notes(uuid4(), db)  # type: ignore[arg-type]
    assert excinfo.value.status_code == 404


def test_create_note_stores_stripped_body(stub_audit: list[str]) -> None:
    case = _Stub()
    db = _NoteDB(case)
    note = create_case_note(
        case.case_id, CaseNoteCreate(body="  wallet reuse across two markets  "), db
    )
    assert note.body == "wallet reuse across two markets"
    assert note.case_id == case.case_id
    assert len(db.added) == 1
    # A note write is auditable, distinct from the note itself.
    assert stub_audit == ["case.note_added"]


def test_create_note_rejects_unknown_case() -> None:
    db = _NoteDB(_Stub(case_id=uuid4()))
    with pytest.raises(HTTPException) as excinfo:
        create_case_note(uuid4(), CaseNoteCreate(body="note"), db)  # type: ignore[arg-type]
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# Model-level invariants
# ---------------------------------------------------------------------------


def test_case_record_declares_triage_columns() -> None:
    """Guards against the columns being dropped from the ORM but not the DB."""
    expected = {
        "priority",
        "severity",
        "tags",
        "assigned_to",
        "sla_due_at",
        "closed_at",
        "closure_reason",
        "updated_at",
    }
    assert expected <= set(CaseRecord.__table__.columns.keys())


def test_case_notes_table_is_case_scoped() -> None:
    from aegis.db.models import CaseNoteRecord

    columns = CaseNoteRecord.__table__.columns
    assert "case_id" in columns
    foreign_keys = {fk.target_fullname for fk in columns["case_id"].foreign_keys}
    assert foreign_keys == {"cases.case_id"}


def test_assignee_and_note_author_use_set_null_on_user_delete() -> None:
    """Removing an analyst must not delete the cases they worked.

    The model declares ON DELETE SET NULL; this asserts it so the behaviour
    cannot be changed silently in one place only.
    """
    from aegis.db.models import CaseNoteRecord

    for table, column in (
        (CaseRecord.__table__, "assigned_to"),
        (CaseNoteRecord.__table__, "author_id"),
    ):
        foreign_keys = list(table.columns[column].foreign_keys)
        assert len(foreign_keys) == 1, f"{table.name}.{column} should have one FK"
        assert foreign_keys[0].target_fullname == "users.user_id"
        assert foreign_keys[0].ondelete == "SET NULL"


def test_case_notes_cascade_with_their_case() -> None:
    from aegis.db.models import CaseNoteRecord

    fk = next(iter(CaseNoteRecord.__table__.columns["case_id"].foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_migration_declares_the_assignee_foreign_key() -> None:
    """The migration must create the FK the ORM declares.

    ``ALTER TABLE cases ADD COLUMN assigned_to UUID`` alone gives a bare
    column, so the constraint has to be added explicitly. Without this the
    migrated database silently drifts from the ORM: no referential integrity,
    and Alembic autogenerate reports a spurious diff.
    """
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0004_case_triage.py"
    ).read_text(encoding="utf-8")
    assert "ADD CONSTRAINT fk_cases_assigned_to" in migration
    assert "REFERENCES users(user_id) ON DELETE SET NULL" in migration


def test_case_note_cascade_is_declared_in_migration() -> None:
    """Cascade delete is expressed in SQL, so assert it textually."""
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0004_case_triage.py"
    ).read_text(encoding="utf-8")
    assert "case_id UUID NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE" in migration


def test_closure_check_constraint_exists() -> None:
    names = {c.name for c in CaseRecord.__table__.constraints}
    assert "ck_cases_closure_reason" in names
    assert "ck_cases_priority" in names
    assert "ck_cases_severity" in names


def test_uuid_type_is_usable_as_primary_key() -> None:
    """Sanity check that CaseRecord still maps a UUID primary key."""
    assert isinstance(CaseRecord.__table__.columns["case_id"].type.python_type, type(UUID))


def test_cors_allows_every_method_the_app_routes() -> None:
    """The CORS allow-list must cover every verb the app actually routes.

    ``settings.cors_origins`` defaults to ``""``, so the middleware is not
    installed during the test session and the drift is invisible to any test
    that exercises the app end to end. Cross-origin callers get a preflight
    rejection instead, while same-origin ones (the Vite dev proxy) never
    notice. Deriving the expectation from the live route table means adding a
    new verb without widening the allow-list fails here.
    """
    import re
    from pathlib import Path

    from aegis.api.app import app

    source = (Path(__file__).resolve().parents[1] / "src" / "aegis" / "api" / "app.py").read_text(
        encoding="utf-8"
    )
    block = re.search(r"allow_methods=\[([^\]]*)\]", source)
    assert block is not None, "allow_methods is no longer a literal list in app.py"
    allowed = set(re.findall(r'"([A-Z]+)"', block.group(1)))

    # Only non-safelisted methods force a preflight, so only those can be
    # rejected by a missing allow_methods entry. GET/HEAD/POST are safelisted
    # and pass regardless; OPTIONS is answered by the middleware itself.
    safelisted = {"GET", "HEAD", "POST", "OPTIONS"}
    routed = {
        method
        for route in app.routes
        for method in getattr(route, "methods", ()) or ()
        if method not in safelisted
    }
    assert routed, "no preflighted methods found - guard is not exercising anything"
    assert routed - allowed == set(), f"routed but not CORS-allowed: {sorted(routed - allowed)}"
