"""Analyst Copilot API boundary."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Annotated, cast
from uuid import UUID

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
from aegis.copilot.postgres_search import PostgresEvidenceSearch
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

logger = logging.getLogger(__name__)

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

#: Cached OpenSearch reachability. ``None`` means "not probed yet".
#:
#: The deployment does not run OpenSearch at all, so without this every copilot
#: question would pay a refused connection before falling back — turning a
#: missing optional adapter into a per-request stall. The TTL exists so a
#: cluster that is started later is picked up rather than ignored for the life
#: of the process.
_PROBE_TTL_S = 30.0
_opensearch_available: bool | None = None
_opensearch_checked_at: float = 0.0


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

    The engine itself is a *lazy fallback*. The adapter is constructed
    unconditionally and is the preferred path, but OpenSearch is optional
    and absent unless someone ran `docker compose up`. When it is, the
    default route — the one every plain question takes — returned nothing at
    all, which is what left the agent looking broken in the default
    deployment while its tests passed against a stubbed engine. The handler
    swaps in a PostgreSQL-backed engine when the adapter reports itself
    unavailable, and the response says which one answered.
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


def _use_postgres_fallback(
    context: CopilotToolContext, db: Session, case_id: UUID | None
) -> tuple[CopilotToolContext, str]:
    """Swap in the PostgreSQL engine when OpenSearch is not there.

    Returns the context to use and a short note for the response. The note is
    empty when the configured adapter answered, because a working index is not
    news.

    A *probe* rather than a `try` around the query. Wrapping the query would
    also catch a genuine query rejection — a malformed query, a filter the
    index refuses — and silently re-run it against different data, which turns
    a bug in the adapter into a quiet difference in the answer. Probing
    separates "there is no cluster" from "the cluster did not like this".

    The probe result is memoised for the process, because a question arriving
    on a box with no OpenSearch should not pay a connection timeout every
    time. A short TTL keeps a cluster that comes back from being ignored for
    the life of the process.
    """
    global _opensearch_available, _opensearch_checked_at
    if _opensearch_available is None or time.monotonic() - _opensearch_checked_at > _PROBE_TTL_S:
        _opensearch_available = _probe_opensearch(context.search)
        _opensearch_checked_at = time.monotonic()

    if _opensearch_available:
        return context, ""

    fallback = replace(context, search=PostgresEvidenceSearch(db, case_id=case_id))
    scope = "this investigation" if case_id is not None else "the platform"
    return fallback, (
        f"Searched with PostgreSQL: the OpenSearch adapter is not reachable, so "
        f"results cover the most recent records in {scope}."
    )


def _probe_opensearch(engine: object) -> bool:
    """Whether the configured search engine can actually answer.

    The adapter raises `SearchError` for both a missing package and a refused
    connection, which are the two cases the deployment says to expect.
    """
    if not isinstance(engine, OpenSearchAdapter):
        # Anything injected rather than configured — a test double, or a
        # caller that supplied its own engine. Leave it alone.
        return True
    try:
        engine.client.cluster.health()
    except Exception as error:  # noqa: BLE001 - any failure means "unavailable"
        logger.info("OpenSearch unavailable; the copilot will search PostgreSQL: %s", error)
        return False
    return True


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
            case_id=payload.case_id,
        )

    # The engine swap happens last, once the case is known, because the
    # fallback is scoped to it. A probe is used rather than a bare try: the
    # adapter reports a transport failure as a `SearchError`, and catching
    # that around the *query* would also swallow a genuine query rejection,
    # which is a different thing and should not silently change engines.
    engine_note = ""
    context, engine_note = _use_postgres_fallback(context, db, payload.case_id)

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
        search=engine_note,
        report=cast("CopilotReport | None", _report_dict(answer.report)),
    )
