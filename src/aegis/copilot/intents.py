"""Deterministic intent routing from an analyst question only."""

from __future__ import annotations

import re

from aegis.copilot.types import IntentKind, ParsedIntent, StructuredQuery, ToolName

_SUBJECT = re.compile(r"\b(actor|hypothesis|case):([A-Za-z0-9_.:-]+)")
_WORD = re.compile(r"[\w-]+")


def build_structured_query(question: str, *, limit: int = 10) -> StructuredQuery:
    """Parse platform-authored question text only; never inspect retrieved evidence."""
    if not question.strip():
        raise ValueError("question must be non-empty")
    subjects = tuple(f"{kind}:{value}" for kind, value in _SUBJECT.findall(question))
    subject_values = {value.casefold() for _, value in _SUBJECT.findall(question)}
    terms = tuple(
        word.casefold() for word in _WORD.findall(question) if word.casefold() not in subject_values
    )
    return StructuredQuery(terms=terms, subjects=subjects, limit=limit)


def parse_intent(question: str, *, limit: int = 10) -> ParsedIntent:
    """Route the seven Phase 22 tool intents with auditable matching rules."""
    query = build_structured_query(question, limit=limit)
    lowered = question.casefold()
    rules: tuple[tuple[tuple[str, ...], IntentKind, tuple[ToolName, ...], str], ...] = (
        (
            ("compare", "hypothesis"),
            IntentKind.HYPOTHESIS_COMPARISON,
            (ToolName.COMPARE_HYPOTHESES,),
            "compare+hypothesis",
        ),
        (
            ("report",),
            IntentKind.REPORT_BRIEF,
            (ToolName.SEARCH_EVIDENCE, ToolName.GENERATE_REPORT),
            "report",
        ),
        (("timeline", "when"), IntentKind.TIMELINE, (ToolName.GET_TIMELINE,), "timeline"),
        (
            ("assessment", "confidence"),
            IntentKind.ASSESSMENT,
            (ToolName.GET_ASSESSMENT,),
            "assessment",
        ),
        (("graph", "relationship"), IntentKind.GRAPH_QUERY, (ToolName.QUERY_GRAPH,), "graph"),
        (("actor", "profile"), IntentKind.ACTOR_PROFILE, (ToolName.GET_ACTOR,), "actor"),
    )
    for markers, intent, tools, rule in rules:
        if any(marker in lowered for marker in markers):
            return ParsedIntent(intent, query, tools, rule)
    return ParsedIntent(IntentKind.EVIDENCE_SEARCH, query, (ToolName.SEARCH_EVIDENCE,), "default")
