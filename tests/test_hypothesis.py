from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLink
from aegis.synthetic.contradiction import (
    ContradictionAnalysis,
    ContradictionDetector,
)
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.hypothesis import AttributionHypothesisBuilder


def _generate():
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    actor_ids = sorted({item.actor_id for item in evidence})

    candidate = CandidateLink(
        link_id="test-hypothesis-link",
        source_actor_id=actor_ids[0],
        target_actor_id=actor_ids[1],
        score=0.75,
        features=(),
    )

    calibrated = ConfidenceCalibrator().calibrate(
        candidate,
        evidence,
    )

    contradiction = ContradictionDetector().analyze(
        candidate,
        evidence,
    )

    return evidence, calibrated, contradiction


def test_hypothesis_is_candidate() -> None:
    evidence, calibrated, contradiction = _generate()

    hypothesis = AttributionHypothesisBuilder().build(
        calibrated,
        contradiction,
        evidence,
    )

    assert hypothesis.status == "candidate"


def test_hypothesis_score_is_bounded() -> None:
    evidence, calibrated, contradiction = _generate()

    hypothesis = AttributionHypothesisBuilder().build(
        calibrated,
        contradiction,
        evidence,
    )

    assert 0.0 <= hypothesis.final_score <= 1.0


def test_contradictions_reduce_score() -> None:
    evidence, calibrated, contradiction = _generate()

    no_contradiction = ContradictionAnalysis(
        link_id=calibrated.link_id,
        contradictions=(),
        contradiction_score=0.0,
    )

    baseline = AttributionHypothesisBuilder().build(
        calibrated,
        no_contradiction,
        evidence,
    )

    adjusted = AttributionHypothesisBuilder().build(
        calibrated,
        contradiction,
        evidence,
    )

    assert adjusted.final_score <= baseline.final_score


def test_hypothesis_contains_supporting_evidence() -> None:
    evidence, calibrated, contradiction = _generate()

    hypothesis = AttributionHypothesisBuilder().build(
        calibrated,
        contradiction,
        evidence,
    )

    assert any(item.role == "supporting" for item in hypothesis.evidence)


def test_hypothesis_contains_explanations() -> None:
    evidence, calibrated, contradiction = _generate()

    hypothesis = AttributionHypothesisBuilder().build(
        calibrated,
        contradiction,
        evidence,
    )

    assert "support_score=" in hypothesis.explanations[0]
    assert "contradiction_score=" in hypothesis.explanations[1]
    assert "final_score=" in hypothesis.explanations[2]
