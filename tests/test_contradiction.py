from aegis.synthetic.candidate_links import CandidateLink
from aegis.synthetic.contradiction import ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator


def _generate():
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    actor_ids = sorted({item.actor_id for item in evidence})

    candidate = CandidateLink(
        link_id="contradiction-test-link",
        source_actor_id=actor_ids[0],
        target_actor_id=actor_ids[1],
        score=0.75,
        features=(),
    )

    return evidence, candidate


def test_contradiction_analysis_is_deterministic() -> None:
    evidence, candidate = _generate()

    detector = ContradictionDetector()

    first = detector.analyze(candidate, evidence)
    second = detector.analyze(candidate, evidence)

    assert first == second


def test_contradiction_score_is_bounded() -> None:
    evidence, candidate = _generate()

    result = ContradictionDetector().analyze(
        candidate,
        evidence,
    )

    assert 0.0 <= result.contradiction_score <= 1.0


def test_contradictions_have_explanations() -> None:
    evidence, candidate = _generate()

    result = ContradictionDetector().analyze(
        candidate,
        evidence,
    )

    for contradiction in result.contradictions:
        assert contradiction.evidence_id
        assert contradiction.contradiction_type
        assert 0.0 <= contradiction.severity <= 1.0
        assert contradiction.explanation


def test_contradiction_analysis_preserves_link_id() -> None:
    evidence, candidate = _generate()

    result = ContradictionDetector().analyze(
        candidate,
        evidence,
    )

    assert result.link_id == candidate.link_id


def test_internal_conflict_is_detected() -> None:
    from aegis.evaluation.scenarios import ScenarioBuilder

    actors = SyntheticActorGenerator(seed=26151).generate(4)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    scenario = next(
        item for item in ScenarioBuilder().build(evidence) if item.name == "contradictory"
    )

    candidate = CandidateLink(
        link_id="internal-conflict-test",
        source_actor_id=scenario.source_actor_id,
        target_actor_id=scenario.target_actor_id,
        score=0.75,
        features=(),
    )

    result = ContradictionDetector().analyze(
        candidate,
        list(scenario.evidence),
    )

    assert result.contradiction_score == 0.45
    assert any(
        item.contradiction_type == "timezone_internal_conflict" for item in result.contradictions
    )
