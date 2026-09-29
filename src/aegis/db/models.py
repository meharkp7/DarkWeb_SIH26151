from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Sequence,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from aegis.db.base import Base


class UUIDList(TypeDecorator[Any]):
    """A ``list[UUID]`` stored in a JSONB column.

    psycopg serialises JSONB with the standard library encoder, which has no
    idea what a ``UUID`` is — so a plain ``Mapped[list[UUID]]`` raises
    ``TypeError: Object of type UUID is not JSON serializable`` at flush time,
    not at import or declaration time. Every writer would have to remember to
    stringify first, and every reader would have to remember that it is
    looking at strings.

    Doing it in the type keeps the annotation honest in both directions:
    callers pass and receive ``UUID`` objects, and the column holds canonical
    strings. Rows written before this type existed already hold strings, so
    they read back unchanged.
    """

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return [str(item) if isinstance(item, UUID) else item for item in value]

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        parsed: list[Any] = []
        for item in value:
            try:
                parsed.append(item if isinstance(item, UUID) else UUID(str(item)))
            except (TypeError, ValueError, AttributeError):
                # A malformed element is dropped rather than failing the whole
                # read: evidence-id lists are advisory annotations on a record,
                # and one bad entry must not make a case unreadable.
                continue
        return parsed


class CaseRecord(Base):
    """Investigation case with analyst triage fields (migration 0004).

    ``priority``/``severity`` drive queue ordering, ``tags`` is persisted
    JSONB (it was a dead schema field before 0004), and ``sla_due_at`` makes
    response deadlines explicit. ``assigned_to`` is deliberately nullable:
    a case can be opened before an owner is assigned.
    """

    __tablename__ = "cases"
    # Mirrors the CHECK constraints in migration 0004 so databases built from
    # model metadata enforce the same invariants as migrated ones.
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')", name="ck_cases_priority"
        ),
        CheckConstraint(
            "severity IN ('informational', 'low', 'medium', 'high', 'critical')",
            name="ck_cases_severity",
        ),
        CheckConstraint("jsonb_typeof(tags) = 'array'", name="ck_cases_tags_is_array"),
        CheckConstraint(
            "status <> 'closed' OR (closure_reason IS NOT NULL AND btrim(closure_reason) <> '')",
            name="ck_cases_closure_reason",
        ),
        # Mirrors `ix_cases_status` in migration 0004. The queue is filtered by
        # status, so without this every open-cases query is a sequential scan.
        Index("ix_cases_status", "status"),
    )
    case_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseNoteRecord(Base):
    """Analyst-authored investigative note.

    Distinct from :class:`AuditLogRecord`: notes are free-text working
    commentary that analysts write during an investigation, whereas the audit
    trail is system-generated, append-only and hash-chained. A note is tied
    to a case (cascade-deleted with it) and optionally to an author.
    """

    __tablename__ = "case_notes"
    __table_args__ = (
        # Mirrors `ix_case_notes_case_id` in migration 0004. Composite rather
        # than a bare `index=True` on case_id because the only read path is
        # "notes for a case, newest first": the composite lets Postgres serve
        # the filter and the ORDER BY from one index instead of sorting.
        Index("ix_case_notes_case_id", "case_id", "created_at"),
    )
    note_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceRecord(Base):
    __tablename__ = "sources"
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    reliability: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArtifactRecord(Base):
    __tablename__ = "artifacts"
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionJobRecord(Base):
    __tablename__ = "collection_jobs"
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.source_id"), nullable=False
    )
    collector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    collector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EvidenceRecord(Base):
    __tablename__ = "evidence"
    #: Observation identity: the same content re-observed from another
    #: source or at a later scan is a distinct evidence row. Content
    #: (bytes) identity lives on ArtifactRecord, not here.
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "sha256",
            "observed_at",
            name="uq_evidence_observation",
            postgresql_nulls_not_distinct=True,
        ),
    )
    evidence_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.source_id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    entity_value_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.artifact_id"), nullable=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    collector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    collector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_reliability: Mapped[float] = mapped_column(Float, nullable=False)
    independence_group: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvidenceDerivationRecord(Base):
    __tablename__ = "evidence_derivations"
    derivation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    derived_evidence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evidence.evidence_id"), nullable=False, index=True
    )
    parent_evidence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evidence.evidence_id"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttributionHypothesisRecord(Base):
    __tablename__ = "attribution_hypotheses"

    hypothesis_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_actor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_actor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    support_score: Mapped[float] = mapped_column(Float, nullable=False)
    contradiction_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    explanations_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HypothesisContradictionRecord(Base):
    __tablename__ = "hypothesis_contradictions"

    contradiction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    hypothesis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("attribution_hypotheses.hypothesis_id"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    contradiction_type: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 03 — complete evidence ledger
# ---------------------------------------------------------------------------


class RoleRecord(Base):
    """RBAC role with explicit permission strings."""

    __tablename__ = "roles"

    role_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRecord(Base):
    """Analyst account. Credentials are never stored in plain text."""

    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.role_id"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EntityRecord(Base):
    """Typed extracted entity with span provenance (Phase 03/07)."""

    __tablename__ = "entities"

    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evidence.evidence_id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    surface_form: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_form: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    span_start: Mapped[int | None] = mapped_column(nullable=True)
    span_end: Mapped[int | None] = mapped_column(nullable=True)
    span_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RelationshipRecord(Base):
    """Temporally bounded, evidence-backed typed edge."""

    __tablename__ = "relationships"

    relationship_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    subject_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False, index=True
    )
    object_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_ids: Mapped[list[UUID]] = mapped_column(
        UUIDList, nullable=False, default=list, server_default="[]"
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HypothesisRecord(Base):
    """Canonical case-scoped hypothesis (spec §27)."""

    __tablename__ = "hypotheses"

    hypothesis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=False, index=True
    )
    subject_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False, index=True
    )
    object_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    missing_evidence: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    analyst_disposition: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HypothesisLinkRecord(Base):
    """One evidence item's role in a hypothesis."""

    __tablename__ = "hypothesis_links"

    link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    hypothesis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hypotheses.hypothesis_id"), nullable=False, index=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evidence.evidence_id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    modality: Mapped[str] = mapped_column(String(64), nullable=False)
    independence_group: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentRecord(Base):
    """Model output for a hypothesis: raw score + calibrated confidence."""

    __tablename__ = "assessments"

    assessment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    hypothesis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hypotheses.hypothesis_id"), nullable=False, index=True
    )
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    calibrated_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signals_json: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    supporting_evidence_ids: Mapped[list[UUID]] = mapped_column(
        UUIDList, nullable=False, default=list, server_default="[]"
    )
    contradictory_evidence_ids: Mapped[list[UUID]] = mapped_column(
        UUIDList, nullable=False, default=list, server_default="[]"
    )
    explanations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    limitations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRunRecord(Base):
    """MLOps experiment registry row (spec §33)."""

    __tablename__ = "model_runs"

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hyperparameters_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    metrics_json: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    calibration_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    artifact_paths: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLogRecord(Base):
    """Append-only, hash-chained audit trail.

    UPDATE and DELETE are blocked by a database trigger (see migration 0002);
    corrections are new entries referencing the superseded one.
    """

    __tablename__ = "audit_logs"

    audit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    seq: Mapped[int] = mapped_column(
        BigInteger, Sequence("audit_logs_seq"), nullable=False, unique=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)


