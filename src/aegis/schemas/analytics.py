"""Response schemas for the Command Center, Threat Watch and Administration.

These routes previously returned untyped ``dict[str, object]``, so their
OpenAPI schema was ``{}``: the frontend had no generated contract, a renamed
field broke a screen at runtime rather than at build time, and the "no fake
numbers" rule had nothing enforcing it. Declaring the shapes here makes the
contract explicit and turns a drift into a test failure.

The models are deliberately *descriptive* — every field answers a question an
analyst actually asked, and nothing is included "for completeness". A
posture tile that cannot be clicked through to the thing it counts is
decoration, so each aggregate is paired with the query that explains it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------
# Command Center
# --------------------------------------------------------------------------


class CommandPosture(BaseModel):
    """The six figures that answer "what needs attention right now, and why".

    Every field maps to a filter on the investigations register, which is what
    makes the tiles clickable rather than decorative.
    """

    model_config = ConfigDict(frozen=True)

    active_investigations: int
    critical: int
    high: int
    sla_at_risk: int
    new_evidence: int
    unresolved_links: int
    #: Denominator for the queue-pressure index, so a "12" can be read as
    #: 12 of 19 rather than an unexplained magnitude.
    total_investigations: int
    unassigned: int
    #: Mean of the five pressure indicators, 0-100.
    pressure_index: int


class VelocityPoint(BaseModel):
    label: str
    count: int
    #: Change against the previous bucket, as a signed count. `None` on the
    #: first bucket, where there is nothing to compare against.
    delta: int | None = None


class PressureIndicator(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    #: The raw count the score was scaled from, so the scaling is auditable.
    observed: int
    #: The count that would have produced a score of 100.
    ceiling: int


class AttributionPosture(BaseModel):
    """One leading assessment, with the evidence standing behind it.

    A bare confidence percentage is not an assessment. These rows carry the
    signal count, the number of distinct modalities, the contradictions, and
    the freshness, so an analyst can see *why* a number is what it is.
    """

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    case_name: str
    confidence: float
    supporting_signals: int
    modalities: int
    contradictions: int
    freshness: float
    explanations: list[str]
    #: Per-modality signal strengths, so the posture can be explained without
    #: a second round trip into the case.
    signals: dict[str, float] = Field(default_factory=dict)


class PriorityReason(BaseModel):
    """One named driver behind a case's queue position."""

    key: str
    label: str
    #: Signed contribution to the queue score, so the ordering is explainable
    #: rather than a black box that happens to look sensible.
    weight: int


class CaseQueueEntry(BaseModel):
    """A row in the priority queue, with the reasoning attached."""

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    name: str
    status: str
    priority: str
    severity: str
    tags: list[str]
    assigned_to: str | None
    sla_due_at: datetime | None
    sla_overdue: bool
    #: ``breached`` past due, ``at_risk`` due within 12 hours, ``ok``, or
    #: ``none`` when no deadline was set. Kept distinct from ``sla_overdue``
    #: because an investigation four hours from breach is operationally
    #: different from one that is already past it, and collapsing them makes
    #: the posture tile useless exactly when it matters.
    sla_state: str
    queue_score: int = Field(ge=0, le=100)
    queue_reason: str
    reasons: list[PriorityReason]
    counts: dict[str, int]
    last_activity: datetime | None
    attribution: float | None = None


class CaseSummary(BaseModel):
    """The investigations register row."""

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    name: str
    description: str | None
    status: str
    priority: str
    severity: str
    tags: list[str]
    assigned_to: str | None
    sla_due_at: datetime | None
    closed_at: datetime | None
    closure_reason: str | None
    sla_overdue: bool
    queue_score: int
    queue_reason: str
    reasons: list[PriorityReason]
    created_at: datetime | None
    updated_at: datetime | None
    counts: dict[str, int]
    last_activity: datetime | None
    attribution: float | None = None


class PlatformCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    cases: int
    evidence: int
    entities: int
    relationships: int
    assessments: int


class ActivityEvent(BaseModel):
    """One audit entry, as replayed by Threat Watch and the timeline."""

    model_config = ConfigDict(frozen=True)

    seq: int
    occurred_at: datetime
    action: str
    entity_type: str | None
    entity_id: str | None
    case_id: UUID | None
    payload: dict[str, Any]


