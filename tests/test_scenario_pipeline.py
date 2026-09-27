from aegis.evaluation.scenarios import ScenarioBuilder
from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLinkEngine
from aegis.synthetic.contradiction import ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.hypothesis import AttributionHypothesisBuilder


def test_scenarios_through_attribution_pipeline():
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    scenarios = ScenarioBuilder().build(evidence)

    candidate_engine = CandidateLinkEngine()
    calibrator = ConfidenceCalibrator()
    contradiction_detector = ContradictionDetector()
    hypothesis_builder = AttributionHypothesisBuilder()

    results = {}

    for scenario in scenarios:
        candidates = candidate_engine.generate(
            list(scenario.evidence),
            min_score=0.0,
        )

        candidate = next(
            (
                item
                for item in candidates
                if {
                    item.source_actor_id,
                    item.target_actor_id,
                }
                == {
                    scenario.source_actor_id,
                    scenario.target_actor_id,
                }
            ),
            None,
        )

        assert candidate is not None

        calibrated = calibrator.calibrate(
            candidate,
            list(scenario.evidence),
        )

        contradiction = contradiction_detector.analyze(
            candidate,
            list(scenario.evidence),
        )

        hypothesis = hypothesis_builder.build(
            calibrated,
            contradiction,
            list(scenario.evidence),
        )

        results[scenario.name] = hypothesis

    assert results["clean_strong"].final_score > 0
    assert results["clean_weak"].final_score > 0

    assert (
        results["contradictory"].contradiction_score > results["clean_strong"].contradiction_score
    )

    assert results["noisy_match"].support_score < results["clean_strong"].support_score

    assert results["no_match"].final_score <= results["clean_strong"].final_score


def test_zero_candidate_score_cannot_create_calibrated_support():
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    scenarios = ScenarioBuilder().build(evidence)
    scenario = next(item for item in scenarios if item.name == "no_match")

    candidates = CandidateLinkEngine().generate(
        list(scenario.evidence),
        min_score=0.0,
    )

    candidate = next(
        item
        for item in candidates
        if {
            item.source_actor_id,
            item.target_actor_id,
        }
        == {
            scenario.source_actor_id,
            scenario.target_actor_id,
        }
    )

    assert candidate.score == 0.0

    calibrated = ConfidenceCalibrator().calibrate(
        candidate,
        list(scenario.evidence),
    )

    assert calibrated.calibrated_score == 0.0
