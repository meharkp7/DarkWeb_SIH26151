from datetime import UTC, datetime

from aegis.copilot.types import Claim, Report, ReportSection
from aegis.reporting.export import ReportProvenance, export_csv, export_json, export_stix_bundle


def _report() -> Report:
    return Report(
        "Assessment",
        (ReportSection("Findings", (Claim("Observed indicator", ("e1",)),)),),
        ("e1",),
        "aegis",
    )


def _provenance() -> ReportProvenance:
    return ReportProvenance(
        "case-1", "question", ("e1",), ("model-1",), ("data-1",), datetime(2026, 1, 1, tzinfo=UTC)
    )


def test_exports_preserve_provenance_and_citations() -> None:
    assert '"case_id": "case-1"' in export_json(_report(), _provenance())
    assert "Observed indicator" in export_csv(_report(), _provenance())
    bundle = export_stix_bundle(_report(), _provenance())
    assert bundle["type"] == "bundle"
    assert bundle["objects"][0]["external_references"][0]["external_id"] == "e1"


def test_stix_is_deterministic_per_section_id() -> None:
    first = export_stix_bundle(_report(), _provenance())
    second = export_stix_bundle(_report(), _provenance())
    assert first["objects"][0]["id"] == second["objects"][0]["id"]