# ---------------------------------------------------------------------------
# Actor registry
#
# The problem statement's central deliverable is a result set of threat actor
# profiles — handle, category, identifiers, persona linkages, attribution
# confidence, last scan date and source. Until now an actor was only an
# `entities` row of type "actor", which cannot carry a registry: it has no
# identity of its own, no scan state, and no way to say which marketplaces a
# persona was seen on.
#
# These tables are that registry. They deliberately do not replace
# `entities`/`relationships` — a case graph still holds the case-scoped
# evidence, and an actor here is a cross-case intelligence object that
# several cases may reference.
# ---------------------------------------------------------------------------


class ActorRecord(Base):
    """One tracked threat actor, independent of any single investigation."""

    __tablename__ = "actors"

    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    handle: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    #: Primary category as the problem statement requires it on every row of
    #: the result set: drugs, arms, stolen data, hacking services, money
    #: laundering, terror financing, and so on.
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: `active`, `dormant`, `rebranded`, `retired`, `unknown`. Distinct from
    #: a case status: this is the actor's observed state, not a workflow one.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    #: Attributed confidence 0-1. Nullable because "not assessed" and
    #: "assessed at zero" are different facts and must not collapse.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: When this actor was last re-scanned. The problem statement requires
    #: last scan date on the result set, and it is a different fact from
    #: last_seen: an actor can be seen daily and scanned monthly.
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.source_id"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_actors_confidence_range",
        ),
        Index("ix_actors_category_status", "category", "status"),
    )


class ActorIdentifierRecord(Base):
    """A handle, PGP key, wallet, onion address or messenger handle.

    Independence matters here and is modelled explicitly: three handles on one
    onion service are not three sources, and an analyst has to be able to
    discount them.
    """

    __tablename__ = "actor_identifiers"

    identifier_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("actors.actor_id"), nullable=False, index=True
    )
    #: handle, pgp, wallet, onion, clearnet, jabber, tor_ref, marketplace
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    #: Groups identifiers that are not independent observations. Two handles
    #: in the same thread are one source wearing two hats.
    independence_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.source_id"), nullable=True
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("actor_id", "kind", "value", name="uq_actor_identifier"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_actor_identifier_confidence_range",
        ),
    )


