from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLink, CandidateLinkEngine
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator


def _generate():
    actors = SyntheticActorGenerator(seed=26151).generate(3)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    candidates = CandidateLinkEngine().generate(
        evidence,
        min_score=0.0,
    )

    return evidence, candidates


def test_calibration_is_deterministic() -> None:
    evidence, candidates = _generate()

    assert candidates

    calibrator = ConfidenceCalibrator()

    first = calibrator.calibrate(candidates[0], evidence)
    second = calibrator.calibrate(candidates[0], evidence)

    assert first == second


def test_calibrated_score_is_bounded() -> None:
    evidence, candidates = _generate()

    calibrator = ConfidenceCalibrator()

    for candidate in candidates:
        result = calibrator.calibrate(candidate, evidence)

        assert 0.0 <= result.raw_score <= 1.0
        assert 0.0 <= result.calibrated_score <= 1.0


def test_calibration_contains_independence_groups() -> None:
    evidence, candidates = _generate()

    assert candidates

    result = ConfidenceCalibrator().calibrate(
        candidates[0],
        evidence,
    )

    assert result.contributions

    groups = {contribution.independence_group for contribution in result.contributions}

    assert groups


def test_calibration_preserves_evidence_ids() -> None:
    evidence, candidates = _generate()

    assert candidates

    result = ConfidenceCalibrator().calibrate(
        candidates[0],
        evidence,
    )

    result_ids = {
        evidence_id
        for contribution in result.contributions
        for evidence_id in contribution.evidence_ids
    }

    expected_ids = {
        item.evidence_id
        for item in evidence
        if item.actor_id
        in {
            candidates[0].source_actor_id,
            candidates[0].target_actor_id,
        }
    }

    assert result_ids == expected_ids


def test_calibration_handles_explicit_candidate() -> None:
    evidence, _ = _generate()

    actors = sorted({item.actor_id for item in evidence})

    candidate = CandidateLink(
        link_id="explicit-test-link",
        source_actor_id=actors[0],
        target_actor_id=actors[1],
        score=0.75,
        features=(),
    )

    result = ConfidenceCalibrator().calibrate(
        candidate,
        evidence,
    )

    assert result.link_id == "explicit-test-link"
    assert result.raw_score == 0.75
    assert result.contributions
