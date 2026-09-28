"""API schemas for the analyst copilot."""

from pydantic import BaseModel, Field


class CopilotQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    limit: int = Field(default=10, ge=1, le=100)


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