class ActorMarketplaceRecord(Base):
    """Where a persona trades.

    The second core capability is mapping one actor across many marketplaces.
    A row per (actor, marketplace) with a presence window is what makes
    "seen on four venues, moved off two of them in the last quarter" a
    question the data can answer.
    """

    __tablename__ = "actor_marketplaces"

    presence_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("actors.actor_id"), nullable=False, index=True
    )
    marketplace: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Listings attributed to this persona on this venue, when known.
    listing_count: Mapped[int | None] = mapped_column(nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.source_id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (UniqueConstraint("actor_id", "marketplace", name="uq_actor_marketplace"),)


# ---------------------------------------------------------------------------
# Tor hidden-service infrastructure findings
#
# The first core capability: find misconfigurations in Tor hidden services —
# exposed server-status pages, certificates tied to clearnet domains, default
# banners, descriptor inconsistencies — and match them against clearnet
# infrastructure to point at the likely origin.
#
# `InfrastructureObservation` and the correlation functions already exist in
# `aegis.infrastructure`; what was missing was anywhere to put the results.
# --------------------------------------------------------------------------


class InfrastructureObservationRecord(Base):
    """One observation of a hidden service, with its extracted features.

    `features_json` holds the `InfrastructureFeatures` payload verbatim rather
    than being exploded into columns: the channel set grows as new correlation
    dimensions are added, and a normalised table would mean a migration per
    dimension for data that is only ever read as a whole.
    """

    __tablename__ = "infrastructure_observations"

    observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    #: The hidden-service subject: an onion address, or a clearnet host when
    #: the observation is the comparison side.
    subject: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    #: `onion` or `clearnet`. The correlation is between the two, and a
    #: finding that does not record which side a subject came from cannot be
    #: reasoned about afterwards.
    network: Mapped[str] = mapped_column(String(16), nullable=False, default="onion", index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    features_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    evidence_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evidence.evidence_id"), nullable=True
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint("network IN ('onion', 'clearnet')", name="ck_infra_observation_network"),
        Index("ix_infra_observation_subject_network", "subject", "network"),
    )


class InfrastructureFindingRecord(Base):
    """A misconfiguration found in a hidden service.

    `kind` is constrained to the four classes the problem statement names, so
    a finding cannot be filed as something the platform does not actually
    detect. An unrecognised detection is a new detector, not a new label.
    """

    __tablename__ = "infrastructure_findings"

    finding_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("infrastructure_observations.observation_id"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", index=True)
    #: What was found, in the operator's terms, and — separately — what it
    #: does and does not imply. A detector that reports a certificate reuse
    #: without saying shared hosting is possible is not actionable.
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    evidence_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evidence.evidence_id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('exposed_status_page', 'clearnet_certificate', 'default_banner',"
            " 'descriptor_inconsistency', 'shared_fingerprint')",
            name="ck_infra_finding_kind",
        ),
        CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low', 'informational')",
            name="ck_infra_finding_severity",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_infra_finding_confidence_range",
        ),
    )


class InfrastructureMatchRecord(Base):
    """A correlation between a hidden service and a clearnet host.

    The per-channel breakdown is kept, not just the overall score. "0.92
    similar" is useless; "0.97 on certificate fingerprint, nothing on
    technology" is a finding with a known alternative explanation.
    """

    __tablename__ = "infrastructure_matches"

    match_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    onion_observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("infrastructure_observations.observation_id"),
        nullable=False,
        index=True,
    )
    clearnet_observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("infrastructure_observations.observation_id"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    overall: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    breakdown_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    limitations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    #: The strongest channel, named. Correlation can be carried entirely by
    #: one dimension, and an analyst needs to know which before relying on it.
    strongest_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint("overall >= 0 AND overall <= 1", name="ck_infra_match_overall_range"),
        CheckConstraint(
            "onion_observation_id <> clearnet_observation_id",
            name="ck_infra_match_distinct_observations",
        ),
    )


# ---------------------------------------------------------------------------
# Persona linkage
#
# The third core capability: link rebranded or migrated personas to known
# actors using stylometry and behavioural profiling.
#
# A linkage is a *proposal* until an analyst rules on it, exactly like an
# attribution assessment. The model's score and the analyst's decision are
# kept in separate columns so the badge can distinguish them, and so a
# rejected proposal remains visible as a rejected one rather than vanishing.
# --------------------------------------------------------------------------


