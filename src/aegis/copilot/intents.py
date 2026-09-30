"""Deterministic intent routing from an analyst question only."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from aegis.copilot.types import IntentKind, ParsedIntent, StructuredQuery, ToolName

_SUBJECT = re.compile(r"\b(actor|hypothesis|case):([A-Za-z0-9_.:-]+)")
_WORD = re.compile(r"[\w-]+")

#: Relative windows, longest unit first so "last 2 weeks" is not read as
#: "2 weeks" of something else, and "hours" cannot match inside "hours' worth
#: of speculation" before the more specific rule gets a chance.
_RELATIVE_WINDOW = re.compile(
    r"\b(?:last|past|previous|recent)\s+"
    r"(?P<count>\d{1,3})\s*"
    r"(?P<unit>minute|hour|day|week|month)s?\b"
)
#: A bare unit with no count, e.g. "in the last week".
_BARE_WINDOW = re.compile(
    r"\b(?:last|past|previous|recent)\s+(?P<unit>minute|hour|day|week|month)\b"
)

_UNIT_SECONDS = {
    "minute": 60,
    "hour": 3600,
    "day": 86_400,
    "week": 604_800,
    "month": 2_592_000,
}

#: The widest window the copilot will infer. An unbounded "recent" would read
#: as the whole case, which is a different claim from what the analyst asked.
_MAX_WINDOW = timedelta(days=90)


def _window_bounds(question: str, *, now: datetime) -> tuple[datetime | None, datetime | None]:
    """Read a relative time window out of the question.

    The console's own timeline suggestions include "Summarize the last 24
    hours" and "When did the first activity appear". The first named a window
    the query could not express, so `since` stayed `None` and the timeline tool
    returned the entire case history — the analyst asked for a day and was
    given everything, with nothing on screen saying so.

    Only relative expressions are recognised. An absolute date is deliberately
    not inferred: reading "March" as a month boundary requires knowing which
    year, and guessing one would silently answer a different question.
    """
    match = _RELATIVE_WINDOW.search(question) or _BARE_WINDOW.search(question)
    if match is None:
        return None, None

    count = int(match.groupdict().get("count") or 1)
    unit = match.group("unit")
    seconds = _UNIT_SECONDS.get(unit)
    if seconds is None:
        return None, None

    since = now - min(timedelta(seconds=seconds * count), _MAX_WINDOW)
    return since, now


def build_structured_query(
    question: str, *, limit: int = 10, now: datetime | None = None
) -> StructuredQuery:
    """Parse platform-authored question text only; never inspect retrieved evidence."""
    if not question.strip():
        raise ValueError("question must be non-empty")
    subjects = tuple(f"{kind}:{value}" for kind, value in _SUBJECT.findall(question))
    subject_values = {value.casefold() for _, value in _SUBJECT.findall(question)}
    terms = tuple(
        word.casefold() for word in _WORD.findall(question) if word.casefold() not in subject_values
    )
    since, until = _window_bounds(question, now=now or datetime.now(UTC))
    return StructuredQuery(
        terms=terms, subjects=subjects, limit=limit, since=since, until=until
    )


def parse_intent(question: str, *, limit: int = 10, now: datetime | None = None) -> ParsedIntent:
    """Route the seven Phase 22 tool intents with auditable matching rules."""
    query = build_structured_query(question, limit=limit, now=now)
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
        # "evolve" and "history" are here because the console's own timeline tab
        # suggests "How did this investigation evolve?" — a question its router
        # did not recognise, so the one prompt offered for a temporal view fell
        # through to a plain evidence search.
        (
            ("timeline", "when", "evolve", "how did"),
            IntentKind.TIMELINE,
            (ToolName.GET_TIMELINE,),
            "timeline",
        ),
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
    # A question that named a time window is asking about time, and the
    # timeline tool is the one that can answer inside a window. Checked after
    # the explicit markers so a question that also said "compare" or "actor"
    # still takes the more specific route, but before the default so
    # "Summarize the last 24 hours" is not answered by a plain evidence search
    # that ignores the window it was given.
    if query.since is not None:
        return ParsedIntent(
            IntentKind.TIMELINE, query, (ToolName.GET_TIMELINE,), "time-window"
        )
    return ParsedIntent(IntentKind.EVIDENCE_SEARCH, query, (ToolName.SEARCH_EVIDENCE,), "default")
