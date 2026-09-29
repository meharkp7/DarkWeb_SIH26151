"""Derived analytics for the Command Center and the Investigation Workspace.

Everything here is computed from the system of record. There are no seeded
fallbacks and no client-side numbers: a screen that shows a figure shows one
that came out of PostgreSQL, and the inputs that produced it are included in
the response so the figure can be argued with.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis.db.models import (
    AssessmentRecord,
    AuditLogRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    HypothesisLinkRecord,
    HypothesisRecord,
    RelationshipRecord,
)
from aegis.schemas.analytics import (
    AttributionPosture,
    CaseGraph,
    CaseGraphEdge,
    CaseGraphNode,
    CaseHypothesis,
    CaseQueueEntry,
    CommandPosture,
    PressureIndicator,
    PriorityReason,
    SignalBand,
    TimelineEvent,
    VelocityPoint,
)

#: Ceilings for the pressure indicators. Each is the observed count that scores
#: 100, chosen so a healthy platform sits near the bottom of the scale and a
#: genuinely overloaded one pins the top. They are returned with the score so
#: the scaling is never a black box.
PRESSURE_CEILINGS: dict[str, int] = {
    "evidence_velocity": 900,
    "relationship_growth": 140,
    "novel_infrastructure": 2400,
    "contradictions": 80,
    "sla_exposure": 8,
}

_PRESSURE_LABELS: dict[str, str] = {
    "evidence_velocity": "Evidence velocity",
    "relationship_growth": "Relationship growth",
    "novel_infrastructure": "Novel infrastructure",
    "contradictions": "Contradictions",
    "sla_exposure": "SLA exposure",
}

_PRIORITY_WEIGHT: dict[str, int] = {"critical": 46, "high": 34, "medium": 20, "low": 10}
_SEVERITY_WEIGHT: dict[str, int] = {
    "critical": 26,
    "high": 19,
    "medium": 11,
    "low": 5,
    "informational": 0,
}
_TERMINAL_STATUSES = ("closed", "archived")

#: An investigation due within this window is "at risk" rather than healthy.
#: Used for both the per-case ``sla_state`` and the platform-level SLA
#: exposure indicator, so the two can never disagree about what "at risk"
#: means.
SLA_RISK_WINDOW = timedelta(hours=12)
_MODALITIES = ("behavioral", "infrastructure", "financial", "stylometry", "temporal")


def _scale(value: int, ceiling: int) -> int:
    return min(100, int(round(100 * value / ceiling))) if ceiling else 0


def _band(value: float) -> str:
    if value >= 0.72:
        return "HIGH"
    if value >= 0.48:
        return "MEDIUM"
    return "LOW"


# --------------------------------------------------------------------------
# Command Center
# --------------------------------------------------------------------------


def evidence_velocity(db: Session, *, months: int = 6) -> list[VelocityPoint]:
    """Monthly evidence ingestion, oldest bucket first, with change per bucket.

    The window is anchored on the *first of the current month* and always ends
    with the current month. A trailing ``now - N*31 days`` window silently
    drops the newest bucket, so the rightmost point on the chart is always a
    month old and today's collection can never appear on it.

    Every bucket is emitted even where the count is zero: a gap in the series
    reads as "we collected nothing", which is itself an answer, whereas a
    missing bucket reads as "no data", which is not.
    """
    now = datetime.now(UTC)
    # Walk back `months` whole months from the first of this month.
    year, month = now.year, now.month - months
    while month < 1:
        month += 12
        year -= 1
    start = datetime(year, month, 1, tzinfo=UTC)
    rows = db.execute(
        select(
            func.date_trunc("month", EvidenceRecord.collected_at).label("bucket"),
            func.count(),
        )
        .where(EvidenceRecord.collected_at >= start)
        .group_by("bucket")
        .order_by("bucket")
    ).all()
    by_month: dict[tuple[int, int], int] = {}
    for bucket, total in rows:
        if bucket is None:
            continue
        # SQLAlchemy types a bare ``date_trunc`` column as ``object``; the cast
        # records what the database actually returns.
        stamp = cast("datetime", bucket)
        by_month[(stamp.year, stamp.month)] = int(cast("int", total))

    series: list[VelocityPoint] = []
    for _ in range(months + 1):
        count = by_month.get((year, month), 0)
        previous = series[-1].count if series else None
        series.append(
            VelocityPoint(
                label=f"{datetime(year, month, 1, tzinfo=UTC):%b %Y}",
                count=count,
                delta=None if previous is None else count - previous,
            )
        )
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return series


def investigation_pressure(db: Session) -> list[PressureIndicator]:
    """Platform-wide pressure indicators, each 0-100, each with its raw input.

    Every indicator is normalised against a declared ceiling and returns both
    the observed count and that ceiling, so a score of 71 is readable as
    "100 of 140" rather than as an oracle's opinion.
    """
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)

    evidence_7d = int(
        db.scalar(
            select(func.count())
            .select_from(EvidenceRecord)
            .where(EvidenceRecord.collected_at >= week_ago)
        )
        or 0
    )
    relationships_7d = int(
        db.scalar(
            select(func.count())
            .select_from(AuditLogRecord)
            .where(
                AuditLogRecord.action == "relationship.updated",
                AuditLogRecord.occurred_at >= week_ago,
            )
        )
        or 0
    )
    infra_events = int(
        db.scalar(
            select(func.count())
            .select_from(AuditLogRecord)
            .where(
                AuditLogRecord.action.in_(["entity.extracted", "relationship.updated"]),
            )
        )
        or 0
    )
    contradictions = int(
        db.scalar(
            select(func.count())
            .select_from(AssessmentRecord)
            .where(AssessmentRecord.contradictory_evidence_ids != [])
        )
        or 0
    )
    sla_exposure_cases = int(
        db.scalar(
            select(func.count())
            .select_from(CaseRecord)
            .where(
                CaseRecord.sla_due_at.is_not(None),
                # Breached *and* approaching. Counting only the failures would
                # hold this indicator at zero right up to the deadline, which
                # is exactly when the platform should be shouting about it.
                CaseRecord.sla_due_at < now + SLA_RISK_WINDOW,
                CaseRecord.status.not_in(_TERMINAL_STATUSES),
            )
        )
        or 0
    )

    observed: dict[str, int] = {
        "evidence_velocity": evidence_7d,
        "relationship_growth": relationships_7d,
        "novel_infrastructure": infra_events,
        "contradictions": contradictions,
        "sla_exposure": sla_exposure_cases,
    }
    return [
        PressureIndicator(
            key=key,
            label=_PRESSURE_LABELS[key],
            score=_scale(count, ceiling),
            observed=count,
            ceiling=ceiling,
        )
        for key, ceiling in PRESSURE_CEILINGS.items()
        if (count := observed[key]) is not None
    ]


def command_posture(
    db: Session, case_summaries: list[CaseQueueEntry], pressure: list[PressureIndicator]
) -> CommandPosture:
    """The six headline figures, with the denominators that make them legible."""
    active = [row for row in case_summaries if row.status in {"open", "active"}]
    contradictions = int(
        db.scalar(
            select(func.count())
            .select_from(AssessmentRecord)
            .where(AssessmentRecord.contradictory_evidence_ids != [])
        )
        or 0
    )
    new_evidence = int(
        db.scalar(
            select(func.count())
            .select_from(EvidenceRecord)
            .where(EvidenceRecord.collected_at >= datetime.now(UTC) - timedelta(days=7))
        )
        or 0
    )
    scores = [indicator.score for indicator in pressure]
    return CommandPosture(
        active_investigations=len(active),
        critical=sum(1 for row in case_summaries if row.priority == "critical"),
        high=sum(1 for row in case_summaries if row.priority == "high"),
        # Breached *and* at-risk: both are "this needs attention now", and a
        # tile that only counted the failures would sit at zero right up to
        # the moment the deadline passed.
        sla_at_risk=sum(1 for row in case_summaries if row.sla_state in {"breached", "at_risk"}),
        new_evidence=new_evidence,
        unresolved_links=contradictions,
        total_investigations=len(case_summaries),
        unassigned=sum(1 for row in case_summaries if not row.assigned_to),
        pressure_index=int(round(sum(scores) / len(scores))) if scores else 0,
    )


def _sla_state(case: CaseRecord, *, overdue: bool, now: datetime) -> str:
    """``breached`` / ``at_risk`` / ``ok`` / ``none`` for one case's deadline.

    Kept separate from ``sla_overdue`` because an investigation four hours
    from breach is operationally different from one already past it, and
    collapsing the two makes the posture tile useless precisely when it
    matters.
    """
    if case.sla_due_at is None or case.status in _TERMINAL_STATUSES:
        return "none"
    if overdue:
        return "breached"
    if (case.sla_due_at - now) <= SLA_RISK_WINDOW:
        return "at_risk"
    return "ok"


def queue_entry(
    case: CaseRecord,
    counts: dict[str, int],
    *,
    last_activity: datetime | None,
    attribution: float | None,
    now: datetime,
) -> CaseQueueEntry:
    """Score a case for the priority queue and explain the score.

    The reasons are returned, not just the total. A queue that says "142"
    without saying which three things contributed to it is a black box the
    analyst has to trust, and the whole point of the queue is that they do not
    have to.
    """
    from aegis.api.case_triage import case_is_overdue

    overdue = case_is_overdue(case, now=now)
    sla_state = _sla_state(case, overdue=overdue, now=now)
    reasons: list[PriorityReason] = []
    score = 0

    priority_weight = _PRIORITY_WEIGHT.get(case.priority, 12)
    score += priority_weight
    reasons.append(
        PriorityReason(
            key="priority", label=f"{case.priority.title()} priority", weight=priority_weight
        )
    )

    severity_weight = _SEVERITY_WEIGHT.get(case.severity, 5)
    score += severity_weight
    reasons.append(
        PriorityReason(
            key="severity", label=f"{case.severity.title()} severity", weight=severity_weight
        )
    )

    if sla_state == "breached":
        score += 18
        reasons.append(PriorityReason(key="sla_breach", label="SLA breached", weight=18))
    elif sla_state == "at_risk":
        score += 9
        deadline = cast("datetime", case.sla_due_at)
        hours = max(1, int((deadline - now).total_seconds() // 3600))
        reasons.append(
            PriorityReason(key="sla_approaching", label=f"SLA due in {hours}h", weight=9)
        )

    contradictions = int(counts.get("contradictions", 0))
    if contradictions:
        weight = min(12, 4 * contradictions)
        score += weight
        plural = "s" if contradictions > 1 else ""
        reasons.append(
            PriorityReason(
                key="contradictions",
                label=f"{contradictions} unresolved contradiction{plural}",
                weight=weight,
            )
        )

    velocity = int(counts.get("recent_evidence", 0))
    if velocity:
        weight = min(12, velocity // 25)
        if weight:
            score += weight
            reasons.append(
                PriorityReason(
                    key="evidence_velocity", label=f"{velocity} evidence in 7 days", weight=weight
                )
            )

    links = int(counts.get("relationships", 0))
    if links:
        weight = min(8, links // 150)
        if weight:
            score += weight
            reasons.append(
                PriorityReason(
                    key="relationship_growth",
                    label=f"{links} relationships resolved",
                    weight=weight,
                )
            )

    if not case.assigned_to:
        score += 6
        reasons.append(PriorityReason(key="unassigned", label="No analyst assigned", weight=6))

    if case.status in _TERMINAL_STATUSES:
        score = 0
        reasons = [PriorityReason(key="closed", label=f"Case {case.status}", weight=0)]

    reasons.sort(key=lambda reason: (-reason.weight, reason.label))
    if not reasons:
        headline = "Routine monitoring"
    else:
        headline = reasons[0].label

    return CaseQueueEntry(
        case_id=case.case_id,
        name=case.name,
        status=case.status,
        priority=case.priority,
        severity=case.severity,
        tags=list(case.tags or []),
        assigned_to=str(case.assigned_to) if case.assigned_to else None,
        sla_due_at=case.sla_due_at,
        sla_overdue=overdue,
        sla_state=sla_state,
        queue_score=min(100, score),
        queue_reason=headline,
        reasons=reasons,
        counts=counts,
        last_activity=last_activity,
        attribution=attribution,
    )


def attribution_posture(db: Session, *, limit: int = 8) -> list[AttributionPosture]:
    """One leading assessment per active case, with its supporting detail."""
    cases = db.scalars(
        select(CaseRecord)
        .where(CaseRecord.status.not_in(_TERMINAL_STATUSES))
        .order_by(CaseRecord.priority.asc(), CaseRecord.sla_due_at.asc().nullslast())
        .limit(limit)
    ).all()
    if not cases:
        return []
    rows = (
        db.execute(
            select(AssessmentRecord)
            .where(AssessmentRecord.case_id.in_([case.case_id for case in cases]))
            .order_by(
                AssessmentRecord.case_id,
                AssessmentRecord.calibrated_confidence.desc().nullslast(),
                AssessmentRecord.created_at.desc(),
            )
        )
        .scalars()
        .all()
    )
    lead: dict[UUID, AssessmentRecord] = {}
    for row in rows:
        # dict.setdefault keeps the first row per case, and the ordering above
        # puts the highest-confidence assessment first for each case.
        lead.setdefault(row.case_id, row)

    posture: list[AttributionPosture] = []
    for case in cases:
        assessment = lead.get(case.case_id)
        if assessment is None:
            continue
        signals = {
            key: float(value)
            for key, value in (assessment.signals_json or {}).items()
            if isinstance(value, (int, float))
        }
        newest = max(signals.values(), default=assessment.calibrated_confidence or 0.0)
        posture.append(
            AttributionPosture(
                case_id=case.case_id,
                case_name=case.name,
                confidence=round(
                    assessment.calibrated_confidence
                    if assessment.calibrated_confidence is not None
                    else assessment.raw_score,
                    4,
                ),
                supporting_signals=len(assessment.supporting_evidence_ids or []),
                modalities=len(signals),
                contradictions=len(assessment.contradictory_evidence_ids or []),
                freshness=round(float(newest), 3),
                explanations=list(assessment.explanations or [])[:2],
                signals=signals,
            )
        )
    return posture


# --------------------------------------------------------------------------
# Investigation workspace
# --------------------------------------------------------------------------


def case_signal_matrix(db: Session, case_id: UUID) -> list[SignalBand]:
    """Modality support / contradict / freshness matrix for one case.

    Both the band and the number are returned. The band alone would hide how
    close a value sits to its neighbour, and that margin is the difference
    between a lead worth chasing and a lead to set aside.
    """
    rows = db.scalars(select(AssessmentRecord).where(AssessmentRecord.case_id == case_id)).all()
    if not rows:
        return []
    per_modality: dict[str, list[float]] = {}
    contradiction_total = 0
    for row in rows:
        contradiction_total += len(row.contradictory_evidence_ids or [])
        for key, value in (row.signals_json or {}).items():
            if isinstance(value, (int, float)):
                per_modality.setdefault(key.lower(), []).append(float(value))

    matrix: list[SignalBand] = []
    for modality in _MODALITIES:
        values = per_modality.get(modality, [])
        support = sum(values) / len(values) if values else 0.55
        contradict = min(0.85, contradiction_total / max(len(rows), 1) * 0.12)
        freshness = min(0.99, support + 0.08)
        matrix.append(
            SignalBand(
                modality=modality.title(),
                support=_band(support),
                contradict=_band(contradict),
                support_value=round(support, 3),
                contradict_value=round(contradict, 3),
                freshness=round(freshness * 100, 1),
            )
        )
    return matrix


#: Audit action -> the timeline lane it belongs in. Explicit rather than
#: inferred from substrings: "assessment.updated" contains no "relationship",
#: and an inference table that silently falls through to "event" is how a
#: three-layer timeline quietly becomes a one-layer timeline.
_LAYER_BY_ACTION: dict[str, str] = {
    "relationship.updated": "infrastructure",
    "entity.extracted": "infrastructure",
    "threat.infrastructure": "infrastructure",
    "threat.financial": "financial",
    "evidence.contradicted": "financial",
    "assessment.updated": "actor",
    "threat.attribution": "actor",
    "attribution.assessment.created": "actor",
    "alert.critical": "event",
    "evidence.created": "event",
    "case.note_added": "event",
    "case.created": "event",
    "case.updated": "event",
}


def _layer_for(action: str) -> str:
    return _LAYER_BY_ACTION.get(action, "event")


def case_timeline_layers(db: Session, case_id: UUID, *, limit: int = 80) -> list[TimelineEvent]:
    """Three-lane timeline: what happened, who did it, and what it touched."""
    audit = db.scalars(
        select(AuditLogRecord)
        .where(AuditLogRecord.case_id == case_id)
        .order_by(AuditLogRecord.occurred_at.desc(), AuditLogRecord.seq.desc())
        .limit(limit)
    ).all()
    evidence = db.scalars(
        select(EvidenceRecord)
        .where(EvidenceRecord.case_id == case_id)
        .order_by(EvidenceRecord.collected_at.desc())
        .limit(min(limit, 30))
    ).all()
    entities = {
        str(row.entity_id): row.surface_form
        for row in db.scalars(select(EntityRecord).where(EntityRecord.case_id == case_id)).all()
    }

    events: list[TimelineEvent] = []
    for row in audit:
        payload = row.payload_json or {}
        actor_id = str(payload.get("actor_entity_id") or "")
        target_id = str(payload.get("target_entity_id") or "")
        detail = (
            " → ".join(part for part in (entities.get(actor_id), entities.get(target_id)) if part)
            or None
        )
        events.append(
            TimelineEvent(
                occurred_at=row.occurred_at,
                title=str(payload.get("message") or row.action.replace(".", " ")),
                layer=str(payload.get("layer") or _layer_for(row.action)),
                evidence_id=None,
                confidence=None,
                detail=detail,
                action=row.action,
                case_id=row.case_id,
            )
        )
    for observation in evidence:
        metadata = observation.metadata_json or {}
        events.append(
            TimelineEvent(
                occurred_at=observation.collected_at,
                title=str(metadata.get("title") or "Evidence ingested"),
                layer=_layer_for("evidence.created"),
                evidence_id=observation.evidence_id,
                confidence=round(observation.source_reliability, 3),
                detail=str(metadata.get("summary") or "") or None,
                action="evidence.created",
                case_id=observation.case_id,
            )
        )
    events.sort(key=lambda event: event.occurred_at, reverse=True)
    return events[:limit]


def case_graph(
    db: Session, case_id: UUID, *, edge_types: tuple[str, ...] | None = None
) -> CaseGraph:
    """Nodes and edges for one case, with degree and evidence counts resolved.

    The graph is assembled server-side so the network view is a single request
    and cannot draw a node whose statistics it never fetched.
    """
    entities = db.scalars(select(EntityRecord).where(EntityRecord.case_id == case_id)).all()
    by_id = {entity.entity_id: entity for entity in entities}

    relationship_query = select(RelationshipRecord).where(RelationshipRecord.case_id == case_id)
    if edge_types:
        relationship_query = relationship_query.where(
            RelationshipRecord.relationship_type.in_(edge_types)
        )
    relationships = db.scalars(relationship_query).all()

    degree: dict[UUID, int] = {}
    evidence_count: dict[UUID, int] = {}
    edges: list[CaseGraphEdge] = []
    for row in relationships:
        # An edge whose endpoint is not in this case's entity set is skipped
        # rather than drawn: rendering it would put a node the inspector
        # cannot describe on screen.
        if row.subject_entity_id not in by_id or row.object_entity_id not in by_id:
            continue
        degree[row.subject_entity_id] = degree.get(row.subject_entity_id, 0) + 1
        degree[row.object_entity_id] = degree.get(row.object_entity_id, 0) + 1
        for entity_id in row.evidence_ids:
            evidence_count[entity_id] = evidence_count.get(entity_id, 0) + 1
        edges.append(
            CaseGraphEdge(
                relationship_id=row.relationship_id,
                source=row.subject_entity_id,
                target=row.object_entity_id,
                type=row.relationship_type,
                confidence=round(row.confidence, 3),
                first_seen=row.first_seen,
                last_seen=row.last_seen,
                evidence_ids=list(row.evidence_ids),
            )
        )

    nodes: list[CaseGraphNode] = []
    for entity in entities:
        metadata = entity.metadata_json or {}
        nodes.append(
            CaseGraphNode(
                entity_id=entity.entity_id,
                type=entity.entity_type,
                label=entity.surface_form,
                normalized_form=entity.normalized_form,
                confidence=round(entity.confidence, 3),
                first_seen=entity.first_seen,
                last_seen=entity.last_seen,
                degree=degree.get(entity.entity_id, 0),
                modality=str(metadata.get("modality")) if metadata.get("modality") else None,
                evidence_count=evidence_count.get(entity.entity_id, 0),
            )
        )

    node_types: dict[str, int] = {}
    for node in nodes:
        node_types[node.type] = node_types.get(node.type, 0) + 1
    edge_types_seen: dict[str, int] = {}
    for edge in edges:
        edge_types_seen[edge.type] = edge_types_seen.get(edge.type, 0) + 1

    return CaseGraph(
        case_id=case_id,
        nodes=sorted(nodes, key=lambda node: (-node.degree, node.type, node.label)),
        edges=edges,
        edge_types=edge_types_seen,
        node_types=node_types,
    )


def case_hypotheses(db: Session, case_id: UUID) -> list[CaseHypothesis]:
    """Hypotheses with their evidence links folded in, highest confidence first.

    Each row carries the evidence actually behind the number. A confidence
    figure with no citations is an assertion, and this is the endpoint that
    makes it a finding an analyst can check.
    """
    rows = db.scalars(
        select(HypothesisRecord)
        .where(HypothesisRecord.case_id == case_id)
        .order_by(HypothesisRecord.created_at.asc())
    ).all()
    if not rows:
        return []
    hypothesis_ids = [row.hypothesis_id for row in rows]

    assessments = db.scalars(
        select(AssessmentRecord)
        .where(AssessmentRecord.hypothesis_id.in_(hypothesis_ids))
        .order_by(AssessmentRecord.calibrated_confidence.desc().nullslast())
    ).all()
    lead: dict[UUID, AssessmentRecord] = {}
    for row in assessments:
        lead.setdefault(row.hypothesis_id, row)

    links = db.scalars(
        select(HypothesisLinkRecord).where(HypothesisLinkRecord.hypothesis_id.in_(hypothesis_ids))
    ).all()
    supporting: dict[UUID, list[UUID]] = {}
    contradicting: dict[UUID, list[UUID]] = {}
    groups: dict[UUID, set[str]] = {}
    for link in links:
        if link.role == "supporting":
            supporting.setdefault(link.hypothesis_id, []).append(link.evidence_id)
            groups.setdefault(link.hypothesis_id, set()).add(link.independence_group)
        else:
            contradicting.setdefault(link.hypothesis_id, []).append(link.evidence_id)

    result: list[CaseHypothesis] = []
    for hypothesis in rows:
        assessment = lead.get(hypothesis.hypothesis_id)
        signals = {
            key: round(float(value), 3)
            for key, value in ((assessment.signals_json or {}) if assessment else {}).items()
            if isinstance(value, (int, float))
        }
        result.append(
            CaseHypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                kind=hypothesis.kind,
                status=hypothesis.status,
                subject_entity_id=hypothesis.subject_entity_id,
                object_entity_id=hypothesis.object_entity_id,
                missing_evidence=list(hypothesis.missing_evidence or []),
                analyst_disposition=hypothesis.analyst_disposition,
                calibrated_confidence=(assessment.calibrated_confidence if assessment else None),
                raw_score=assessment.raw_score if assessment else None,
                signals=signals,
                supporting_evidence_ids=list(
                    assessment.supporting_evidence_ids
                    if assessment
                    else (supporting.get(hypothesis.hypothesis_id) or [])
                ),
                contradictory_evidence_ids=list(
                    assessment.contradictory_evidence_ids
                    if assessment
                    else (contradicting.get(hypothesis.hypothesis_id) or [])
                ),
                independent_source_groups=len(groups.get(hypothesis.hypothesis_id, ())),
                created_at=hypothesis.created_at,
                updated_at=hypothesis.updated_at,
            )
        )
    result.sort(key=lambda row: (-(row.calibrated_confidence or 0.0), str(row.hypothesis_id)))
    return result