class PersonaLinkageRecord(Base):
    """A proposed or adjudicated link between a candidate persona and an actor."""

    __tablename__ = "persona_linkages"

    linkage_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("actors.actor_id"), nullable=False, index=True
    )
    #: The candidate: usually a handle or a corpus key, not a handle the
    #: platform has already resolved to this actor.
    candidate_handle: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    #: `stylometry`, `behavioural`, `infrastructure`, `attribution`, `manual`
    method: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: The model's output, 0-1. Never overwritten by a human decision.
    score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    #: `proposed`, `confirmed`, `rejected`. Only an adjudicated row may be
    #: presented as a finding.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed", index=True)
    #: Which features agree and which disagree, named. The same three-way
    #: discipline as the hypothesis comparison: a one-sided feature is
    #: aligned, an opposed one is apart, and anything measured on both sides
    #: is contested rather than being quietly counted either way.
    aligned_features: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    apart_features: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    contested_features: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    limitations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    adjudicated_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    adjudicated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("actor_id", "candidate_handle", "method", name="uq_persona_linkage"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_persona_linkage_score_range"),
        CheckConstraint(
            "status IN ('proposed', 'confirmed', 'rejected')",
            name="ck_persona_linkage_status",
        ),
        CheckConstraint(
            "method IN ('stylometry', 'behavioural', 'infrastructure', 'attribution', 'manual')",
            name="ck_persona_linkage_method",
        ),
        # An adjudicated row must say who ruled, when, and why. A decision
        # with no rationale is indistinguishable from a model output, which is
        # precisely the distinction this table exists to preserve.
        CheckConstraint(
            "(status = 'proposed') OR (adjudicated_by IS NOT NULL AND adjudicated_at IS NOT NULL",
            name="ck_persona_linkage_adjudicated",
        ),
    )


class ActorLinkRecord(Base):
    """A directed edge between two tracked actors.

    The problem statement's second capability is "mapping threat actors
    across multiple marketplaces into a single relationship graph of handles,
    PGP keys, wallets and **trust links**". Identifiers and marketplaces are
    rows on an actor; the links *between* actors had nowhere to live, so the
    graph the statement asks for did not exist.

    Two decisions are load-bearing:

    * **Trust is directed.** A trusts B is not B trusts A — a vendor vouches
      for a buyer far more often than the reverse, and a symmetric edge
      would erase the asymmetry that makes the relation worth recording.
      `work_with` and `disputes` are recorded with the same table and their
      own direction rule, so one query answers "who does this actor deal
      with, and in what capacity".

    * **Every link must state its basis.** A trust edge with no recorded
      reason is an assertion. `basis` is free text precisely because the
      basis is frequently a sentence a human wrote, and forcing it into an
      enum would mean either losing the detail or refusing to record the
      link at all.
    """

    __tablename__ = "actor_links"

    link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    subject_actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("actors.actor_id"), nullable=False, index=True
    )
    object_actor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("actors.actor_id"), nullable=False, index=True
    )
    #: trusts, works_with, sells_to, mentions, disputes, shares_identifier
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: What the trust is evidenced by, in a sentence. Nullable only because a
    #: link proposed by a model before analyst review has none yet, which is
    #: exactly what `analyst_recorded` distinguishes.
    basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What would make this link wrong, or what it does not establish.
    limitations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.source_id"), nullable=True
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id"), nullable=True, index=True
    )
    evidence_ids: Mapped[list[UUID]] = mapped_column(
        UUIDList, nullable=False, default=list, server_default="[]"
    )
    #: True once a human has ruled on it. Mirrors `persona_linkages` for the
    #: same reason: a model proposal and an analyst finding are different
    #: things and must never be presented as one.
    analyst_recorded: Mapped[bool] = mapped_column(nullable=False, default=False)
    recorded_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint(
            "subject_actor_id <> object_actor_id", name="ck_actor_link_distinct_actors"
        ),
        CheckConstraint(
            "kind IN ('trusts', 'works_with', 'sells_to', 'mentions', 'disputes',"
            " 'shares_identifier')",
            name="ck_actor_link_kind",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_actor_link_confidence_range",
        ),
        # A recorded link must say who ruled and when. A decision with no
        # author is indistinguishable from a model output, which is the
        # distinction `analyst_recorded` exists to preserve.
        CheckConstraint(
            "NOT analyst_recorded OR (recorded_by IS NOT NULL AND recorded_at IS NOT NULL"
            " AND basis IS NOT NULL)",
            name="ck_actor_link_recorded",
        ),
        Index("ix_actor_links_subject_kind", "subject_actor_id", "kind"),
    )
