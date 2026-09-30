from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from aegis.copilot.intents import parse_intent
from aegis.copilot.service import run_copilot
from aegis.copilot.tools import CopilotToolContext
from aegis.copilot.types import Answer, IntentKind
from aegis.graph.schema import EntityType, NodeLabel
from aegis.graph.store import InMemoryGraphStore
from aegis.schemas.evidence import Evidence
from aegis.search import IndexedDocument, InProcessSearchEngine
from aegis.timeline.types import TimelineEvent, TimelineEventKind


def test_run_copilot_routes_default_search() -> None:
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))

    answer = run_copilot(
        "find evidence about shadowbroker",
        CopilotToolContext(search=search),
    )

    assert answer.intent.intent is IntentKind.EVIDENCE_SEARCH
    assert answer.tools_run
    assert answer.pack.ids == (str(evidence.evidence_id),)
    assert answer.claims


def test_run_copilot_routes_actor_profile() -> None:
    graph = InMemoryGraphStore()
    graph.add_node(
        "shadowbroker",
        NodeLabel.ACTOR,
        entity_type=EntityType.ACTOR_HYPOTHESIS,
    )

    answer = run_copilot(
        "show actor:shadowbroker profile",
        CopilotToolContext(graph=graph),
    )

    assert answer.intent.intent is IntentKind.ACTOR_PROFILE
    assert answer.tools_run
    assert len(answer.pack.items) == 2


def test_run_copilot_report_intent_builds_a_brief_from_supported_claims() -> None:
    """The report tool is implemented, and it only prints what validation kept.

    It used to be skipped unconditionally, so `tools_run` advertised
    `generate_report`, the console showed it in its progress trail, and no
    report came back. A test asserted that as correct.
    """
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))

    answer = run_copilot(
        "create a report about shadowbroker",
        CopilotToolContext(search=search),
    )

    assert answer.intent.intent is IntentKind.REPORT_BRIEF
    assert answer.tools_run[-1].value == "generate_report"
    assert answer.report is not None
    # Built from the answer's validated claims, so the brief and the answer
    # cannot disagree about what was supported.
    assert answer.report.claim_texts == tuple(
        claim.text for claim in answer.validation.supported_claims
    )
    assert answer.report.evidence_ids == answer.pack.ids
    assert answer.report.sections


def test_a_report_is_none_when_nothing_survived_validation() -> None:
    """An empty brief is a document; no brief is an honest answer.

    Returning a report with zero sections would present the analyst with
    something that looks like the report they asked for, produced from
    nothing.
    """
    answer = run_copilot("create a report", CopilotToolContext())

    assert answer.report is None
    assert not answer.validation.supported_claims


def test_a_report_never_contains_a_claim_validation_rejected() -> None:
    """The containment property, asserted on the report builder itself.

    Rejection is unreachable through `run_copilot` — synthesis always cites an
    id that is in the pack, so nothing is ever dropped in practice. That makes
    it exactly the kind of guarantee that decays unnoticed: the invariant is
    only real if something tests it directly, so this constructs the partition
    by hand.
    """
    from aegis.copilot.report import build_report
    from aegis.copilot.types import (
        CitationValidation,
        Claim,
        ClaimStatus,
        EvidenceItem,
        EvidencePack,
        ToolName,
        ValidatedClaim,
    )

    kept = Claim("The handle appeared on two forums.", ("e1",), origin="tool:search_evidence")
    no_citation = Claim("This needs no evidence.", (), origin="tool:search_evidence")
    wrong_id = Claim(
        "Cites a record that does not exist.", ("nope",), origin="tool:search_evidence"
    )

    pack = EvidencePack(
        (
            EvidenceItem(
                item_id="e1",
                tool=ToolName.SEARCH_EVIDENCE,
                kind="Evidence",
                summary=kept.text,
                data_text="",
            ),
        )
    )
    answer = Answer(
        question="q",
        intent=parse_intent("q"),
        pack=pack,
        validation=CitationValidation(
            supported=(ValidatedClaim(kept, ClaimStatus.SUPPORTED, "all citations resolve"),),
            unsupported=(
                ValidatedClaim(no_citation, ClaimStatus.UNSUPPORTED, "claim has no citations"),
            ),
            dropped=(ValidatedClaim(wrong_id, ClaimStatus.DROPPED, "unknown citation ids: nope"),),
        ),
        text="",
    )

    report = build_report(answer)
    assert report is not None
    assert report.claim_texts == (kept.text,)
    assert no_citation.text not in report.claim_texts
    assert wrong_id.text not in report.claim_texts


def test_a_report_with_nothing_supported_is_none() -> None:
    from aegis.copilot.report import build_report
    from aegis.copilot.types import (
        CitationValidation,
        Claim,
        ClaimStatus,
        EvidencePack,
        ValidatedClaim,
    )

    rejected = Claim("Unsupported.", (), origin="tool:search_evidence")
    answer = Answer(
        question="q",
        intent=parse_intent("q"),
        pack=EvidencePack(),
        validation=CitationValidation(
            supported=(),
            unsupported=(ValidatedClaim(rejected, ClaimStatus.UNSUPPORTED, "no citations"),),
            dropped=(),
        ),
        text="",
    )

    assert build_report(answer) is None


