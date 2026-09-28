"""complete the evidence ledger: identities, graph, hypotheses, assessments,
model registry, and the append-only hash-chained audit log

Revision ID: 0002_ledger
Revises: c17711a67dbb
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_ledger"
down_revision = "c17711a67dbb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------- roles
    op.create_table(
        "roles",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "permissions", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_roles_name", "roles", ["name"])

    # --------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("totp_secret", sa.String(128), nullable=True),
        sa.Column(
            "role_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.role_id"), nullable=False,
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role_id", "users", ["role_id"])

    # ------------------------------------------------------------ entities
    op.create_table(
        "entities",
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.case_id"), nullable=True,
        ),
        sa.Column(
            "evidence_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.evidence_id"), nullable=False,
        ),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("surface_form", sa.String(1024), nullable=False),
        sa.Column("normalized_form", sa.String(1024), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=True),
        sa.Column("span_end", sa.Integer(), nullable=True),
        sa.Column("span_field", sa.String(64), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_entities_case_id", "entities", ["case_id"])
    op.create_index("ix_entities_evidence_id", "entities", ["evidence_id"])
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index("ix_entities_normalized_form", "entities", ["normalized_form"])
    op.create_index(
        "ix_entities_type_normalized", "entities", ["entity_type", "normalized_form"]
    )
    op.create_index("ix_entities_first_seen", "entities", ["first_seen"])
    op.create_index("ix_entities_last_seen", "entities", ["last_seen"])

    # -------------------------------------------------------- relationships
    op.create_table(
        "relationships",
        sa.Column("relationship_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.case_id"), nullable=True,
        ),
        sa.Column(
            "subject_entity_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.entity_id"), nullable=False,
        ),
        sa.Column(
            "object_entity_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.entity_id"), nullable=False,
        ),
        sa.Column("relationship_type", sa.String(64), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "evidence_ids", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_relationships_case_id", "relationships", ["case_id"])
    op.create_index(
        "ix_relationships_subject", "relationships", ["subject_entity_id"]
    )
    op.create_index("ix_relationships_object", "relationships", ["object_entity_id"])
    op.create_index(
        "ix_relationships_type", "relationships", ["relationship_type"]
    )
    op.create_index("ix_relationships_first_seen", "relationships", ["first_seen"])
    op.create_index("ix_relationships_last_seen", "relationships", ["last_seen"])

    # ---------------------------------------------------------- hypotheses
    op.create_table(
        "hypotheses",
        sa.Column("hypothesis_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.case_id"), nullable=False,
        ),
        sa.Column(
            "subject_entity_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.entity_id"), nullable=False,
        ),
        sa.Column(
            "object_entity_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.entity_id"), nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column(
            "missing_evidence", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("analyst_disposition", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_hypotheses_case_id", "hypotheses", ["case_id"])
    op.create_index("ix_hypotheses_subject", "hypotheses", ["subject_entity_id"])
    op.create_index("ix_hypotheses_object", "hypotheses", ["object_entity_id"])

    # ----------------------------------------------------- hypothesis links
    op.create_table(
        "hypothesis_links",
        sa.Column("link_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hypothesis_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hypotheses.hypothesis_id"), nullable=False,
        ),
        sa.Column(
            "evidence_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence.evidence_id"), nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("modality", sa.String(64), nullable=False),
        sa.Column("independence_group", sa.String(128), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_hypothesis_links_hypothesis", "hypothesis_links", ["hypothesis_id"])
    op.create_index("ix_hypothesis_links_evidence", "hypothesis_links", ["evidence_id"])
    op.create_index(
        "ix_hypothesis_links_independence", "hypothesis_links", ["independence_group"]
    )

    # ---------------------------------------------------------- assessments
    op.create_table(
        "assessments",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hypothesis_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hypotheses.hypothesis_id"), nullable=False,
        ),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.case_id"), nullable=False,
        ),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("calibrated_confidence", sa.Float(), nullable=True),
        sa.Column("calibration_version", sa.String(64), nullable=True),
        sa.Column(
            "signals_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "supporting_evidence_ids", postgresql.JSONB(), nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "contradictory_evidence_ids", postgresql.JSONB(), nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "explanations", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "limitations", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_assessments_hypothesis", "assessments", ["hypothesis_id"])
    op.create_index("ix_assessments_case_id", "assessments", ["case_id"])
    op.create_index("ix_assessments_raw_score", "assessments", ["raw_score"])

    # ---------------------------------------------------------- model runs
    op.create_table(
        "model_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("dataset_version", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("git_commit", sa.String(64), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column(
            "hyperparameters_json", postgresql.JSONB(), nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "metrics_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "calibration_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "artifact_paths", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_model_runs_model_id", "model_runs", ["model_id"])

    # ---------------------------------------------------------- audit logs
    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_logs_seq START 1")
    op.create_table(
        "audit_logs",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "seq", sa.BigInteger(),
            sa.Sequence("audit_logs_seq"), nullable=False, unique=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"), nullable=True,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.case_id"), nullable=True,
        ),
        sa.Column(
            "payload_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("entry_hash", sa.String(64), nullable=False, unique=True),
    )
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])
    op.create_index("ix_audit_logs_case_id", "audit_logs", ["case_id"])
    op.create_index("ix_audit_logs_entry_hash", "audit_logs", ["entry_hash"])
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])

    # Append-only enforcement: UPDATE/DELETE raise, keeping the chain verifiable.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only; supersede entries instead';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_mutation
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_mutation ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    op.drop_table("audit_logs")
    op.execute("DROP SEQUENCE IF EXISTS audit_logs_seq")
    op.drop_table("model_runs")
    op.drop_table("assessments")
    op.drop_table("hypothesis_links")
    op.drop_table("hypotheses")
    op.drop_table("relationships")
    op.drop_table("entities")
    op.drop_table("users")
    op.drop_table("roles")
