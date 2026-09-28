import pytest

from aegis.attribution.fusion import EvidenceContribution, EvidenceRole, fuse_evidence


def test_support_and_contradiction_are_separated():
    result = fuse_evidence(
        [
            EvidenceContribution("s1", EvidenceRole.SUPPORTING),
            EvidenceContribution("c1", EvidenceRole.CONTRADICTING),
        ]
    )
    assert result.supporting_weight == pytest.approx(1.0)
    assert result.contradictory_weight == pytest.approx(1.0)
    assert result.raw_score == pytest.approx(0.5)


def test_copied_sources_are_discounted():
    result = fuse_evidence(
        [
            EvidenceContribution("s1", EvidenceRole.SUPPORTING, independence_group="copy"),
            EvidenceContribution("s2", EvidenceRole.SUPPORTING, independence_group="copy"),
            EvidenceContribution("s3", EvidenceRole.SUPPORTING, independence_group="independent"),
        ]
    )
    assert result.supporting_weight == pytest.approx(1.5)


def test_quality_and_temporal_fit_reduce_weight():
    result = fuse_evidence(
        [
            EvidenceContribution(
                "s1", EvidenceRole.SUPPORTING, reliability=0.8, quality=0.5, temporal_fit=0.25
            ),
        ]
    )
    assert result.supporting_weight == pytest.approx(0.1)


def test_invalid_factor_rejected():
    with pytest.raises(ValueError):
        EvidenceContribution("s1", EvidenceRole.SUPPORTING, quality=1.1)
