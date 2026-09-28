"""Phase 17.2 integration of contradiction-aware fusion with attribution assessments."""

from __future__ import annotations

from aegis.attribution.fusion import EvidenceContribution, FusionResult, fuse_evidence
from aegis.attribution.signals import ChannelSignals


def build_fused_assessment(
    *,
    hypothesis_id: str,
    case_id: str,
    model_id: str,
    model_version: str,
    signals: ChannelSignals,
    evidence: list[EvidenceContribution],
    alpha: float = 1.0,
    beta: float = 1.0,
) -> dict[str, object]:
    """Build an AttributionAssessment-compatible payload with fusion output.

    raw_score remains explicitly non-calibrated. Phase 18 owns calibrated confidence.
    """
    result: FusionResult = fuse_evidence(evidence, alpha=alpha, beta=beta)
    return {
        "hypothesis_id": hypothesis_id,
        "case_id": case_id,
        "model_id": model_id,
        "model_version": model_version,
        "raw_score": result.raw_score,
        "calibrated_confidence": None,
        "calibration_version": None,
        "signals": signals.as_dict(),
        "supporting_evidence_ids": result.supporting_evidence_ids,
        "contradictory_evidence_ids": result.contradictory_evidence_ids,
        "explanations": {
            "supporting_weight": result.supporting_weight,
            "contradictory_weight": result.contradictory_weight,
            "unknown_weight": result.unknown_weight,
        },
        "limitations": [
            "raw_score is not a calibrated probability",
            "calibration is deferred to Phase 18",
        ],
    }
