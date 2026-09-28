from uuid import uuid4

from aegis.attribution.persistence import AttributionAssessmentPersistenceService
from aegis.schemas.hypothesis import AttributionAssessment


def assessment() -> AttributionAssessment:
    return AttributionAssessment(
        hypothesis_id=uuid4(),
        case_id=uuid4(),
        model_id="transparent-fusion",
        model_version="baseline-0.1",
        raw_score=0.84,
        signals={"S_h": 1.0, "S_w": 0.6},
        supporting_evidence_ids=(uuid4(),),
        contradictory_evidence_ids=(uuid4(),),
        explanations=("Two independent channels support the hypothesis.",),
        limitations=("Calibration has not been applied.",),
    )


def test_assessment_maps_to_existing_persistence_model() -> None:
    payload = assessment()
    record = AttributionAssessmentPersistenceService.to_record(payload)

    assert record.assessment_id == payload.assessment_id
    assert record.hypothesis_id == payload.hypothesis_id
    assert record.case_id == payload.case_id
    assert record.model_id == "transparent-fusion"
    assert record.model_version == "baseline-0.1"
    assert record.raw_score == 0.84
    assert record.calibrated_confidence is None
    assert record.signals_json == {"S_h": 1.0, "S_w": 0.6}
    assert record.supporting_evidence_ids == list(payload.supporting_evidence_ids)
    assert record.contradictory_evidence_ids == list(payload.contradictory_evidence_ids)


def test_calibrated_assessment_preserves_calibration_metadata() -> None:
    payload = assessment().model_copy(
        update={"calibrated_confidence": 0.81, "calibration_version": "platt-0.1"}
    )
    record = AttributionAssessmentPersistenceService.to_record(payload)

    assert record.calibrated_confidence == 0.81
    assert record.calibration_version == "platt-0.1"
