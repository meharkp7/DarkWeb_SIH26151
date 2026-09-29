"""Phase 22 analyst-copilot tool adapters.

This module deliberately contains orchestration only. Canonical search,
graph, timeline, hypothesis and assessment objects remain authoritative.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from aegis.attribution.persistence import AttributionAssessmentPersistenceService
from aegis.copilot.types import EvidenceItem, EvidencePack, ToolName
from aegis.graph.store import InMemoryGraphStore
from aegis.schemas.hypothesis import Hypothesis
from aegis.search import (
    IndexName,
    MatchMode,
    RetrievalMode,
    SearchEngine,
    SearchQuery,
)
from aegis.timeline.types import TimelineEvent


@dataclass(frozen=True)
class CopilotToolContext:
    """Dependencies supplied by the application boundary."""

    search: SearchEngine | None = None
    graph: InMemoryGraphStore | None = None
    assessments: AttributionAssessmentPersistenceService | None = None
    timeline: Sequence[TimelineEvent] = ()
    hypotheses: Sequence[Hypothesis] = ()


def _pack(
    *,
    tool: ToolName,
    items: Sequence[Any],
    evidence_ids: Sequence[str] = (),
    explanation: str = "",
) -> EvidencePack:
    """Convert tool results into the canonical Phase 22 evidence pack."""
    del explanation

    ids = tuple(dict.fromkeys(str(x) for x in evidence_ids))

    packed: list[EvidenceItem] = []
    for index, item in enumerate(items):
        item_id = ids[index] if index < len(ids) else f"{tool.value}:{index}"
        packed.append(
            EvidenceItem(
                item_id=item_id,
                tool=tool,
                kind=type(item).__name__,
                summary=f"{tool.value} returned {type(item).__name__} record {item_id}.",
                data_text=repr(item),
                provenance={"tool": tool.value},
            )
        )

    return EvidencePack(tuple(packed))


def search_evidence(
    ctx: CopilotToolContext,
    query: str,
    *,
    limit: int = 10,
    since: datetime | None = None,
    until: datetime | None = None,
    entity_ids: Sequence[str] = (),
) -> EvidencePack:
    if ctx.search is None:
        raise RuntimeError("search dependency is not configured")

    result = ctx.search.search(
        SearchQuery(
            text=query,
            index=IndexName.EVIDENCE,
            limit=limit,
            since=since,
            until=until,
            entity_ids=tuple(entity_ids),
            match_mode=MatchMode.TERMS,
            retrieval_mode=RetrievalMode.HYBRID,
        )
    )

    evidence_ids: list[str] = []
    for hit in result.hits:
        evidence_ids.append(str(hit.document.doc_id))

    return _pack(
        tool=ToolName.SEARCH_EVIDENCE,
        items=result.hits,
        evidence_ids=evidence_ids,
        explanation=f"Retrieved {len(result.hits)} evidence records.",
    )


def query_graph(
    ctx: CopilotToolContext,
    node_id: str,
    *,
    direction: str = "both",
    at_time: datetime | None = None,
    max_hops: int = 2,
) -> EvidencePack:
    if ctx.graph is None:
        raise RuntimeError("graph dependency is not configured")

    neighborhood = ctx.graph.two_hop_neighborhood(
        node_id,
        direction=direction,
        at_time=at_time,
        max_hops=max_hops,
    )

    evidence_ids = [evidence_id for edge in neighborhood.edges for evidence_id in edge.evidence_ids]

    return _pack(
        tool=ToolName.QUERY_GRAPH,
        items=(neighborhood,),
        evidence_ids=evidence_ids,
        explanation=(
            f"Returned a {max_hops}-hop temporal neighborhood containing "
            f"{len(neighborhood.nodes)} nodes and {len(neighborhood.edges)} edges."
        ),
    )


def get_actor(
    ctx: CopilotToolContext,
    actor_id: str,
) -> EvidencePack:
    if ctx.graph is None:
        raise RuntimeError("graph dependency is not configured")

    actor = ctx.graph.get_node(actor_id)
    neighborhood = ctx.graph.two_hop_neighborhood(actor_id, max_hops=1)

    evidence_ids = [evidence_id for edge in neighborhood.edges for evidence_id in edge.evidence_ids]

    return _pack(
        tool=ToolName.GET_ACTOR,
        items=(actor, neighborhood),
        evidence_ids=evidence_ids,
        explanation=f"Returned actor node {actor_id} and its immediate associations.",
    )


def get_timeline(
    ctx: CopilotToolContext,
    subject_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> EvidencePack:
    events = [
        event
        for event in ctx.timeline
        if event.subject_id == subject_id
        and (since is None or event.observed_at >= since)
        and (until is None or event.observed_at <= until)
    ]
    events.sort(key=lambda event: (event.observed_at, event.event_id))

    evidence_ids = [evidence_id for event in events for evidence_id in event.evidence_ids]

    return _pack(
        tool=ToolName.GET_TIMELINE,
        items=events,
        evidence_ids=evidence_ids,
        explanation=f"Returned {len(events)} timeline events for {subject_id}.",
    )


def get_assessment(
    ctx: CopilotToolContext,
    assessment_id: UUID,
) -> EvidencePack:
    if ctx.assessments is None:
        raise RuntimeError("assessment dependency is not configured")

    record = ctx.assessments.get(assessment_id)
    if record is None:
        raise LookupError(f"assessment {assessment_id} not found")

    evidence_ids = [
        *map(str, record.supporting_evidence_ids),
        *map(str, record.contradictory_evidence_ids),
    ]

    return _pack(
        tool=ToolName.GET_ASSESSMENT,
        items=(record,),
        evidence_ids=evidence_ids,
        explanation=f"Returned attribution assessment {assessment_id}.",
    )


def compare_hypotheses(
    ctx: CopilotToolContext,
    hypothesis_ids: Sequence[UUID],
) -> EvidencePack:
    wanted = {str(value) for value in hypothesis_ids}

    if not wanted:
        # No ids in the question means "all of them in scope", not "none of
        # them". "Compare the competing hypotheses in this investigation" — the
        # question the console itself suggests — names no ids, and comparing
        # zero hypotheses returned "Compared 0 competing hypotheses", which
        # reads as "there are none" when the case has twenty-eight.
        hypotheses = tuple(sorted(ctx.hypotheses, key=lambda h: str(h.hypothesis_id)))
    else:
        hypotheses = tuple(
            hypothesis for hypothesis in ctx.hypotheses if str(hypothesis.hypothesis_id) in wanted
        )

    if wanted and len(hypotheses) != len(wanted):
        found = {str(h.hypothesis_id) for h in hypotheses}
        missing = sorted(wanted - found)
        raise LookupError(f"hypotheses not found: {missing}")

    evidence_ids = [
        str(link.evidence_id)
        for hypothesis in sorted(hypotheses, key=lambda h: str(h.hypothesis_id))
        for link in hypothesis.links
    ]

    return _pack(
        tool=ToolName.COMPARE_HYPOTHESES,
        items=tuple(sorted(hypotheses, key=lambda h: str(h.hypothesis_id))),
        evidence_ids=evidence_ids,
        explanation=f"Compared {len(hypotheses)} competing hypotheses.",
    )


def generate_report(
    *,
    report: Any,
    provenance: Any,
    export_format: str = "json",
) -> str | dict[str, object]:
    """Export an already validated Report through Phase 24."""

    from aegis.reporting import export_csv, export_json, export_stix_bundle

    if export_format == "json":
        return export_json(report, provenance)
    if export_format == "csv":
        return export_csv(report, provenance)
    if export_format == "stix":
        return export_stix_bundle(report, provenance)

    raise ValueError("export_format must be json, csv, or stix")
