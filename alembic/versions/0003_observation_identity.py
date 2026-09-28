"""evidence identity = observation, not content

The global UNIQUE on ``evidence.sha256`` conflated content identity with
observation identity: the same bytes re-observed from another source or at
a later scan were rejected with a conflict, defeating last-scan tracking
and independence counting. Content identity belongs on ``artifacts.sha256``
(already unique); an evidence row is one observation, keyed by
``(source_id, sha256, observed_at)`` with ``NULLS NOT DISTINCT`` so an
idempotent re-submit of the same observation (including an unknown
observation time) still conflicts.

The ``ix_evidence_sha256`` index is kept (non-unique) for content lookups
and the ledger load test's plan assertion.

Revision ID: 0003_observation
Revises: 0002_ledger
Create Date: 2026-09-28
"""

from alembic import op

revision = "0003_observation"
down_revision = "0002_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fresh installs from 0001 carry the column-level unique constraint;
    # databases created from model metadata carry a unique ix_evidence_sha256.
    # Drop both forms, then rebuild the index non-unique.
    op.execute("ALTER TABLE evidence DROP CONSTRAINT IF EXISTS evidence_sha256_key")
    op.execute("DROP INDEX IF EXISTS ix_evidence_sha256")
    op.execute("CREATE INDEX ix_evidence_sha256 ON evidence (sha256)")
    op.execute(
        "ALTER TABLE evidence "
        "ADD CONSTRAINT uq_evidence_observation "
        "UNIQUE NULLS NOT DISTINCT (source_id, sha256, observed_at)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE evidence DROP CONSTRAINT IF EXISTS uq_evidence_observation")
    op.execute("DROP INDEX IF EXISTS ix_evidence_sha256")
    op.execute("CREATE UNIQUE INDEX ix_evidence_sha256 ON evidence (sha256)")
