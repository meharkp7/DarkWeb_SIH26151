from aegis.attribution.fusion import EvidenceContribution
from aegis.attribution.fusion_assessment import build_fused_assessment
from aegis.attribution.signals import ChannelSignals
from aegis.schemas.hypothesis import EvidenceRole


def test_fusion_is_exposed_as_assessment_payload():
    payload = build_fused_assessment(
        hypothesis_id="h1",
        case_id="c1",
        model_id="contradiction-fusion",
        model_version="fusion-0.1",
        signals=ChannelSignals(1, 0, 1, 0, 0, 0),
        evidence=[
            EvidenceContribution("e1", EvidenceRole.SUPPORTING, independence_group="g1"),
            EvidenceContribution("e2", EvidenceRole.CONTRADICTING, independence_group="g2"),
        ],
    )
    assert payload["raw_score"] == 0.5
    assert payload["calibrated_confidence"] is None
    assert payload["calibration_version"] is None
    assert payload["supporting_evidence_ids"] == ("e1",)
    assert payload["contradictory_evidence_ids"] == ("e2",)
    assert payload["model_version"] == "fusion-0.1"
