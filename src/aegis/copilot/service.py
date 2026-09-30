"""Analyst Copilot orchestration service (Phase 22)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from uuid import UUID

from aegis.copilot.intents import parse_intent
from aegis.copilot.report import build_report
from aegis.copilot.synthesis import synthesize
from aegis.copilot.tools import (
    CopilotToolContext,
    compare_hypotheses,
    get_actor,
    get_assessment,
    get_timeline,
    query_graph,
    search_evidence,
)
from aegis.copilot.types import Answer, EvidencePack, ParsedIntent, ToolName
from aegis.search.types import SearchError

logger = logging.getLogger(__name__)


def _run_search(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    """Search, degrading rather than failing.

    OpenSearch is an *optional* adapter — it may be absent, misconfigured or
    holding a query it rejects. None of those is a reason for the whole agent
    to return a 500: the graph, hypothesis, timeline and assessment tools all
    work without it, and a question the analyst asked should get the part of
    an answer that is available plus a statement of what is missing.

    A hard failure here meant one misconfigured optional dependency turned
    every question into an error, including the case-scoped ones that never
    needed search.
    """
    query = " ".join(intent.query.terms)
    try:
        return search_evidence(
            ctx,
            query,
            limit=intent.query.limit,
            since=intent.query.since,
            until=intent.query.until,
            entity_ids=intent.query.entity_ids,
        )
    except SearchError as error:
        # An empty pack, not a fabricated one. The synthesis layer reports
        # "no evidence-backed findings were retrieved" when every pack is
        # empty, which is exactly true here — and it is true in a way an
        # analyst can check, unlike a plausible-looking answer.
        logger.warning("Copilot search unavailable, continuing without it: %s", error)
        return EvidencePack()


def _run_graph(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    node_id = (
        intent.query.subject("actor")
        or intent.query.subject("case")
        or intent.query.subject("hypothesis")
    )
    if node_id is None:
        return EvidencePack()
    return query_graph(ctx, node_id)


def _run_actor(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    actor_id = intent.query.subject("actor")
    if actor_id is None:
        return EvidencePack()
    return get_actor(ctx, actor_id)


def _run_timeline(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    # `load_timeline` stamps every event with the *case* as its subject, so
    # "how did this investigation evolve" — a question the console itself
    # suggests, naming no id — used to match no subject and return an empty
    # pack. Requiring the analyst to type `case:<uuid>` to reach a tool that
    # has only ever been loaded with case data makes it unreachable. An
    # explicit `actor:`/`hypothesis:` subject still wins, so a narrowed
    # question is still narrowed.
    subject_id = (
        intent.query.subject("actor")
        or intent.query.subject("hypothesis")
        or intent.query.subject("case")
    )
    if subject_id is None:
        subjects = {event.subject_id for event in ctx.timeline}
        # A case-scoped context holds events for exactly one case, so a single
        # distinct subject *is* the case. Returning nothing when there is no
        # timeline at all is correct — that case has no citable events.
        if len(subjects) != 1:
            return EvidencePack()
        subject_id = next(iter(subjects))

    return get_timeline(
        ctx,
        subject_id,
        since=intent.query.since,
        until=intent.query.until,
    )


def _run_assessment(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    subject = (
        intent.query.subject("hypothesis")
        or intent.query.subject("actor")
        or intent.query.subject("case")
    )
    if subject is not None:
        try:
            assessment_id = UUID(subject)
        except ValueError:
            # A subject that is not an assessment id. An actor name is a real
            # subject the analyst asked about, so answering about the case's
            # *leading* assessment instead would silently answer a different
            # question — the "what is X's confidence" shape is not yet a tool,
            # and the honest answer is nothing rather than a near-miss.
            return EvidencePack()
    elif ctx.leading_assessment is not None:
        # No subject at all, which is what "What evidence is driving this
        # confidence?" looks like: it is the console's own suggestion for the
        # assessment tab and names no id, so requiring one made the product's
        # own prompt unanswerable while the case held twenty-eight
        # assessments. The boundary supplies the case's *leading* one.
        assessment_id = ctx.leading_assessment
    else:
        return EvidencePack()

    return get_assessment(ctx, assessment_id)


def _run_hypotheses(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    hypothesis_ids = tuple(
        UUID(value.split(":", 1)[1])
        for value in intent.query.subjects
        if value.startswith("hypothesis:")
    )
    # No ids does NOT mean "no hypotheses". A natural-language question —
    # "compare the competing hypotheses in this investigation" — names no ids,
    # and returning an empty pack here made the agent answer "no
    # evidence-backed findings were retrieved" for a case holding four
    # hypotheses and thousands of records. `compare_hypotheses` already
    # treats an empty id set as "every hypothesis in scope", which is what a
    # human means by the question.
    return compare_hypotheses(ctx, hypothesis_ids)


#: Every runner takes the same three arguments and returns a pack. Typing it
#: as `object` forced a `type: ignore` at the single call site, which is what let
#: a signature drift here go unnoticed until mypy ran in CI.
_Runner = Callable[[CopilotToolContext, ParsedIntent], EvidencePack]

_RUNNERS: Mapping[ToolName, _Runner] = {
    ToolName.SEARCH_EVIDENCE: _run_search,
    ToolName.QUERY_GRAPH: _run_graph,
    ToolName.GET_ACTOR: _run_actor,
    ToolName.GET_TIMELINE: _run_timeline,
    ToolName.GET_ASSESSMENT: _run_assessment,
    ToolName.COMPARE_HYPOTHESES: _run_hypotheses,
}


def _run_safely(tool: ToolName, ctx: CopilotToolContext, intent: ParsedIntent) -> EvidencePack:
    """Run one tool, degrading rather than failing.

    Every optional adapter behind these tools can be absent or incomplete: the
    graph is only built for a case-scoped request, so an unscoped "trace
    actor:X" would raise `RuntimeError` and return HTTP 500 for a question the
    analyst was entitled to ask. A `LookupError` from a hypothesis or assessment
    id that does not exist is the same shape — a wrong id is a normal outcome,
    not a server fault.

    Both become an empty pack. The synthesis layer then says plainly that no
    evidence-backed findings were retrieved, which is a checkable claim; a 500
    is not an answer, and a fabricated one would be worse than either.
    """
    runner = _RUNNERS.get(tool)
    if runner is None:
        logger.warning("No copilot runner registered for %s; skipping it.", tool.value)
        return EvidencePack()

    try:
        return runner(ctx, intent)
    except (RuntimeError, LookupError) as error:
        logger.info("Copilot tool %s unavailable, continuing without it: %s", tool.value, error)
        return EvidencePack()


def run_copilot(
    question: str,
    ctx: CopilotToolContext,
    *,
    limit: int = 10,
) -> Answer:
    """Route one analyst question through retrieval and safe synthesis."""
    intent = parse_intent(question, limit=limit)

    packs: list[EvidencePack] = []

    for tool in intent.tools:
        if tool is ToolName.GENERATE_REPORT:
            # Not a retrieval step. It reads the answer that the other tools
            # produced, so it runs after the merge rather than as one of them.
            # Skipping it here unconditionally is what made the tool a name in
            # `tools_run` with nothing behind it.
            continue

        packs.append(_run_safely(tool, ctx, intent))

    merged = []
    seen: set[str] = set()

    for pack in packs:
        for item in pack.items:
            if item.item_id in seen:
                continue
            seen.add(item.item_id)
            merged.append(item)

    answer = synthesize(
        question,
        intent,
        EvidencePack(tuple(merged)),
    )

    if ToolName.GENERATE_REPORT not in intent.tools:
        return answer

    # The report is assembled from the answer's *validated* claims, so it
    # cannot contain a sentence citation checking rejected. `build_report`
    # returns `None` when nothing survived validation, and a question that
    # asked for a report gets an honest "there was nothing supported enough
    # to report" rather than an empty document that looks like a finding.
    report = build_report(answer)
    if report is None:
        logger.info("Report requested for %r but no claim survived validation.", question)
        return answer
    return replace(answer, report=report)
