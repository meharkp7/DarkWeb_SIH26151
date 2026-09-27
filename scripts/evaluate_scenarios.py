from aegis.evaluation.scenarios import ScenarioBuilder
from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLinkEngine
from aegis.synthetic.contradiction import ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.hypothesis import AttributionHypothesisBuilder


def main() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    scenarios = ScenarioBuilder().build(evidence)

    candidate_engine = CandidateLinkEngine()
    calibrator = ConfidenceCalibrator()
    contradiction_detector = ContradictionDetector()
    hypothesis_builder = AttributionHypothesisBuilder()

    print(f"{'Scenario':<18}{'Raw':>8}{'Support':>10}{'Contrad.':>12}{'Final':>10}")
    print("-" * 58)

    for scenario in scenarios:
        candidates = candidate_engine.generate(
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

        print(
            f"{scenario.name:<18}"
            f"{hypothesis.raw_score:>8.3f}"
            f"{hypothesis.support_score:>10.3f}"
            f"{hypothesis.contradiction_score:>12.3f}"
            f"{hypothesis.final_score:>10.3f}"
        )


if __name__ == "__main__":
    main()
