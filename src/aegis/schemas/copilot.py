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


class CopilotQueryResponse(BaseModel):
    question: str
    intent: str
    rule: str
    tools_run: list[str]
    evidence_ids: list[str]
    flagged_evidence_ids: list[str]
    claims: list[dict[str, object]]
    unsupported_claims: list[dict[str, object]]
    dropped_claims: list[dict[str, object]]
    text: str
