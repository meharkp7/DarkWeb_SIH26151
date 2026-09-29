"""Derived dashboard analytics for the command center."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis.db.models import AssessmentRecord, AuditLogRecord, CaseRecord, EvidenceRecord


def evidence_velocity(db: Session, *, months: int = 6) -> list[dict[str, object]]:
    """Monthly evidence ingestion counts (most recent month last)."""
    now = datetime.now(UTC)
    start = now - timedelta(days=months * 31)
    rows = db.execute(
        select(
            func.date_trunc("month", EvidenceRecord.collected_at).label("bucket"),
            func.count(),
        )
        .where(EvidenceRecord.collected_at >= start)
        .group_by("bucket")
        .order_by("bucket")
    ).all()
    by_month: dict[str, int] = {}
    for bucket, total in rows:
        label = bucket.strftime("%b %Y") if bucket is not None else "unknown"
        by_month[label] = int(total)
    # Ensure a continuous window even when some months are empty.
    series: list[dict[str, object]] = []
    cursor = datetime(start.year, start.month, 1, tzinfo=UTC)
    for _ in range(months):
        label = cursor.strftime("%b %Y")
        series.append({"label": label, "count": by_month.get(label, 0)})
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=UTC)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=UTC)
    return series[-months:]


def investigation_pressure(db: Session) -> list[dict[str, object]]:
    """Platform-wide pressure indicators (0–100) feeding the priority queue."""
    evidence_7d = int(
        db.scalar(
            select(func.count())
            .select_from(EvidenceRecord)
            .where(EvidenceRecord.collected_at >= datetime.now(UTC) - timedelta(days=7))
        )
        or 0
    )
    relationships_7d = int(
        db.scalar(select(func.count()).select_from(AuditLogRecord).where(
            AuditLogRecord.action == "relationship.updated",
            AuditLogRecord.occurred_at >= datetime.now(UTC) - timedelta(days=7),
        ))
        or 0
    )
    contradictions = sum(
        1
        for row in db.scalars(select(AssessmentRecord.contradictory_evidence_ids)).all()
        if row and len(row) > 0
    )
    overdue_cases = int(
        db.scalar(
            select(func.count())
            .select_from(CaseRecord)
            .where(
                CaseRecord.sla_due_at.is_not(None),
                CaseRecord.sla_due_at < datetime.now(UTC),
                CaseRecord.status.not_in(["closed", "archived"]),
            )
        )
        or 0
    )
    infra_events = int(
        db.scalar(
            select(func.count())
            .select_from(AuditLogRecord)
            .where(AuditLogRecord.action.in_(["entity.extracted", "relationship.updated"]))
        )
        or 0
    )

    def scale(value: int, cap: int) -> int:
        return min(100, int(round(100 * value / cap))) if cap else 0

    return [
        {"key": "evidence_velocity", "label": "Evidence velocity", "score": scale(evidence_7d, 800)},
        {"key": "relationship_growth", "label": "Relationship growth", "score": scale(relationships_7d, 120)},
        {"key": "novel_infrastructure", "label": "Novel infrastructure", "score": scale(infra_events, 2000)},
        {"key": "contradictions", "label": "Contradictions", "score": scale(contradictions, 80)},
        {"key": "sla_exposure", "label": "SLA exposure", "score": scale(overdue_cases, 8)},
    ]


def attribution_posture(db: Session) -> list[dict[str, object]]:
    """Top attribution posture rows — one leading assessment per active case."""
    cases = db.scalars(
        select(CaseRecord)
        .where(CaseRecord.status.in_(["open", "active", "on_hold"]))
        .order_by(CaseRecord.priority.desc(), CaseRecord.updated_at.desc())
        .limit(8)
    ).all()
    rows: list[dict[str, object]] = []
    for case in cases:
        assessment = db.scalar(
            select(AssessmentRecord)
            .where(AssessmentRecord.case_id == case.case_id)
            .order_by(AssessmentRecord.calibrated_confidence.desc().nullslast())
            .limit(1)
        )
        if assessment is None:
            continue
        signals = assessment.signals_json or {}
        modalities = len([value for value in signals.values() if isinstance(value, (int, float))])
        contradictions = len(assessment.contradictory_evidence_ids or [])
        rows.append(
            {
                "case_id": str(case.case_id),
                "case_name": case.name,
                "confidence": assessment.calibrated_confidence or assessment.raw_score,
                "supporting_signals": len(assessment.supporting_evidence_ids or []),
                "modalities": modalities,
                "contradictions": contradictions,
                "freshness": round(
                    max(signals.values()) if signals else assessment.calibrated_confidence or 0, 3
                ),
                "explanations": list(assessment.explanations or [])[:2],
            }
        )
    return rows


def command_posture(db: Session, case_summaries: list[dict[str, object]]) -> dict[str, int]:
    active = [row for row in case_summaries if row.get("status") in {"open", "active"}]
    critical = sum(1 for row in case_summaries if row.get("priority") == "critical")
    high = sum(1 for row in case_summaries if row.get("priority") == "high")
    sla_at_risk = sum(1 for row in case_summaries if row.get("sla_overdue"))
    unresolved = sum(
        1
        for row in db.scalars(select(AssessmentRecord.contradictory_evidence_ids)).all()
        if row and len(row) > 0
    )
    new_evidence = int(
        db.scalar(
            select(func.count())
            .select_from(EvidenceRecord)
            .where(EvidenceRecord.collected_at >= datetime.now(UTC) - timedelta(days=7))
        )
        or 0
    )
    return {
        "active_investigations": len(active),
        "critical": critical,
        "high": high,
        "sla_at_risk": sla_at_risk,
        "new_evidence": new_evidence,
        "unresolved_links": unresolved,
    }


def case_signal_matrix(db: Session, case_id: Any) -> list[dict[str, object]]:
    """Modal support / contradict / freshness matrix for a case workspace."""
    assessments = db.scalars(
        select(AssessmentRecord).where(AssessmentRecord.case_id == case_id)
    ).all()
    if not assessments:
        return []
    modalities = ["behavioral", "infrastructure", "financial", "stylometry", "temporal"]
    accum: dict[str, list[float]] = defaultdict(list)
    contradict_weight = 0
    for row in assessments:
        contradict_weight += len(row.contradictory_evidence_ids or [])
        for key, value in (row.signals_json or {}).items():
            if isinstance(value, (int, float)):
                accum[key.lower()].append(float(value))
    matrix: list[dict[str, object]] = []
    for modality in modalities:
        values = accum.get(modality, accum.get(modality.replace("stylometry", "linguistic"), []))
        support = sum(values) / len(values) if values else 0.55
        freshness = min(0.99, support + 0.08)
        contradict = min(0.85, contradict_weight / max(len(assessments), 1) * 0.12)
        matrix.append(
            {
                "modality": modality.title(),
                "support": _band(support),
                "contradict": _band(contradict),
                "freshness": round(freshness * 100),
            }
        )
    return matrix


def _band(value: float) -> str:
    if value >= 0.72:
        return "HIGH"
    if value >= 0.48:
        return "MEDIUM"
    return "LOW"


def case_timeline_layers(db: Session, case_id: Any, *, limit: int = 80) -> dict[str, object]:
    """Three-layer timeline derived from audit + evidence timestamps."""
    audit = db.scalars(
        select(AuditLogRecord)
        .where(AuditLogRecord.case_id == case_id)
        .order_by(AuditLogRecord.occurred_at.desc())
        .limit(limit)
    ).all()
    evidence = db.scalars(
        select(EvidenceRecord)
        .where(EvidenceRecord.case_id == case_id)
        .order_by(EvidenceRecord.collected_at.desc())
        .limit(limit)
    ).all()

    def pack_event(
        *,
        occurred_at: datetime,
        title: str,
        layer: str,
        evidence_id: str | None = None,
        confidence: float | None = None,
    ) -> dict[str, object]:
        return {
            "occurred_at": occurred_at.isoformat(),
            "title": title,
            "layer": layer,
            "evidence_id": evidence_id,
            "confidence": confidence,
        }

    events: list[dict[str, object]] = []
    for row in audit:
        message = str((row.payload_json or {}).get("message", row.action.replace(".", " ")))
        layer = "event"
        if "relationship" in row.action:
            layer = "infrastructure"
        elif "evidence" in row.action:
            layer = "financial" if "fund" in message.lower() else "event"
        elif "assessment" in row.action or "attribution" in row.action:
            layer = "actor"
        events.append(
            pack_event(occurred_at=row.occurred_at, title=message, layer=layer)
        )
    for row in evidence[: min(24, len(evidence))]:
        title = str((row.metadata_json or {}).get("title", "Evidence ingested"))
        events.append(
            pack_event(
                occurred_at=row.collected_at,
                title=title,
                layer="event",
                evidence_id=str(row.evidence_id),
                confidence=row.source_reliability,
            )
        )
    events.sort(key=lambda item: str(item["occurred_at"]), reverse=True)
    return {
        "events": events[:limit],
        "layers": ["event", "actor", "infrastructure", "financial"],
    }
