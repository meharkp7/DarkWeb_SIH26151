import pytest

from aegis.attribution.calibration import (
    IsotonicCalibrator,
    PlattCalibrator,
    brier_score,
    calibration_by_group,
    calibrator_suite,
    expected_calibration_error,
    reliability_diagram,
)

SCORES = [0.05, 0.15, 0.25, 0.65, 0.8, 0.95]
LABELS = [0, 0, 0, 1, 1, 1]


def test_all_calibrators_fit_and_return_bounded_confidence():
    for calibrator in calibrator_suite():
        calibrator.fit(SCORES, LABELS)
        result = calibrator.calibrate(0.7)
        assert 0.0 <= result.calibrated_confidence <= 1.0
        assert result.raw_score == 0.7
        assert result.calibration_version == "calibration-0.1"


def test_isotonic_is_monotonic():
    calibrator = IsotonicCalibrator().fit(SCORES, LABELS)
    outputs = [calibrator.transform(score) for score in SCORES]
    assert outputs == sorted(outputs)


def test_metrics_are_bounded():
    assert 0.0 <= brier_score(SCORES, LABELS) <= 1.0
    assert 0.0 <= expected_calibration_error(SCORES, LABELS) <= 1.0


def test_calibration_requires_both_classes():
    with pytest.raises(ValueError):
        PlattCalibrator().fit([0.1, 0.2], [0, 0])


def test_invalid_metric_inputs_rejected():
    with pytest.raises(ValueError):
        brier_score([0.1], [0, 1])
    with pytest.raises(ValueError):
        expected_calibration_error([0.1], [0], bins=0)


def test_reliability_diagram_and_group_slices_are_plot_ready():
    diagram = reliability_diagram(SCORES, LABELS, bins=2)
    slices = calibration_by_group(SCORES, LABELS, ["low"] * 3 + ["high"] * 3)
    assert sum(item.count for item in diagram) == len(SCORES)
    assert set(slices) == {"high", "low"}
    assert slices["low"]["count"] == 3.0
