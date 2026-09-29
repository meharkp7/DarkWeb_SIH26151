"""Analyst Copilot API boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.copilot.context import (
    assessment_service,
    build_graph,
    load_hypotheses,
    load_timeline,
)
from aegis.copilot.service import run_copilot
from aegis.copilot.tools import CopilotToolContext
from aegis.copilot.types import ValidatedClaim
from aegis.schemas.copilot import CopilotQueryRequest, CopilotQueryResponse
from aegis.search.opensearch import OpenSearchAdapter
from aegis.settings import settings

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


def get_copilot_context(
    case_id: Annotated[UUID | None, Query()] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> CopilotToolContext:
    """Build the copilot's tool context from the live database.

    The graph, assessment, timeline and hypothesis adapters used to be left
    unset here, so every tool except search answered "not available" and the
    agent's suggested questions — compare the hypotheses, trace this actor —
    were promised and unanswerable.

    The graph build is the expensive part, so it is only performed for a
    case-scoped request. A platform-wide graph over a large deployment is tens
    of thousands of nodes, and a two-hop expansion of a graph that took a
    minute to load is not an answer.
    """
    username = settings.opensearch_username
    password = settings.opensearch_password
    auth = (username, password) if username is not None and password is not None else None

    search = OpenSearchAdapter(
        settings.opensearch_url,
        index_prefix=settings.opensearch_index_prefix,
        http_auth=auth,
    )
    if case_id is None:
        # Unscoped: the agent can search and quote, but the graph, timeline
        # and hypothesis tools have nothing to narrow to and are left unset
        # rather than filled with every row in the platform.
        return CopilotToolContext(search=search)

    return CopilotToolContext(
        search=search,
        graph=build_graph(db, case_id=case_id),
        assessments=assessment_service(db),
        timeline=load_timeline(db, case_id=case_id),
        hypotheses=load_hypotheses(db, case_id=case_id),
    )


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
    db: Annotated[Session, Depends(get_db)],
) -> CopilotQueryResponse:
    # The body carries the case, because that is where the analyst's context
    # already is. A query parameter would mean the client has to repeat the
    # scope in two places and be able to contradict itself between them.
    if payload.case_id is not None:
        context = CopilotToolContext(
            search=context.search,
            graph=build_graph(db, case_id=payload.case_id),
            assessments=assessment_service(db),
            timeline=load_timeline(db, case_id=payload.case_id),
            hypotheses=load_hypotheses(db, case_id=payload.case_id),
        )
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
