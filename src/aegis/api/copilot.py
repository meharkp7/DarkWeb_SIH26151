"""Analyst Copilot API boundary."""

from typing import Annotated

from fastapi import APIRouter, Depends

from aegis.copilot.service import run_copilot
from aegis.copilot.tools import CopilotToolContext
from aegis.copilot.types import ValidatedClaim
from aegis.schemas.copilot import CopilotQueryRequest, CopilotQueryResponse
from aegis.search.opensearch import OpenSearchAdapter
from aegis.settings import settings

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


def get_copilot_context() -> CopilotToolContext:
    """Build the production Copilot context from configured backends.

    Graph, assessment, timeline and hypothesis adapters remain unset until
    their production persistence interfaces are explicitly wired.
    """
    username = settings.opensearch_username
    password = settings.opensearch_password
    auth = (username, password) if username is not None and password is not None else None

    search = OpenSearchAdapter(
        settings.opensearch_url,
        index_prefix=settings.opensearch_index_prefix,
        http_auth=auth,
    )
    return CopilotToolContext(search=search)


def _claim_dict(entry: ValidatedClaim) -> dict[str, object]:
    claim = entry.claim
    return {
        "text": claim.text,
        "citations": list(claim.citations),
        "origin": claim.origin,
        "status": entry.status.value,
        "reason": entry.reason,
    }


@router.post("/query", response_model=CopilotQueryResponse)
def copilot_query(
    payload: CopilotQueryRequest,
    context: Annotated[CopilotToolContext, Depends(get_copilot_context)],
) -> CopilotQueryResponse:
    answer = run_copilot(payload.question, context, limit=payload.limit)

    return CopilotQueryResponse(
        question=answer.question,
        intent=answer.intent.intent.value,
        rule=answer.intent.rule,
        tools_run=[tool.value for tool in answer.tools_run],
        evidence_ids=list(answer.pack.ids),
        flagged_evidence_ids=[item.item_id for item in answer.flagged_items],
        claims=[_claim_dict(entry) for entry in answer.validation.supported],
        unsupported_claims=[_claim_dict(entry) for entry in answer.validation.unsupported],
        dropped_claims=[_claim_dict(entry) for entry in answer.validation.dropped],
        text=answer.text,
    )
