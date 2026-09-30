"""API schemas for the analyst copilot."""

from uuid import UUID

from pydantic import BaseModel, Field


class CopilotQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    limit: int = Field(default=10, ge=1, le=100)
    #: Scope the agent's graph, hypothesis and timeline tools to one case.
    #:
    #: Optional because the agent is also used platform-wide, but the case-
    #: scoped questions — "compare the hypotheses", "what changed" — are only
    #: answerable when it is set. Without it those tools return nothing rather
    #: than guessing an investigation.
    case_id: UUID | None = None
    #: Which screen the analyst asked from, e.g. "Operation Nightfall —
    #: viewing assessment".
    #:
    #: A *separate field*, never appended to `question`. The intent router
    #: matches on substrings, so a grounding suffix naming the view leaked
    #: "assessment" into every question typed on the assessment tab and
    #: routed it to `get_assessment` with no subject; and every word of it
    #: became an AND-ed search term. Grounding describes context, so it
    #: travels as context and the question stays the analyst's own words.
    context: str | None = Field(default=None, max_length=500)


class CopilotReportSection(BaseModel):
    heading: str
    claims: list[str]


class CopilotReport(BaseModel):
    """A brief assembled only from citation-validated claims.

    ``None`` when nothing survived validation, which is a different state from
    a report with no sections: the first means the question could not be
    answered to a citable standard, the second would be a document.
    """

    title: str
    sections: list[CopilotReportSection]
    evidence_ids: list[str]
    generated_by: str


class CopilotQueryResponse(BaseModel):
    question: str
    #: Echoed so the console can show which screen an answer was produced for.
    #: Present on the response rather than only in the request so a copied
    #: answer carries its own provenance.
    context: str | None = None
    intent: str
    rule: str
    tools_run: list[str]
    evidence_ids: list[str]
    flagged_evidence_ids: list[str]
    claims: list[dict[str, object]]
    unsupported_claims: list[dict[str, object]]
    dropped_claims: list[dict[str, object]]
    text: str
    report: CopilotReport | None = None
    #: Which engine answered, when the configured one was not available.
    #: Empty when the configured adapter served the question, because a
    #: working index is not news. The deployment does not run OpenSearch, so
    #: this is the normal case there and the analyst is entitled to know that
    #: "the top 10" means the top 10 of a bounded window.
    search: str = ""
