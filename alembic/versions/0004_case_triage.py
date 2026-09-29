"""case triage fields + investigative notes

``CaseRecord`` carried only ``name``/``description``/``status``, so the API
schema's ``tags`` field was a dead declaration: it was never persisted and
every read returned an empty tuple. There was no way to record priority,
severity, ownership or an SLA, and no investigative log distinct from the
immutable system audit trail.

This migration adds:

* ``cases.priority``      — triage ordering (low/medium/high/critical)
* ``cases.severity``      — impact band (informational/low/medium/high/critical)
* ``cases.tags``          — JSONB, now actually persisted
* ``cases.assigned_to``   — analyst UUID, FK to ``users``
* ``cases.sla_due_at``    — response deadline
* ``cases.closed_at`` / ``cases.closure_reason`` — closure discipline
* ``cases.updated_at``    — last triage mutation

and a new ``case_notes`` table: free-text investigative notes that are
*analyst-authored and mutable-in-place-by-author*, deliberately separate
from ``audit_logs`` (append-only, hash-chained, system-generated).

A closing check constraint rejects a closed case without a closure reason, so
"closed" is never a bare status flip.

Revision ID: 0004_case_triage
Revises: 0003_observation
Create Date: 2026-09-29
"""

from alembic import op

revision = "0004_case_triage"
down_revision = "0003_observation"
branch_labels = None
depends_on = None

CASE_STATUSES = "('open', 'active', 'on_hold', 'closed', 'archived')"
CASE_PRIORITIES = "('low', 'medium', 'high', 'critical')"
CASE_SEVERITIES = "('informational', 'low', 'medium', 'high', 'critical')"


def upgrade() -> None:
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS priority VARCHAR(16)")
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS severity VARCHAR(16)")
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS tags JSONB")
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS assigned_to UUID")
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS sla_due_at TIMESTAMPTZ")
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS closure_reason TEXT")
    op.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")

    # Backfill so the NOT NULL + CHECK constraints below can be applied to
    # rows that already exist: status='closed' rows need a closure reason.
    op.execute("UPDATE cases SET priority = 'medium' WHERE priority IS NULL")
    op.execute("UPDATE cases SET severity = 'medium' WHERE severity IS NULL")
    op.execute("UPDATE cases SET tags = '[]'::jsonb WHERE tags IS NULL")
    op.execute(
        "UPDATE cases SET closure_reason = 'Closed before triage fields existed' "
        "WHERE status = 'closed' AND closure_reason IS NULL"
    )

    op.execute("ALTER TABLE cases ALTER COLUMN priority SET NOT NULL")
    op.execute("ALTER TABLE cases ALTER COLUMN severity SET NOT NULL")
    op.execute("ALTER TABLE cases ALTER COLUMN tags SET NOT NULL")
    op.execute("ALTER TABLE cases ALTER COLUMN tags SET DEFAULT '[]'::jsonb")

    op.execute(
        "ALTER TABLE cases ADD CONSTRAINT ck_cases_priority "
        f"CHECK (priority IN {CASE_PRIORITIES})"
    )
    op.execute(
        "ALTER TABLE cases ADD CONSTRAINT ck_cases_severity "
        f"CHECK (severity IN {CASE_SEVERITIES})"
    )
    op.execute(
        "ALTER TABLE cases ADD CONSTRAINT ck_cases_tags_is_array "
        "CHECK (jsonb_typeof(tags) = 'array')"
    )
    # A case may not sit in a terminal state without a recorded reason.
    op.execute(
        "ALTER TABLE cases ADD CONSTRAINT ck_cases_closure_reason "
        "CHECK (status <> 'closed' "
        "OR (closure_reason IS NOT NULL AND btrim(closure_reason) <> ''))"
    )
    # Keep updated_at fresh on every mutation.
    op.execute(
        "CREATE OR REPLACE FUNCTION aegis_touch_updated_at() RETURNS trigger AS $$ "
        "BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_cases_updated_at ON cases")
    op.execute(
        "CREATE TRIGGER trg_cases_updated_at BEFORE UPDATE ON cases "
        "FOR EACH ROW EXECUTE FUNCTION aegis_touch_updated_at()"
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_cases_assigned_to ON cases (assigned_to)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cases_sla_due_at ON cases (sla_due_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cases_status ON cases (status)")

    # The column is added above as a bare UUID so the backfill runs without
    # depending on `users`; the constraint is attached once it exists.
    # ON DELETE SET NULL keeps cases alive when an analyst account is removed.
    op.execute("ALTER TABLE cases DROP CONSTRAINT IF EXISTS fk_cases_assigned_to")
    op.execute(
        "ALTER TABLE cases ADD CONSTRAINT fk_cases_assigned_to "
        "FOREIGN KEY (assigned_to) REFERENCES users(user_id) ON DELETE SET NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS case_notes (
            note_id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
            author_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE case_notes ADD CONSTRAINT ck_case_notes_body CHECK (btrim(body) <> '')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_case_notes_case_id ON case_notes (case_id, created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_case_notes_author_id ON case_notes (author_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_case_notes_author_id")
    op.execute("DROP INDEX IF EXISTS ix_case_notes_case_id")
    op.execute("DROP TABLE IF EXISTS case_notes")

    op.execute("ALTER TABLE cases DROP CONSTRAINT IF EXISTS fk_cases_assigned_to")
    op.execute("DROP INDEX IF EXISTS ix_cases_status")
    op.execute("DROP INDEX IF EXISTS ix_cases_sla_due_at")
    op.execute("DROP INDEX IF EXISTS ix_cases_assigned_to")
    op.execute("DROP TRIGGER IF EXISTS trg_cases_updated_at ON cases")
    op.execute("DROP FUNCTION IF EXISTS aegis_touch_updated_at()")

    op.execute("ALTER TABLE cases DROP CONSTRAINT IF EXISTS ck_cases_closure_reason")
    op.execute("ALTER TABLE cases DROP CONSTRAINT IF EXISTS ck_cases_tags_is_array")
    op.execute("ALTER TABLE cases DROP CONSTRAINT IF EXISTS ck_cases_severity")
    op.execute("ALTER TABLE cases DROP CONSTRAINT IF EXISTS ck_cases_priority")

    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS closure_reason")
    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS closed_at")
    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS sla_due_at")
    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS assigned_to")
    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS tags")
    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS severity")
    op.execute("ALTER TABLE cases DROP COLUMN IF EXISTS priority")
