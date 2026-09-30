"""Builds a citation-validated analyst brief from a copilot answer.

``generate_report`` was advertised in the tool set and in the console's own
progress trail, but nothing implemented it: `service.py` skipped it
unconditionally and `Answer.report` was therefore always ``None``. A question
containing the word "report" ran the tool name, showed it in the UI as
though it had run, and returned no report.

The contract is in :class:`~aegis.copilot.types.Report` — *built only from
validated claims, so a report can never contain a sentence that citation
validation rejected*. That is the whole reason this module is separate from
synthesis: synthesis proposes, validation rules, and only what survives
validation may be printed. A report generator that reached past validation
would be a hole in the containment property the injection tests assert on.
"""

from __future__ import annotations

from datetime import datetime

from aegis.copilot.types import Answer, Claim, Report, ReportSection
from aegis.reporting import ReportProvenance

#: Tool name -> the heading its claims appear under.
#:
#: Grouped by the tool that produced the claim rather than by one flat list,
#: because "here is what we found" is not a report — a report says *what kind*
#: of finding this is. An unmapped origin lands under "Other findings" rather
#: than being dropped, so a newly added tool does not silently shrink the
#: report.
_ORIGIN_HEADINGS: tuple[tuple[str, str], ...] = (
    ("tool:search_evidence", "Evidence retrieved"),
    ("tool:compare_hypotheses", "Hypotheses compared"),
    ("tool:query_graph", "Relationship graph"),
    ("tool:get_actor", "Actor profile"),
    ("tool:get_timeline", "Timeline"),
    ("tool:get_assessment", "Attribution assessment"),
)
_FALLBACK_HEADING = "Other findings"


def _heading_for(origin: str) -> str:
    for prefix, heading in _ORIGIN_HEADINGS:
        if origin == prefix or origin.startswith(f"{prefix}:"):
            return heading
    return _FALLBACK_HEADING


def build_report(answer: Answer, *, title: str | None = None) -> Report | None:
    """The answer's supported claims as a report, or ``None`` if there are none.

    Returning ``None`` rather than an empty report is deliberate. A brief with
    no sections would still be presented to the analyst as a document they had
    asked for, and the difference between "here is your report, it is empty"
    and "there was nothing supported enough to put in one" is the difference
    between a report and a fabrication.
    """
    if not answer.validation.supported_claims:
        return None

    grouped: dict[str, list[Claim]] = {}
    for claim in answer.validation.supported_claims:
        grouped.setdefault(_heading_for(claim.origin), []).append(claim)

    # Section order follows `_ORIGIN_HEADINGS`, not dict insertion order, so
    # the same question always produces the same document layout.
    order = [heading for _, heading in _ORIGIN_HEADINGS] + [_FALLBACK_HEADING]
    sections = tuple(
        ReportSection(heading=heading, claims=tuple(grouped[heading]))
        for heading in order
        if heading in grouped
    )
    if not sections:
        return None

    return Report(
        title=title or answer.question,
        sections=sections,
        evidence_ids=answer.pack.ids,
        generated_by="aegis.copilot",
    )


def report_provenance(answer: Answer, *, case_id: str, generated_at: datetime) -> ReportProvenance:
    """Provenance for the Phase 24 exporters.

    Imported here rather than at module scope so this module does not become a
    reason for `aegis.reporting` — which already imports the copilot types —
    to pull in the whole copilot service.
    """
    return ReportProvenance(
        case_id=case_id,
        query=answer.question,
        evidence_ids=answer.pack.ids,
        model_versions=(),
        dataset_versions=(),
        generated_at=generated_at,
    )


__all__ = ["build_report", "report_provenance"]
