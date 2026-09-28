"""Analyst Copilot orchestration service (Phase 22)."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from aegis.copilot.intents import parse_intent
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


def _run_search(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    query = " ".join(intent.query.terms)
    return search_evidence(
        ctx,
        query,
        limit=intent.query.limit,
        since=intent.query.since,
        until=intent.query.until,
        entity_ids=intent.query.entity_ids,
    )


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
    subject_id = (
        intent.query.subject("actor")
        or intent.query.subject("case")
        or intent.query.subject("hypothesis")
    )
    if subject_id is None:
        return EvidencePack()

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
    if subject is None:
        return EvidencePack()

    try:
        assessment_id = UUID(subject)
    except ValueError:
        return EvidencePack()

    return get_assessment(ctx, assessment_id)


def _run_hypotheses(
    ctx: CopilotToolContext,
    intent: ParsedIntent,
) -> EvidencePack:
    hypothesis_ids = tuple(
        UUID(value)
        for value in intent.query.subjects
        if value.startswith("hypothesis:")
        for raw in (value.split(":", 1)[1],)
    )
    if not hypothesis_ids:
        return EvidencePack()

    return compare_hypotheses(ctx, hypothesis_ids)


_RUNNERS: Mapping[ToolName, object] = {
    ToolName.SEARCH_EVIDENCE: _run_search,
    ToolName.QUERY_GRAPH: _run_graph,
    ToolName.GET_ACTOR: _run_actor,
    ToolName.GET_TIMELINE: _run_timeline,
    ToolName.GET_ASSESSMENT: _run_assessment,
    ToolName.COMPARE_HYPOTHESES: _run_hypotheses,
}


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
            continue

        runner = _RUNNERS.get(tool)
        if runner is None:
            raise ValueError(f"no copilot runner registered for {tool.value}")

        # All registered runners share this concrete callable shape.
        packs.append(runner(ctx, intent))  # type: ignore[operator]

    merged = []
    seen: set[str] = set()

    for pack in packs:
        for item in pack.items:
            if item.item_id in seen:
                continue
            seen.add(item.item_id)
            merged.append(item)

    return synthesize(
        question,
        intent,
        EvidencePack(tuple(merged)),
    )
