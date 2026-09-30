"""Phase 22 analyst-copilot tool adapters.

This module deliberately contains orchestration only. Canonical search,
graph, timeline, hypothesis and assessment objects remain authoritative.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
    #: The case's leading assessment, used when a question about confidence
    #: names no id. Set by the boundary, which is the only layer that knows
    #: the case; the tool itself must not reach for "the newest" and start
    #: answering about a different investigation's assessment.
    leading_assessment: UUID | None = None


def _pack(
    *,
    tool: ToolName,
    items: Sequence[Any],
    evidence_ids: Sequence[str] = (),
    explanation: str = "",
    describe: Callable[[Any], str] | None = None,
    render: Callable[[Any], str] | None = None,
    cite: Callable[[Any], Sequence[str]] | None = None,
) -> EvidencePack:
    """Convert tool results into the canonical Phase 22 evidence pack.

    `describe` and `render` exist because the previous shape produced an
    answer no analyst could read: the summary was a template
    ("compare_hypotheses returned Hypothesis record <uuid>") and the data
    region was ``repr(item)`` — a raw Python tuple in the middle of an
    intelligence report.

    Two correctness problems came with it. A hypothesis was cited by the *first
    evidence id in the pack*, so the claim text named an evidence record while
    the item was a hypothesis; and every item fell back to a positional id, so
    two runs over the same data cited different things. Each tool now says
    what its own record is, how it renders, and what it is cited by.
    """
    del explanation
    cited = tuple(dict.fromkeys(str(x) for x in evidence_ids))

    packed: list[EvidenceItem] = []
    for index, item in enumerate(items):
        item_ids = tuple(str(value) for value in cite(item)) if cite is not None else ()
        if item_ids:
            item_id = item_ids[0]
        elif index < len(cited):
            # Positional fallback, kept only for tools that do not know their
            # own identity. Stable because `items` is ordered.
            item_id = cited[index]
        else:
            item_id = f"{tool.value}:{index}"
        packed.append(
            EvidenceItem(
                item_id=item_id,
                tool=tool,
                kind=type(item).__name__,
                summary=(
                    describe(item)
                    if describe is not None
                    else f"{tool.value} returned {type(item).__name__} record {item_id}."
                ),
                data_text=render(item) if render is not None else "",
                provenance={"tool": tool.value},
            )
        )

    return EvidencePack(tuple(packed))


def _describe(record: object) -> str:
    """A one-line, human-readable description of a returned record.

    The pack's default summary was a template — "get_actor returned Actor
    record <uuid>" — which is what the analyst actually saw. Anything better
    than that has to know the record's fields, and only the tool that fetched
    it does, so the fallbacks live here and each tool overrides what matters.
    """
    name = type(record).__name__
    fields = {
        key: value
        for key, value in vars(record).items()
        if not key.startswith("_") and isinstance(value, (str, int, float, bool))
    }
    if not fields:
        return f"{name} record"
    head = ", ".join(f"{key}={value}" for key, value in list(fields.items())[:4])
    return f"{name}: {head}"


def _render(record: object) -> str:
    """The data region, as text rather than a Python repr."""
    return (
        "\n".join(
            f"{key}={value}" for key, value in vars(record).items() if not key.startswith("_")
        )
        if hasattr(record, "__dict__")
        else str(record)
    )


def _field(fields: object, name: str) -> str | None:
    """One non-empty value out of an index document's ``fields`` mapping.

    The searchable text is held in ``fields`` (a mapping), not in attributes
    on the document, so a `getattr` lookup by field name silently finds
    nothing. An empty string is stored for absent optional values, so it has
    to be treated as missing rather than rendered as `key=`.
    """
    if not isinstance(fields, Mapping):
        return None
    value = fields.get(name)
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    return None


def _first_str(record: object, attributes: tuple[str, ...]) -> str | None:
    """The first non-empty string among `attributes`, trimmed.

    Search hits and timeline events both carry the same information under
    different names depending on which producer wrote them, and an empty string
    is a value that must not win over a real one further down the list.
    """
    for name in attributes:
        value = getattr(record, name, None)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
    return None


def _cite_by(*attributes: str) -> Callable[[object], Sequence[str]]:
    """Cite a record by its own identity, not by its position in the pack.

    Positional ids meant the same question cited different records on a
    re-run, and a claim could name an evidence id while the item was an
    actor.
    """
    def cite_by(item: object) -> Sequence[str]:
        # `item_id` is the identifier the tool already stamped on the record,
        # so it is checked first. A record carrying none of the attributes
        # yields nothing rather than a literal "unknown" — an empty citation
        # lets the caller fall back to a stable positional id, whereas
        # "unknown" would silently make every record cite itself.
        for candidate in ("item_id", *attributes):
            value = getattr(item, candidate, None)
            if value:
                return (str(value),)
        return ()

    return cite_by


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

    def describe(hit: object) -> str:
        """Name the evidence record in the analyst's vocabulary.

        Without this the default route — the one a plain question takes —
        produced "search_evidence returned SearchHit record <uuid>" and an
        empty data region, which is what made the agent look broken. The whole
        answer body was a list of those lines.

        The searchable text lives in ``document.fields``, not in attributes on
        the document, so a lookup by attribute name finds nothing and falls
        through to the id. The evidence index stores ``collector`` and
        ``source_type`` alongside the text, which is what actually
        distinguishes one record from another on screen.
        """
        document = getattr(hit, "document", None)
        fields = getattr(document, "fields", None)
        collector = _field(fields, "collector") or "evidence"
        source_type = _field(fields, "source_type") or "unknown source"
        when = getattr(document, "timestamp", None)
        head = f"{collector} record via {source_type}"
        if when is not None:
            stamp = when.isoformat() if hasattr(when, "isoformat") else str(when)
            return f"{head} at {stamp}"
        return head

    def render(hit: object) -> str:
        document = getattr(hit, "document", None)
        fields = getattr(document, "fields", None)
        lines = [
            f"doc_id={getattr(document, 'doc_id', '?')}",
            f"source={getattr(document, 'source', '?')}",
            f"collected_at={getattr(document, 'timestamp', '?')}",
        ]
        for key in ("collector", "source_type", "entity_type", "case_id", "artifact_uri"):
            value = _field(fields, key)
            if value is not None:
                lines.append(f"{key}={value}")
        # The score is the retrieval engine's own ranking, not a recorded
        # confidence, so it is labelled as one of the two.
        score = getattr(hit, "score", None)
        if score is not None:
            lines.append(f"relevance={score}")
        return "\n".join(lines)

    return _pack(
        tool=ToolName.SEARCH_EVIDENCE,
        items=result.hits,
        evidence_ids=evidence_ids,
        describe=describe,
        render=render,
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
        describe=_describe,
        render=_render,
        cite=_cite_by("entity_id", "label"),
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
        describe=_describe,
        render=_render,
        cite=_cite_by("entity_id", "label"),
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

    def describe(event: object) -> str:
        """Name the event and when it happened.

        The previous fallback printed "get_timeline returned TimelineEvent
        record <uuid>" with an empty data region, so the timeline — one of the
        agent's own suggested questions — answered in a form no one could read.
        """
        kind = getattr(event, "kind", "activity")
        when = getattr(event, "observed_at", None)
        detail = _first_str(event, ("summary", "description", "detail", "label"))
        head = f"{kind} at {when}" if when is not None else str(kind)
        return f"{head} — {detail}" if detail is not None else head

    def render(event: object) -> str:
        return "\n".join(
            f"{key}={value}"
            for key, value in vars(event).items()
            if not key.startswith("_") and isinstance(value, (str, int, float, bool, type(None)))
        )

    return _pack(
        tool=ToolName.GET_TIMELINE,
        items=events,
        evidence_ids=evidence_ids,
        describe=describe,
        render=render,
        # No `cite`: a timeline entry is asserted *about* its evidence, and
        # the pack's ids are what claim validation checks citations against.
        # Citing the event's own id would make every timeline claim look
        # uncited.
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
        describe=_describe,
        render=_render,
        cite=_cite_by("assessment_id", "hypothesis_id"),
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

    def describe(hypothesis: object) -> str:
        return (
            f"{getattr(hypothesis, 'kind', 'hypothesis')} hypothesis "
            f"{getattr(hypothesis, 'hypothesis_id', '?')}, status "
            f"{getattr(hypothesis, 'status', 'unknown')}, "
            f"{len(getattr(hypothesis, 'links', ()) or ())} cited records"
        )

    def render(hypothesis: object) -> str:
        links = list(getattr(hypothesis, "links", ()) or ())
        supporting = sum(
            1 for link in links if str(getattr(link, "role", "")).endswith("supporting")
        )
        against = len(links) - supporting
        return (
            f"kind={getattr(hypothesis, 'kind', '?')}\n"
            f"status={getattr(hypothesis, 'status', '?')}\n"
            f"subject={getattr(hypothesis, 'subject_entity_id', '?')}\n"
            f"object={getattr(hypothesis, 'object_entity_id', '?')}\n"
            f"supporting_citations={supporting}\n"
            f"contradicting_citations={against}"
        )

    def cite(hypothesis: object) -> Sequence[str]:
        # Cited by the hypothesis itself. Previously the claim carried the
        # first *evidence* id in the pack, so the answer read "Hypothesis
        # record <evidence-uuid>" — a citation to the wrong kind of object.
        return (str(getattr(hypothesis, "hypothesis_id", "unknown")),)

    return _pack(
        tool=ToolName.COMPARE_HYPOTHESES,
        items=tuple(sorted(hypotheses, key=lambda h: str(h.hypothesis_id))),
        evidence_ids=evidence_ids,
        describe=describe,
        render=render,
        cite=cite,
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
