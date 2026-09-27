"""initial AEGIS evidence and provenance schema"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "collection_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.source_id"),
            nullable=False,
        ),
        sa.Column("collector_name", sa.String(128), nullable=False),
        sa.Column("collector_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.case_id"), nullable=True
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.source_id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=True),
        sa.Column("entity_value_hash", sa.String(128), nullable=True),
        sa.Column("context_hash", sa.String(128), nullable=True),
        sa.Column("raw_artifact_uri", sa.Text(), nullable=False),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.artifact_id"),
            nullable=True,
        ),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("collector_name", sa.String(128), nullable=False),
        sa.Column("collector_version", sa.String(64), nullable=False),
        sa.Column("normalizer_version", sa.String(64), nullable=True),
        sa.Column("extraction_version", sa.String(64), nullable=True),
        sa.Column("source_reliability", sa.Float(), nullable=False),
        sa.Column("independence_group", sa.String(128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_evidence_case_id", "evidence", ["case_id"])
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"])
    op.create_index("ix_evidence_observed_at", "evidence", ["observed_at"])
    op.create_index("ix_evidence_collected_at", "evidence", ["collected_at"])
    op.create_index("ix_evidence_sha256", "evidence", ["sha256"])
    op.create_index("ix_evidence_independence_group", "evidence", ["independence_group"])
    op.create_table(
        "evidence_derivations",
        sa.Column("derivation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "derived_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.evidence_id"),
            nullable=False,
        ),
        sa.Column(
            "parent_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.evidence_id"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("tool_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_evidence_derivations_derived", "evidence_derivations", ["derived_evidence_id"]
    )
    op.create_index(
        "ix_evidence_derivations_parent", "evidence_derivations", ["parent_evidence_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_derivations_parent", table_name="evidence_derivations")
    op.drop_index("ix_evidence_derivations_derived", table_name="evidence_derivations")
    op.drop_table("evidence_derivations")
    for index in [
        "ix_evidence_independence_group",
        "ix_evidence_sha256",
        "ix_evidence_collected_at",
        "ix_evidence_observed_at",
        "ix_evidence_source_id",
        "ix_evidence_case_id",
    ]:
        op.drop_index(index, table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("collection_jobs")
    op.drop_table("artifacts")
    op.drop_table("sources")
    op.drop_table("cases")
