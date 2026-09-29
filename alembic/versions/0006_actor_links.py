"""Directed actor-to-actor links: the trust graph the problem statement names.

Adds `actor_links`, which completes the second core capability. Identifiers
and marketplace presence are rows hanging off an actor; the relations
*between* actors had nowhere to live, so the single relationship graph the
statement asks for did not exist.

Two constraints encode judgement rather than shape. `subject_actor_id <>
object_actor_id`, because a self-link is a data error rather than a
relation. And the recorded-link constraint: a link an analyst has ruled on
must name who ruled, when, and the basis they relied on — a decision with
no author and no reason is indistinguishable from a model output, which is
the distinction `analyst_recorded` exists to preserve.

Revision ID: 0006_actor_links
Revises: 0005_actor_registry
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_actor_links"
down_revision = "0005_actor_registry"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "actor_links",
        sa.Column("link_id", UUID, primary_key=True),
        sa.Column("subject_actor_id", UUID, sa.ForeignKey("actors.actor_id"), nullable=False),
        sa.Column("object_actor_id", UUID, sa.ForeignKey("actors.actor_id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("basis", sa.Text, nullable=True),
        sa.Column("limitations", JSONB, nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.source_id"), nullable=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.case_id"), nullable=True),
        sa.Column("evidence_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("analyst_recorded", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("recorded_by", UUID, sa.ForeignKey("users.user_id"), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("subject_actor_id", "object_actor_id", "kind", name="uq_actor_link"),
        sa.CheckConstraint(
            "subject_actor_id <> object_actor_id", name="ck_actor_link_distinct_actors"
        ),
        sa.CheckConstraint(
            "kind IN ('trusts', 'works_with', 'sells_to', 'mentions', 'disputes',"
            " 'shares_identifier')",
            name="ck_actor_link_kind",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_actor_link_confidence_range",
        ),
        sa.CheckConstraint(
            "NOT analyst_recorded OR (recorded_by IS NOT NULL AND recorded_at IS NOT NULL"
            " AND basis IS NOT NULL)",
            name="ck_actor_link_recorded",
        ),
    )
    op.create_index("ix_actor_links_subject_actor_id", "actor_links", ["subject_actor_id"])
    op.create_index("ix_actor_links_object_actor_id", "actor_links", ["object_actor_id"])
    op.create_index("ix_actor_links_kind", "actor_links", ["kind"])
    op.create_index("ix_actor_links_case_id", "actor_links", ["case_id"])
    op.create_index("ix_actor_links_subject_kind", "actor_links", ["subject_actor_id", "kind"])


def downgrade() -> None:
    op.drop_table("actor_links")
