from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLink
from aegis.synthetic.contradiction import ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.hypothesis import AttributionHypothesisBuilder


def test_hypothesis_persistence_payload_is_constructible() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    actor_ids = sorted({item.actor_id for item in evidence})

    candidate = CandidateLink(
        link_id="persistence-test",
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

    hypothesis = AttributionHypothesisBuilder().build(
        calibrated,
        contradiction,
        evidence,
    )

    assert hypothesis.status == "candidate"
    assert hypothesis.source_actor_id
    assert hypothesis.target_actor_id
    assert hypothesis.evidence
    assert 0.0 <= hypothesis.final_score <= 1.0
