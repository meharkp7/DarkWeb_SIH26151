"""Analyst Copilot API boundary."""

from dataclasses import replace
from typing import Annotated, cast

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.api.security import RequestRateLimiter, request_guard
from aegis.copilot.context import (
    assessment_service,
    build_graph,
    leading_assessment,
    load_hypotheses,
    load_timeline,
)
from aegis.copilot.service import run_copilot
from aegis.copilot.tools import CopilotToolContext
from aegis.copilot.types import Report, ValidatedClaim
from aegis.schemas.copilot import (
    CopilotQueryRequest,
    CopilotQueryResponse,
    CopilotReport,
)
from aegis.search.opensearch import OpenSearchAdapter
from aegis.settings import settings

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])

#: Copilot questions are the most expensive read in the console — a scoped one
#: builds a graph — so they are paced like a write even though they change
#: nothing. Without a bound, one analyst holding ⌘J can serialise the API.
#:
#: Tighter than the application default of 120/minute: an analyst asking the
#: agent questions in a burst is doing something the platform should slow down,
#: and 20 is still several times a human reading rate.
_QUERY_LIMITER = RequestRateLimiter(limit=20, window_seconds=60.0)
_copilot_guard = request_guard(_QUERY_LIMITER, max_bytes=65_536)


def get_copilot_context(
    db: Annotated[Session, Depends(get_db)],
) -> CopilotToolContext:
    """Build the copilot's search dependency from configuration.

    The graph, assessment, timeline and hypothesis adapters are *not* built
    here. They are the expensive part — up to 2 000 entities and 4 000
    relationships per case — and they can only be scoped once the case is
    known, which is in the request body rather than in a dependency. Loading
    them for every request and then loading them *again* when a case is
    supplied is the difference between a responsive agent and a stalled one.

    An unscoped request therefore gets search only, which is the honest
    capability set: a platform-wide graph over a large deployment is tens of
    thousands of nodes, and a two-hop expansion of it is not an answer.
    """
    username = settings.opensearch_username
    password = settings.opensearch_password
    auth = (username, password) if username is not None and password is not None else None

    return CopilotToolContext(
        search=OpenSearchAdapter(
            settings.opensearch_url,
            index_prefix=settings.opensearch_index_prefix,
            http_auth=auth,
        )
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


def _report_dict(report: Report | None) -> dict[str, object] | None:
    """Serialise the report, keeping every claim with it.

    The section model carries `Claim` objects; the wire shape carries the text
    alone, because a claim in a report that cannot be traced back to evidence
    is exactly the sentence this whole pipeline exists to prevent — so the
    section's citations are already on the sibling `claims` field, and the
    report's own `evidence_ids` names every record involved.
    """
    if report is None:
        return None
    return {
        "title": report.title,
        "sections": [
            {"heading": section.heading, "claims": [claim.text for claim in section.claims]}
            for section in report.sections
        ],
        "evidence_ids": list(report.evidence_ids),
        "generated_by": report.generated_by,
    }


@router.post("/query", response_model=CopilotQueryResponse)
def copilot_query(
    payload: CopilotQueryRequest,
    context: Annotated[CopilotToolContext, Depends(get_copilot_context)],
    db: Annotated[Session, Depends(get_db)],
    guard: Annotated[None, Depends(_copilot_guard)],
) -> CopilotQueryResponse:
    del guard  # the dependency *is* the rate limit and body-size cap
    # The body is the only place the case is named. A `?case_id=` query
    # parameter used to exist alongside it, which meant two scope channels
    # that could disagree — the graph was built for one and the tool call used
    # the other, and the second silently won.
    if payload.case_id is not None:
        lead = leading_assessment(db, payload.case_id)
        context = replace(
            context,
            graph=build_graph(db, case_id=payload.case_id),
            assessments=assessment_service(db),
            timeline=load_timeline(db, case_id=payload.case_id),
            hypotheses=load_hypotheses(db, case_id=payload.case_id),
            leading_assessment=lead.assessment_id if lead is not None else None,
        )
    answer = run_copilot(payload.question, context, limit=payload.limit)

    return CopilotQueryResponse(
        question=answer.question,
        context=payload.context,
        intent=answer.intent.intent.value,
        rule=answer.intent.rule,
        tools_run=[tool.value for tool in answer.tools_run],
        evidence_ids=list(answer.pack.ids),
        flagged_evidence_ids=[item.item_id for item in answer.flagged_items],
        claims=[_claim_dict(entry) for entry in answer.validation.supported],
        unsupported_claims=[_claim_dict(entry) for entry in answer.validation.unsupported],
        dropped_claims=[_claim_dict(entry) for entry in answer.validation.dropped],
        text=answer.text,
        report=cast("CopilotReport | None", _report_dict(answer.report)),
    )