class DashboardSnapshot(BaseModel):
    """The whole Command Center in one frame.

    Served by both ``GET /api/v1/dashboard/summary`` and every websocket
    snapshot, so the console renders identically whether or not the live socket
    is up.
    """

    model_config = ConfigDict(frozen=True)

    type: str = "snapshot"
    server_time: datetime
    counts: PlatformCounts
    critical_alerts: int
    activity: list[ActivityEvent]
    #: The investigations register and the priority queue read the same rows;
    #: one shape means the two views can never disagree about a case.
    case_summaries: list[CaseQueueEntry] = Field(default_factory=list)
    command_posture: CommandPosture
    evidence_velocity: list[VelocityPoint]
    investigation_pressure: list[PressureIndicator]
    attribution_posture: list[AttributionPosture]


# --------------------------------------------------------------------------
# Investigation workspace analytics
# --------------------------------------------------------------------------


class SignalBand(BaseModel):
    """HIGH / MEDIUM / LOW, plus the underlying number.

    The band alone would hide how close a value is to its neighbour, which is
    the difference between "a lead worth chasing" and "a lead to disregard".
    """

    model_config = ConfigDict(frozen=True)

    modality: str
    support: str
    contradict: str
    support_value: float
    contradict_value: float
    freshness: float


class CaseMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: UUID
    evidence: int
    links: int
    entities: int
    sources: int
    attribution: float | None
    contradictions: int
    hypotheses: int
    independent_sources: int


class TimelineEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    occurred_at: datetime
    title: str
    #: One of ``event``, ``actor``, ``infrastructure``, ``financial``.
    layer: str
    evidence_id: UUID | None
    confidence: float | None
    detail: str | None = None
    action: str | None = None
    case_id: UUID | None = None


class CaseTimeline(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: UUID
    events: list[TimelineEvent]
    layers: list[str]


class CaseHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: UUID
    kind: str
    status: str
    subject_entity_id: UUID
    object_entity_id: UUID
    missing_evidence: list[str]
    analyst_disposition: str | None
    calibrated_confidence: float | None
    raw_score: float | None
    #: Per-modality signal strengths behind the confidence figure.
    signals: dict[str, float] = Field(default_factory=dict)
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradictory_evidence_ids: list[UUID] = Field(default_factory=list)
    independent_source_groups: int = 0
    created_at: datetime | None
    updated_at: datetime | None


class CaseGraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: UUID
    type: str
    label: str
    normalized_form: str
    confidence: float
    first_seen: datetime | None
    last_seen: datetime | None
    #: Degree in this case's subgraph — the "how central is this" number the
    #: node inspector needs, computed here rather than in the browser.
    degree: int
    modality: str | None = None
    evidence_count: int = 0


class CaseGraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    relationship_id: UUID
    source: UUID
    target: UUID
    type: str
    confidence: float
    first_seen: datetime
    last_seen: datetime
    evidence_ids: list[UUID]


class CaseGraph(BaseModel):
    """Nodes and edges for one case, with the per-node aggregates resolved.

    Returning a pre-joined graph means the network view does one request
    instead of three and cannot render a node whose statistics it never
    fetched.
    """

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    nodes: list[CaseGraphNode]
    edges: list[CaseGraphEdge]
    #: Counts of edges by relationship type, for the edge-type filter.
    edge_types: dict[str, int]
    #: Counts of nodes by entity type, for the type filter.
    node_types: dict[str, int]


# --------------------------------------------------------------------------
# Administration
# --------------------------------------------------------------------------


class TeamMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str
    display_name: str
    role: str
    permissions: list[str]
    is_active: bool
    last_login_at: datetime | None
    #: Open cases assigned to this analyst, so the team view shows load.
    assigned_cases: int


class TeamResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    members: list[TeamMember]
    roles: list[str]


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    occurred_at: datetime
    action: str
    actor: str | None
    entity_type: str | None
    entity_id: str | None
    case_id: UUID | None
    case_name: str | None
    payload: dict[str, Any]
    entry_hash: str
    prev_hash: str | None


class AuditTrailResponse(BaseModel):
    """The audit tail plus its integrity verdict.

    ``chain_valid`` is computed by recomputing every hash, not by trusting the
    rows. An operator asking "is my audit log trustworthy" needs the answer to
    be derived, not asserted.
    """

    model_config = ConfigDict(frozen=True)

    entries: list[AuditEntry]
    total: int
    chain_valid: bool
    actions: list[str]


class SystemHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_status: str
    database_status: str
    environment: str
    auth_mode: str
    auth_session_ttl_s: int
    live_socket: str
    counts: PlatformCounts
    metrics: dict[str, Any]
    chain_valid: bool
    #: Advisory only — a missing optional adapter is not an outage.
    adapters: dict[str, str]


class ModelRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    model_id: str
    model_version: str
    dataset_version: str
    feature_version: str
    status: str
    seed: int
    started_at: datetime | None
    finished_at: datetime | None
    metrics: dict[str, Any]


class ModelRegistryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    runs: list[ModelRunSummary]
    total: int