def test_an_unavailable_tool_degrades_instead_of_raising() -> None:
    """A question the analyst was entitled to ask must not become a 500.

    The graph is only built for a case-scoped request, so asking "trace
    actor:x" from the platform-wide context raised `RuntimeError` straight out
    of the service and the endpoint answered 500. A missing optional adapter is
    a capability limit, and the synthesis layer already states it truthfully.
    """
    answer = run_copilot("trace actor:shadowbroker", CopilotToolContext())

    # The question is still recognised and the tool that would answer it is
    # still named; only the tool contributes nothing, which is the capability
    # limit the analyst needs to see. What matters is that this is a 200 with a
    # stated answer rather than an exception out of the service.
    assert answer.intent.intent is IntentKind.ACTOR_PROFILE
    assert answer.tools_run
    assert answer.pack.items == ()
    assert answer.text.strip() != ""
    assert "Traceback" not in answer.text


def test_an_unknown_id_degrades_instead_of_raising() -> None:
    """A wrong hypothesis id is a normal outcome, not a server fault.

    `compare_hypotheses` raises `LookupError` for an id that is not in scope.
    That is a question with a bad premise, so the answer is an empty
    comparison — not an exception that surfaces as a server error.
    """
    answer = run_copilot(f"compare hypothesis:{uuid4()}", CopilotToolContext(hypotheses=()))

    assert answer.intent.intent is IntentKind.HYPOTHESIS_COMPARISON
    assert answer.pack.items == ()


def test_the_case_timeline_is_reachable_without_typing_an_id() -> None:
    """`load_timeline` stamps every event with the case, so the case is the subject.

    "How did this investigation evolve" names no subject, so the timeline tool
    used to match none and return nothing — a question the console itself
    suggests, unanswerable by construction.
    """
    search = InProcessSearchEngine()
    evidence = Evidence.example()
    search.index(IndexedDocument.from_evidence(evidence))
    case_id = uuid4()

    answer = run_copilot(
        "timeline of this investigation",
        CopilotToolContext(
            search=search,
            timeline=(
                TimelineEvent(
                    "ev-1",
                    str(case_id),
                    TimelineEventKind.HANDLE,
                    datetime(2026, 1, 2, tzinfo=UTC),
                    "a new handle appeared",
                    (str(evidence.evidence_id),),
                ),
            ),
        ),
    )

    assert "get_timeline" in [tool.value for tool in answer.tools_run]
    assert any(item.tool.value == "get_timeline" for item in answer.pack.items)


def test_a_confidence_question_with_no_id_uses_the_cases_leading_assessment() -> None:
    """The console's own assessment prompt names no id, so none may be required.

    "What evidence is driving this confidence?" is the suggestion the
    assessment tab offers. `get_assessment` needs a UUID, so the question
    matched no subject and answered "No evidence-backed findings were
    retrieved" — indistinguishable from a case with no assessment, while the
    case held twenty-eight.
    """
    from aegis.db.models import AssessmentRecord

    class _StubAssessments:
        def get(self, assessment_id: UUID) -> AssessmentRecord | None:
            return AssessmentRecord(
                assessment_id=assessment_id,
                hypothesis_id=uuid4(),
                case_id=uuid4(),
                model_id="stub",
                model_version="0",
                raw_score=0.5,
                calibrated_confidence=0.71,
                supporting_evidence_ids=[uuid4()],
                contradictory_evidence_ids=[],
            )

    lead = uuid4()
    answer = run_copilot(
        "What evidence is driving this confidence?",
        CopilotToolContext(
            assessments=_StubAssessments(),  # type: ignore[arg-type]
            leading_assessment=lead,
        ),
    )

    assert answer.intent.intent is IntentKind.ASSESSMENT
    assert any(item.tool.value == "get_assessment" for item in answer.pack.items)
    # The claim must cite the leading assessment, not a placeholder.
    assert str(lead) in answer.pack.ids


def test_a_named_actor_is_not_answered_with_the_leading_assessment() -> None:
    """A near-miss subject must not be answered with a different assessment.

    Falling back whenever the subject is unparsable would answer "what is
    shadowbroker's confidence?" with the case's strongest hypothesis, which
    looks like an answer and is not one.
    """
    from aegis.db.models import AssessmentRecord

    class _ShouldNotBeCalled:
        def get(self, assessment_id: UUID) -> AssessmentRecord | None:
            raise AssertionError("the leading assessment must not be used for a named subject")

    answer = run_copilot(
        "what is actor:shadowbroker's confidence?",
        CopilotToolContext(assessments=_ShouldNotBeCalled()),  # type: ignore[arg-type]
    )

    assert answer.pack.items == ()


def test_no_id_and_no_leading_assessment_answers_nothing() -> None:
    answer = run_copilot(
        "What evidence is driving this confidence?",
        CopilotToolContext(),
    )

    assert answer.intent.intent is IntentKind.ASSESSMENT
    assert answer.pack.items == ()
