"""Case-workspace read APIs for the investigation UI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, delete, func, select
from sqlalchemy.orm import Session

from aegis.api.case_triage import case_is_overdue
from aegis.api.dashboard_analytics import (
    case_graph,
    case_hypotheses,
    case_signal_matrix,
    case_timeline_layers,
    hypothesis_comparison,
)
from aegis.api.deps import get_db
from aegis.db.audit import AuditService
from aegis.db.models import (
    AssessmentRecord,
    AuditLogRecord,
    CaseNoteRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    HypothesisLinkRecord,
    HypothesisRecord,
    RelationshipRecord,
)
from aegis.schemas.analytics import (
    CaseGraph,
    CaseHypothesis,
    CaseMetrics,
    CaseTimeline,
    HypothesisComparison,
    RecordLinkageRequest,
    RecordLinkageResponse,
    SignalBand,
)
from aegis.schemas.evidence import CaseNote, CaseNoteCreate
from aegis.schemas.workspace import WorkspaceResponse

router = APIRouter(prefix="/api/v1/cases", tags=["workspace"])


def _case_or_404(db: Session, case_id: UUID) -> CaseRecord:
    case = db.get(CaseRecord, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def _note_schema(record: CaseNoteRecord) -> CaseNote:
    return CaseNote(
        note_id=record.note_id,
        case_id=record.case_id,
        author_id=record.author_id,
        body=record.body,
        created_at=record.created_at,
    )


@router.get("/{case_id}/workspace", response_model=WorkspaceResponse)
def workspace(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    case = _case_or_404(db, case_id)
    evidence = db.scalars(select(EvidenceRecord).where(EvidenceRecord.case_id == case_id)).all()
    entities = db.scalars(select(EntityRecord).where(EntityRecord.case_id == case_id)).all()
    relationships = db.scalars(
        select(RelationshipRecord).where(RelationshipRecord.case_id == case_id)
    ).all()
    assessments = db.scalars(
        select(AssessmentRecord).where(AssessmentRecord.case_id == case_id)
    ).all()
    activity = db.scalars(
        select(AuditLogRecord)
        .where(AuditLogRecord.case_id == case_id)
        .order_by(AuditLogRecord.seq.desc())
        .limit(40)
    ).all()
    return {
        "case": {
            "case_id": str(case.case_id),
            "name": case.name,
            "description": case.description,
            "status": case.status,
            "priority": case.priority,
            "severity": case.severity,
            "tags": list(case.tags or []),
            "assigned_to": str(case.assigned_to) if case.assigned_to else None,
            "sla_due_at": case.sla_due_at.isoformat() if case.sla_due_at else None,
            "closed_at": case.closed_at.isoformat() if case.closed_at else None,
            "closure_reason": case.closure_reason,
            "sla_overdue": case_is_overdue(case),
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        },
        "counts": {
            "evidence": len(evidence),
            "entities": len(entities),
            "relationships": len(relationships),
            "assessments": len(assessments),
        },
        "evidence": [
            {
                "evidence_id": str(row.evidence_id),
                "source_id": str(row.source_id),
                "source_type": row.source_type,
                "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                "collected_at": row.collected_at.isoformat(),
                "entity_type": row.entity_type,
                "reliability": row.source_reliability,
                # Independence is what later stages use to discount corroborating
                # "sources" that are the same source; the workspace needs it
                # alongside reliability or a confidence reading is uninterpretable.
                "independence_group": row.independence_group,
                "sha256": row.sha256,
                "metadata": row.metadata_json,
            }
            for row in sorted(evidence, key=lambda item: item.collected_at)
        ],
        "entities": [
            {
                "entity_id": str(row.entity_id),
                "type": row.entity_type,
                "surface_form": row.surface_form,
                "normalized_form": row.normalized_form,
                "confidence": row.confidence,
            }
            for row in entities
        ],
        "relationships": [
            {
                "relationship_id": str(row.relationship_id),
                "subject_entity_id": str(row.subject_entity_id),
                "object_entity_id": str(row.object_entity_id),
                "type": row.relationship_type,
                "confidence": row.confidence,
                "first_seen": row.first_seen.isoformat(),
                "last_seen": row.last_seen.isoformat(),
                "evidence_ids": [str(value) for value in row.evidence_ids],
            }
            for row in relationships
        ],
        "assessments": [
            {
                "assessment_id": str(row.assessment_id),
                "hypothesis_id": str(row.hypothesis_id),
                "model_id": row.model_id,
                "model_version": row.model_version,
                "raw_score": row.raw_score,
                "calibrated_confidence": row.calibrated_confidence,
                "signals": row.signals_json,
                "explanations": row.explanations,
                "limitations": row.limitations,
                "supporting_evidence_ids": [str(value) for value in row.supporting_evidence_ids],
                "contradictory_evidence_ids": [
                    str(value) for value in row.contradictory_evidence_ids
                ],
            }
            for row in assessments
        ],
        "activity": [
            {
                "seq": row.seq,
                "occurred_at": row.occurred_at.isoformat(),
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "payload": row.payload_json,
            }
            for row in activity
        ],
    }


@router.get("/{case_id}/hypotheses", response_model=list[CaseHypothesis])
def hypotheses(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> list[CaseHypothesis]:
    """Case-scoped hypotheses with the evidence behind each confidence figure.

    Reads the canonical ``hypotheses`` table, which carries a ``case_id``
    foreign key. The legacy ``attribution_hypotheses`` table has no
    ``case_id`` column at all, so querying it here used to return every
    hypothesis in the database to every case's workspace regardless of the
    path parameter — a cross-case disclosure.
    """
    _case_or_404(db, case_id)
    return case_hypotheses(db, case_id)


@router.get("/{case_id}/notes", response_model=list[CaseNote])
def list_case_notes(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[CaseNote]:
    """Investigative notes, newest first.

    Analyst-authored working commentary, distinct from the immutable
    ``audit_logs`` trail surfaced by ``GET /{case_id}/activity``.
    """
    _case_or_404(db, case_id)
    rows = db.scalars(
        select(CaseNoteRecord)
        .where(CaseNoteRecord.case_id == case_id)
        .order_by(CaseNoteRecord.created_at.desc(), CaseNoteRecord.note_id.desc())
        .limit(limit)
    ).all()
    return [_note_schema(row) for row in rows]


@router.post(
    "/{case_id}/notes",
    response_model=CaseNote,
    status_code=status.HTTP_201_CREATED,
)
def create_case_note(
    case_id: UUID,
    payload: CaseNoteCreate,
    db: Annotated[Session, Depends(get_db)],
) -> CaseNote:
    _case_or_404(db, case_id)
    record = CaseNoteRecord(
        case_id=case_id,
        author_id=payload.author_id,
        body=payload.body.strip(),
    )
    db.add(record)
    db.flush()
    AuditService(db).record(
        "case.note_added",
        case_id=case_id,
        entity_type="case_note",
        entity_id=str(record.note_id),
        payload={"note_id": str(record.note_id), "characters": len(record.body)},
    )
    db.commit()
    db.refresh(record)
    return _note_schema(record)


@router.get("/{case_id}/signals", response_model=list[SignalBand])
def case_signals(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> list[SignalBand]:
    """Per-modality support, contradiction and freshness for one case."""
    _case_or_404(db, case_id)
    return case_signal_matrix(db, case_id)


@router.get("/{case_id}/timeline", response_model=CaseTimeline)
def case_timeline(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 80,
) -> CaseTimeline:
    """Three-lane timeline: what happened, who did it, and what it touched."""
    _case_or_404(db, case_id)
    return CaseTimeline(
        case_id=case_id,
        events=case_timeline_layers(db, case_id, limit=limit),
        layers=["event", "actor", "infrastructure", "financial"],
    )


@router.get("/{case_id}/metrics", response_model=CaseMetrics)
def case_metrics(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> CaseMetrics:
    """The six numbers the workspace header shows.

    ``attribution`` is the *highest* calibrated confidence in the case, not
    whichever assessment the query planner returned first — the previous
    implementation read ``assessments[0]`` off an unordered SELECT, so the
    headline figure was effectively arbitrary.
    """
    case = _case_or_404(db, case_id)
    evidence = db.scalars(select(EvidenceRecord).where(EvidenceRecord.case_id == case_id)).all()
    entities = db.scalars(select(EntityRecord).where(EntityRecord.case_id == case_id)).all()
    relationships = db.scalars(
        select(RelationshipRecord).where(RelationshipRecord.case_id == case_id)
    ).all()
    assessments = db.scalars(
        select(AssessmentRecord).where(AssessmentRecord.case_id == case_id)
    ).all()
    confidences = [
        row.calibrated_confidence for row in assessments if row.calibrated_confidence is not None
    ]
    return CaseMetrics(
        case_id=case.case_id,
        evidence=len(evidence),
        links=len(relationships),
        entities=len(entities),
        sources=len({row.source_id for row in evidence}),
        attribution=round(max(confidences), 4) if confidences else None,
        contradictions=sum(len(row.contradictory_evidence_ids or []) for row in assessments),
        hypotheses=len({row.hypothesis_id for row in assessments}),
        # Independence groups, not source ids: three feeds copying one press
        # release are one source wearing three hats.
        independent_sources=len({row.independence_group for row in evidence}),
    )


@router.get("/{case_id}/evidence")
def case_evidence(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    source_type: str | None = None,
    entity_type: str | None = None,
    independence_group: str | None = None,
    search: str | None = None,
) -> list[dict[str, object]]:
    """The evidence ledger for a case, newest first, with server-side filters.

    Filtering happens here rather than in the browser because a 5,000-row
    ledger is not something to ship over the wire and filter in memory, and
    because the row count the filter returns is part of what the analyst is
    reading.
    """
    _case_or_404(db, case_id)
    query = select(EvidenceRecord).where(EvidenceRecord.case_id == case_id)
    if source_type:
        query = query.where(EvidenceRecord.source_type == source_type)
    if entity_type:
        query = query.where(EvidenceRecord.entity_type == entity_type)
    if independence_group:
        query = query.where(EvidenceRecord.independence_group == independence_group)
    if search:
        # Matched against the JSONB metadata blob rather than a dedicated
        # search index: the ledger filter is a refinement of an
        # already-scoped case, and OpenSearch is a non-authoritative adapter
        # that may not be deployed.
        pattern = f"%{search.strip().lower()}%"
        query = query.where(func.lower(EvidenceRecord.metadata_json.cast(String)).like(pattern))
    rows = db.scalars(query.order_by(EvidenceRecord.collected_at.desc()).limit(limit)).all()
    return [
        {
            "evidence_id": str(row.evidence_id),
            "source_id": str(row.source_id),
            "source_type": row.source_type,
            "observed_at": row.observed_at.isoformat() if row.observed_at else None,
            "collected_at": row.collected_at.isoformat(),
            "entity_type": row.entity_type,
            "reliability": row.source_reliability,
            "independence_group": row.independence_group,
            "sha256": row.sha256,
            "metadata": row.metadata_json,
        }
        for row in rows
    ]


@router.get("/{case_id}/graph", response_model=CaseGraph)
def case_network(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    edge_type: Annotated[list[str] | None, Query()] = None,
    node_type: Annotated[list[str] | None, Query()] = None,
) -> CaseGraph:
    """Nodes and edges for the case network, with per-node aggregates.

    The graph is assembled server-side so the network view is one request,
    and so the node inspector can always describe the node it is showing:
    degree, evidence count and observation window are resolved here rather
    than being absent from the payload and reconstructed in the browser.
    """
    _case_or_404(db, case_id)
    graph = case_graph(db, case_id, edge_types=tuple(edge_type) if edge_type else None)
    if not node_type:
        return graph
    allowed = set(node_type)
    # Filtering nodes implies filtering edges: an edge whose endpoint is
    # hidden must not be drawn, or the network shows lines into nothing.
    kept = {node.entity_id for node in graph.nodes if node.type in allowed}
    return CaseGraph(
        case_id=graph.case_id,
        nodes=[node for node in graph.nodes if node.entity_id in kept],
        edges=[edge for edge in graph.edges if edge.source in kept and edge.target in kept],
        edge_types=graph.edge_types,
        node_types=graph.node_types,
    )


@router.get("/{case_id}/hypotheses/{hypothesis_id}/comparison", response_model=HypothesisComparison)
def hypothesis_comparison_route(
    case_id: UUID,
    hypothesis_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> HypothesisComparison:
    """What agrees with a hypothesis and what does not, per modality.

    A single confidence number hides the shape of the evidence behind it.
    This is the shape: which signals carry the assessment, which pull against
    it, and which are simply not recorded.
    """
    _case_or_404(db, case_id)
    payload = hypothesis_comparison(db, case_id, hypothesis_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found in this case")
    return HypothesisComparison(**payload)  # type: ignore[arg-type]


@router.post(
    "/{case_id}/hypotheses/{hypothesis_id}/record",
    response_model=RecordLinkageResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_linkage(
    case_id: UUID,
    hypothesis_id: UUID,
    payload: RecordLinkageRequest,
    db: Annotated[Session, Depends(get_db)],
) -> RecordLinkageResponse:
    """Record an analyst's ruling on a model association.

    This is the boundary between an estimate and a finding, so it is an
    explicit, cited, attributed and audited act — never a side effect of
    viewing a score. The UI stops calling a figure an estimate only after
    this has happened, which means the transition is visible and reversible
    in the record rather than implied by a number moving.

    The cited evidence must belong to this case. A linkage attributed to
    evidence from a different investigation would not survive a reader
    following the citation, which is the only test of an attribution that
    matters.
    """
    _case_or_404(db, case_id)
    hypothesis = db.get(HypothesisRecord, hypothesis_id)
    if hypothesis is None or hypothesis.case_id != case_id:
        raise HTTPException(status_code=404, detail="Hypothesis not found in this case")

    cited = db.scalars(
        select(EvidenceRecord).where(
            EvidenceRecord.evidence_id.in_(payload.evidence_ids),
            EvidenceRecord.case_id == case_id,
        )
    ).all()
    if len(cited) != len(set(payload.evidence_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Every cited evidence record must belong to this case.",
        )

    role = "supporting" if payload.disposition == "confirmed" else "contradicting"
    # The analyst ruling is a *current position*, not an append-only log —
    # the append-only record is the audit entry written below. Replacing the
    # previous ruling rather than accumulating is what makes re-recording
    # idempotent and makes reversing a decision possible, and it keeps a
    # hypothesis from carrying both "confirmed" and "rejected" analyst links
    # simultaneously, which is how a contradictory record gets made.
    db.execute(
        delete(HypothesisLinkRecord).where(
            HypothesisLinkRecord.hypothesis_id == hypothesis_id,
            HypothesisLinkRecord.independence_group == "analyst-recorded",
        )
    )
    for evidence in cited:
        db.add(
            HypothesisLinkRecord(
                link_id=uuid5(hypothesis_id, f"analyst:{evidence.evidence_id}"),
                hypothesis_id=hypothesis_id,
                evidence_id=evidence.evidence_id,
                role=role,
                modality=str((evidence.metadata_json or {}).get("modality") or "unattributed"),
                independence_group="analyst-recorded",
                weight=1.0,
            )
        )
    if hypothesis.status != payload.disposition:
        hypothesis.status = "supported" if payload.disposition == "confirmed" else "rejected"

    record = AuditService(db).record(
        "attribution.analyst_recorded",
        case_id=case_id,
        entity_type="hypothesis",
        entity_id=str(hypothesis_id),
        actor_id=payload.actor_id,
        payload={
            "disposition": payload.disposition,
            "rationale": payload.rationale,
            "evidence_ids": [str(row.evidence_id) for row in cited],
            "independence_group": "analyst-recorded",
        },
    )
    db.commit()
    return RecordLinkageResponse(
        hypothesis_id=hypothesis_id,
        disposition=payload.disposition,
        analyst_recorded=True,
        evidence_ids=[row.evidence_id for row in cited],
        recorded_at=record.occurred_at,
        audit_seq=record.seq,
    )
