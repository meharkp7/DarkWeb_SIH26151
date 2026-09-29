"""Observed timeline events: the substrate the change detectors read.

`aegis.timeline` can find regime changes, but every one of its detectors takes a
stream of `TimelineEvent` objects and nothing in the database was one. The
registry stored *windows* — `actor_marketplaces` holds a first-seen and a
last-seen per venue — and a window is not an observation: a state detector needs
to see the new value persist across following events before it will believe a
move, and a numeric detector needs a count per bucket. Two rows cannot show
either.

So this adds `temporal_observations`: one row per sighting, on one channel, for
one subject, at one time. The windows stay — they are the summary, and the
registry reads them — but the detection runs over this stream.

The two constraints that carry judgement rather than shape:

* exactly one of `actor_id` / `entity_id` must be set. A subject is either a
  tracked persona or a case-scoped extracted entity, and a row naming both (or
  neither) has no single meaning for the detectors, which require one subject
  per stream.
* `value` is never blank. A state channel is compared for equality; an
  observation with no value is not a state, and admitting one would let the
  detector record a transition to nothing.

`magnitude` is the numeric weight of the sighting on the activity channel —
`build_activity_series` counts events per bucket and ignores it, so it is stored
for charting rather than for detection, and is nullable because the two
categorical channels have no magnitude to record.

Revision ID: 0007_temporal_observations
Revises: 0006_actor_links
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_temporal_observations"
down_revision = "0006_actor_links"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "temporal_observations",
        sa.Column("observation_id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.case_id"), nullable=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("actors.actor_id"), nullable=True),
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.entity_id"), nullable=True),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("subject_kind", sa.String(16), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.String(256), nullable=False),
        sa.Column("magnitude", sa.Float, nullable=True),
        sa.Column("evidence_id", UUID, sa.ForeignKey("evidence.evidence_id"), nullable=True),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.source_id"), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "channel IN ('handle', 'marketplace', 'activity')",
            name="ck_temporal_observation_channel",
        ),
        sa.CheckConstraint(
            "subject_kind IN ('actor', 'entity')", name="ck_temporal_observation_subject_kind"
        ),
        # A detector's stream must belong to exactly one subject.
        sa.CheckConstraint(
            "(actor_id IS NOT NULL AND entity_id IS NULL)"
            " OR (actor_id IS NULL AND entity_id IS NOT NULL)",
            name="ck_temporal_observation_single_subject",
        ),
        sa.CheckConstraint("btrim(value) <> ''", name="ck_temporal_observation_value"),
    )
    op.create_index(
        "ix_temporal_observations_actor_channel",
        "temporal_observations",
        ["actor_id", "channel", "observed_at"],
    )
    op.create_index(
        "ix_temporal_observations_entity_channel",
        "temporal_observations",
        ["entity_id", "channel", "observed_at"],
    )
    op.create_index("ix_temporal_observations_case_id", "temporal_observations", ["case_id"])
    op.create_index(
        "ix_temporal_observations_subject_channel",
        "temporal_observations",
        ["subject_id", "channel", "observed_at"],
    )
    op.create_index(
        "ix_temporal_observations_channel_observed_at",
        "temporal_observations",
        ["channel", "observed_at"],
    )


def downgrade() -> None:
    op.drop_table("temporal_observations")
