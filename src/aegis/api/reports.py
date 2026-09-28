"""Case-scoped report builder and export API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.copilot.types import Claim, Report, ReportSection
from aegis.db.models import (
    AssessmentRecord,
    AttributionHypothesisRecord,
    CaseRecord,
    EvidenceRecord,
)
from aegis.reporting.export import (
    ReportProvenance,
    export_csv,
    export_json,
    export_pdf,
    export_stix_bundle,
)

router = APIRouter(prefix="/api/v1/cases/{case_id}/reports", tags=["reports"])


def build_case_report(db: Session, case_id: UUID) -> tuple[Report, ReportProvenance]:
    case = db.get(CaseRecord, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    evidence = db.scalars(
        select(EvidenceRecord)
        .where(EvidenceRecord.case_id == case_id)
        .order_by(EvidenceRecord.collected_at.asc())
    ).all()
    # This legacy table has no case_id. It is retained in the report builder
    # only as background attribution candidates; case-scoped assessments are
    # the authoritative case-bound model records below.
    _ = db.scalars(
        select(AttributionHypothesisRecord).order_by(AttributionHypothesisRecord.created_at.asc())
    ).all()
    assessments = db.scalars(
        select(AssessmentRecord)
        .where(AssessmentRecord.case_id == case_id)
        .order_by(AssessmentRecord.created_at.asc())
    ).all()

    evidence_ids = tuple(str(row.evidence_id) for row in evidence)
    assessment_ids = tuple(str(row.assessment_id) for row in assessments)
    claims: list[Claim] = [
        Claim(
            f"Case '{case.name}' contains {len(evidence)} persisted evidence records.",
            evidence_ids,
        ),
        Claim(
            f"The case has {len(assessments)} persisted attribution assessment records.",
            assessment_ids,
        ),
    ]
    for assessment in assessments:
        citations = tuple(
            str(value)
            for value in (
                *assessment.supporting_evidence_ids,
                *assessment.contradictory_evidence_ids,
            )
        )
        claims.append(
            Claim(
                f"Assessment {assessment.assessment_id} uses model "
                f"{assessment.model_id} {assessment.model_version} with raw score "
                f"{assessment.raw_score:.3f}.",
                citations,
            )
        )

    sections = (
        ReportSection("Executive Summary", tuple(claims)),
        ReportSection(
            "Evidence Matrix",
            tuple(
                Claim(
                    f"Evidence {row.evidence_id}: source={row.source_id}, "
                    f"reliability={row.source_reliability:.3f}.",
                    (str(row.evidence_id),),
                )
                for row in evidence
            ),
        ),
        ReportSection("Attribution Assessment", tuple(claims[1:])),
        ReportSection(
            "Limitations",
            (
                Claim(
                    "This report is an evidence-preserving analyst aid; attribution "
                    "remains a hypothesis requiring human review.",
                    (),
                ),
            ),
        ),
    )
    report = Report(
        title=f"AEGIS Investigation Report — {case.name}",
        sections=sections,
        evidence_ids=evidence_ids,
        generated_by="aegis-report-builder-1.0",
    )
    dataset_versions = tuple(
        sorted(
            {
                str(row.metadata_json["dataset_version"])
                for row in evidence
                if row.metadata_json.get("dataset_version")
            }
        )
    )
    provenance = ReportProvenance(
        case_id=str(case_id),
        query=f"Case report for {case.name}",
        evidence_ids=evidence_ids,
        model_versions=tuple(sorted({a.model_version for a in assessments})),
        dataset_versions=dataset_versions,
        generated_at=datetime.now(UTC),
    )
    return report, provenance


@router.get("/preview")
def report_preview(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    report, provenance = build_case_report(db, case_id)
    return cast(dict[str, object], json.loads(export_json(report, provenance)))


@router.get("/export")
def report_export(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    format: Annotated[str, Query(pattern="^(json|csv|stix|pdf)$")] = "json",
) -> Response:
    report, provenance = build_case_report(db, case_id)
    if format == "json":
        return Response(export_json(report, provenance), media_type="application/json")
    if format == "csv":
        return Response(export_csv(report, provenance), media_type="text/csv")
    if format == "stix":
        body = json.dumps(export_stix_bundle(report, provenance), indent=2)
        return Response(body, media_type="application/json")
    return Response(export_pdf(report, provenance), media_type="application/pdf")
