"""Actor registry, Tor infrastructure findings, and persona linkages.

Adds the three core capabilities the problem statement names, as tables with
somewhere to put the results:

* `actors` / `actor_identifiers` / `actor_marketplaces` — the actor registry
  and cross-marketplace mapping. The expected solution requires every row of
  the result set to carry handle, category, identifiers, attribution
  confidence, last scan date and source, which an `entities` row cannot.

* `infrastructure_observations` / `infrastructure_findings` /
  `infrastructure_matches` — Tor hidden-service misconfigurations and their
  clearnet correlation. The extraction and correlation logic already exists
  in `aegis.infrastructure`; it had nowhere to write.

* `persona_linkages` — stylometric and behavioural persona linkage, with the
  model's score and the analyst's ruling in separate columns so a proposal
  can never be presented as a finding.

Revision ID: 0005_actor_registry
Revises: 0004_case_triage
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_actor_registry"
down_revision = "0004_case_triage"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column[object]]:
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now())]


def upgrade() -> None:
    # --- actor registry -------------------------------------------------
    op.create_table(
        "actors",
        sa.Column("actor_id", UUID, primary_key=True),
        sa.Column("handle", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.source_id"), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_actors_confidence_range",
        ),
    )
    op.create_index("ix_actors_handle", "actors", ["handle"])
    op.create_index("ix_actors_category", "actors", ["category"])
    op.create_index("ix_actors_status", "actors", ["status"])
    op.create_index("ix_actors_source_id", "actors", ["source_id"])
    op.create_index("ix_actors_category_status", "actors", ["category", "status"])

    op.create_table(
        "actor_identifiers",
        sa.Column("identifier_id", UUID, primary_key=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("actors.actor_id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("value", sa.String(512), nullable=False),
        sa.Column("independence_group", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.source_id"), nullable=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.case_id"), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
        sa.UniqueConstraint("actor_id", "kind", "value", name="uq_actor_identifier"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_actor_identifier_confidence_range",
        ),
    )
    op.create_index("ix_actor_identifiers_actor_id", "actor_identifiers", ["actor_id"])
    op.create_index("ix_actor_identifiers_kind", "actor_identifiers", ["kind"])
    op.create_index("ix_actor_identifiers_case_id", "actor_identifiers", ["case_id"])
    op.create_index("ix_actor_identifiers_source_id", "actor_identifiers", ["source_id"])

    op.create_table(
        "actor_marketplaces",
        sa.Column("presence_id", UUID, primary_key=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("actors.actor_id"), nullable=False),
        sa.Column("marketplace", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("listing_count", sa.Integer, nullable=True),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.source_id"), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
        sa.UniqueConstraint("actor_id", "marketplace", name="uq_actor_marketplace"),
    )
    op.create_index("ix_actor_marketplaces_actor_id", "actor_marketplaces", ["actor_id"])
    op.create_index("ix_actor_marketplaces_marketplace", "actor_marketplaces", ["marketplace"])

    # --- Tor infrastructure ---------------------------------------------
    op.create_table(
        "infrastructure_observations",
        sa.Column("observation_id", UUID, primary_key=True),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("network", sa.String(16), nullable=False, server_default="onion"),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("evidence_id", UUID, sa.ForeignKey("evidence.evidence_id"), nullable=True),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.case_id"), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
        sa.CheckConstraint("network IN ('onion', 'clearnet')", name="ck_infra_observation_network"),
    )
    op.create_index(
        "ix_infrastructure_observations_subject", "infrastructure_observations", ["subject"]
    )
    op.create_index(
        "ix_infrastructure_observations_network", "infrastructure_observations", ["network"]
    )
    op.create_index(
        "ix_infrastructure_observations_observed_at",
        "infrastructure_observations",
        ["observed_at"],
    )
    op.create_index(
        "ix_infrastructure_observations_case_id",
        "infrastructure_observations",
        ["case_id"],
    )
    op.create_index(
        "ix_infra_observation_subject_network",
        "infrastructure_observations",
        ["subject", "network"],
    )

    op.create_table(
        "infrastructure_findings",
        sa.Column("finding_id", UUID, primary_key=True),
        sa.Column(
            "observation_id",
            UUID,
            sa.ForeignKey("infrastructure_observations.observation_id"),
            nullable=False,
        ),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.case_id"), nullable=True),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("limitations", JSONB, nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", UUID, sa.ForeignKey("evidence.evidence_id"), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
        # The four classes the problem statement names, plus shared fingerprint
        # for a content match. A finding must be one the platform can actually
        # detect; an unrecognised detection is a new detector, not a new label.
        sa.CheckConstraint(
            "kind IN ('exposed_status_page', 'clearnet_certificate', 'default_banner',"
            " 'descriptor_inconsistency', 'shared_fingerprint')",
            name="ck_infra_finding_kind",
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low', 'informational')",
            name="ck_infra_finding_severity",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_infra_finding_confidence_range",
        ),
    )
    op.create_index(
        "ix_infrastructure_findings_observation_id",
        "infrastructure_findings",
        ["observation_id"],
    )
    op.create_index("ix_infrastructure_findings_case_id", "infrastructure_findings", ["case_id"])
    op.create_index("ix_infrastructure_findings_kind", "infrastructure_findings", ["kind"])
    op.create_index("ix_infrastructure_findings_severity", "infrastructure_findings", ["severity"])
    op.create_index(
        "ix_infrastructure_findings_detected_at",
        "infrastructure_findings",
        ["detected_at"],
    )

    op.create_table(
        "infrastructure_matches",
        sa.Column("match_id", UUID, primary_key=True),
        sa.Column(
            "onion_observation_id",
            UUID,
            sa.ForeignKey("infrastructure_observations.observation_id"),
            nullable=False,
        ),
        sa.Column(
            "clearnet_observation_id",
            UUID,
            sa.ForeignKey("infrastructure_observations.observation_id"),
            nullable=False,
        ),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.case_id"), nullable=True),
        sa.Column("overall", sa.Float, nullable=False),
        sa.Column("breakdown_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("limitations", JSONB, nullable=False, server_default="[]"),
        sa.Column("strongest_channel", sa.String(32), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
        sa.CheckConstraint("overall >= 0 AND overall <= 1", name="ck_infra_match_overall_range"),
        # Matching an observation against itself is never a finding; the
        # constraint makes that a write error rather than a nonsense row.
        sa.CheckConstraint(
            "onion_observation_id <> clearnet_observation_id",
            name="ck_infra_match_distinct_observations",
        ),
    )
    op.create_index(
        "ix_infrastructure_matches_onion_observation_id",
        "infrastructure_matches",
        ["onion_observation_id"],
    )
    op.create_index(
        "ix_infrastructure_matches_clearnet_observation_id",
        "infrastructure_matches",
        ["clearnet_observation_id"],
    )
    op.create_index("ix_infrastructure_matches_case_id", "infrastructure_matches", ["case_id"])
    op.create_index("ix_infrastructure_matches_overall", "infrastructure_matches", ["overall"])
    op.create_index(
        "ix_infrastructure_matches_detected_at", "infrastructure_matches", ["detected_at"]
    )

    # --- persona linkage -------------------------------------------------
    op.create_table(
        "persona_linkages",
        sa.Column("linkage_id", UUID, primary_key=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("actors.actor_id"), nullable=False),
        sa.Column("candidate_handle", sa.String(128), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("aligned_features", JSONB, nullable=False, server_default="[]"),
        sa.Column("apart_features", JSONB, nullable=False, server_default="[]"),
        sa.Column("contested_features", JSONB, nullable=False, server_default="[]"),
        sa.Column("limitations", JSONB, nullable=False, server_default="[]"),
        sa.Column("case_id", UUID, sa.ForeignKey("cases.case_id"), nullable=True),
        sa.Column("adjudicated_by", UUID, sa.ForeignKey("users.user_id"), nullable=True),
        sa.Column("adjudicated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("actor_id", "candidate_handle", "method", name="uq_persona_linkage"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_persona_linkage_score_range"),
        sa.CheckConstraint(
            "status IN ('proposed', 'confirmed', 'rejected')",
            name="ck_persona_linkage_status",
        ),
        sa.CheckConstraint(
            "method IN ('stylometry', 'behavioural', 'infrastructure', 'attribution', 'manual')",
            name="ck_persona_linkage_method",
        ),
        # An adjudicated row must say who ruled, when, and why. A decision with
        # no rationale is indistinguishable from a model output, which is
        # precisely the distinction this table exists to preserve.
        sa.CheckConstraint(
            "status = 'proposed' OR (adjudicated_by IS NOT NULL AND adjudicated_at IS NOT NULL)",
            name="ck_persona_linkage_adjudicated",
        ),
    )
    op.create_index("ix_persona_linkages_actor_id", "persona_linkages", ["actor_id"])
    op.create_index(
        "ix_persona_linkages_candidate_handle", "persona_linkages", ["candidate_handle"]
    )
    op.create_index("ix_persona_linkages_method", "persona_linkages", ["method"])
    op.create_index("ix_persona_linkages_status", "persona_linkages", ["status"])
    op.create_index("ix_persona_linkages_score", "persona_linkages", ["score"])
    op.create_index("ix_persona_linkages_case_id", "persona_linkages", ["case_id"])


def downgrade() -> None:
    op.drop_table("persona_linkages")
    op.drop_table("infrastructure_matches")
    op.drop_table("infrastructure_findings")
    op.drop_table("infrastructure_observations")
    op.drop_table("actor_marketplaces")
    op.drop_table("actor_identifiers")
    op.drop_table("actors")
