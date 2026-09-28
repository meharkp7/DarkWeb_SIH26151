"""Safe, reproducible JSON/CSV/STIX 2.1 report exports."""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO

from aegis.copilot.types import Report


@dataclass(frozen=True)
class ReportProvenance:
    case_id: str
    query: str
    evidence_ids: tuple[str, ...]
    model_versions: tuple[str, ...]
    dataset_versions: tuple[str, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.query.strip():
            raise ValueError("case_id and query must be non-empty")
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")


def _payload(report: Report, provenance: ReportProvenance) -> dict[str, object]:
    return {
        "title": report.title,
        "generated_by": report.generated_by,
        "sections": [
            {"heading": section.heading, "claims": [claim.text for claim in section.claims]}
            for section in report.sections
        ],
        "provenance": {
            "case_id": provenance.case_id,
            "query": provenance.query,
            "evidence_ids": list(provenance.evidence_ids),
            "model_versions": list(provenance.model_versions),
            "dataset_versions": list(provenance.dataset_versions),
            "generated_at": provenance.generated_at.astimezone(UTC).isoformat(),
        },
    }


def export_json(report: Report, provenance: ReportProvenance) -> str:
    """Stable JSON suitable for evidence-preserving archival."""
    return json.dumps(_payload(report, provenance), sort_keys=True, indent=2)


def export_csv(report: Report, provenance: ReportProvenance) -> str:
    """One row per cited claim, retaining case and report provenance."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=("case_id", "section", "claim", "citations"))
    writer.writeheader()
    for section in report.sections:
        for claim in section.claims:
            writer.writerow(
                {
                    "case_id": provenance.case_id,
                    "section": section.heading,
                    "claim": claim.text,
                    "citations": ";".join(claim.citations),
                }
            )
    return output.getvalue()


def export_stix_bundle(report: Report, provenance: ReportProvenance) -> dict[str, object]:
    """Emit a conservative STIX 2.1 bundle of analyst findings as note objects.

    Findings are not promoted to asserted identity objects; the report remains
    explicitly an assessment and all evidence ids stay in external references.
    """
    timestamp = provenance.generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    objects: list[dict[str, object]] = []
    for ordinal, section in enumerate(report.sections):
        content = "\n".join(claim.text for claim in section.claims)
        if not content:
            continue
        objects.append(
            {
                "type": "note",
                "spec_version": "2.1",
                "id": f"note--{uuid.uuid5(uuid.NAMESPACE_URL, f'{provenance.case_id}:{ordinal}')}",
                "created": timestamp,
                "modified": timestamp,
                "content": content,
                "abstract": section.heading,
                "external_references": [
                    {"source_name": "aegis-evidence", "external_id": evidence_id}
                    for evidence_id in provenance.evidence_ids
                ],
            }
        )
    return {"type": "bundle", "id": f"bundle--{uuid.uuid4()}", "objects": objects}


def export_pdf(report: Report, provenance: ReportProvenance) -> bytes:
    """Render a minimal provenance-preserving PDF report."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError("PDF export requires the report extra") from exc
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, title=report.title)
    styles = getSampleStyleSheet()
    story = [Paragraph(report.title, styles["Title"]), Spacer(1, 12)]
    story.append(Paragraph(f"Case: {provenance.case_id}", styles["Normal"]))
    story.append(Paragraph(f"Query: {provenance.query}", styles["Normal"]))
    story.append(
        Paragraph(
            f"Generated: {provenance.generated_at.astimezone(UTC).isoformat()}", styles["Normal"]
        )
    )
    story.append(Spacer(1, 12))
    for section in report.sections:
        story.append(Paragraph(section.heading, styles["Heading2"]))
        for claim in section.claims:
            citations = (
                ", ".join(claim.citations) if claim.citations else "no direct evidence citation"
            )
            story.append(Paragraph(f"{claim.text} <i>[{citations}]</i>", styles["BodyText"]))
            story.append(Spacer(1, 5))
    document.build(story)
    return buffer.getvalue()
