from aegis.attribution.adapters import (
    from_explicit_channels,
    from_infrastructure_similarity,
    from_resolution_features,
)
from aegis.attribution.signals import Channel
from aegis.infrastructure.types import SimilarityBreakdown
from aegis.resolution.features import CandidatePairFeatures


def test_resolution_adapter_maps_only_direct_channels() -> None:
    features = CandidatePairFeatures(
        handle_similarity=0.9,
        char_ngram_similarity=0.8,
        text_similarity=0.7,
        temporal_overlap=0.6,
        shared_identifier=0.5,
        marketplace_overlap=0.4,
        behavior_similarity=0.3,
        graph_neighborhood_similarity=0.2,
        source_reliability=0.9,
    )
    bundle = from_resolution_features(features, evidence_ids=("e1", "e1"))
    assert bundle.signals.handle == 0.9
    assert bundle.signals.temporal == 0.6
    assert bundle.signals.behavior == 0.3
    assert bundle.signals.pgp == 0.0
    assert bundle.signals.wallet == 0.0
    assert bundle.signals.infrastructure == 0.0
    assert bundle.evidence_for(Channel.HANDLE) == ("e1",)


def test_infrastructure_adapter_maps_overall_score() -> None:
    breakdown = SimilarityBreakdown(
        temporal=0.8,
        overall=0.7,
        certificate=1.0,
        content=0.8,
    )
    bundle = from_infrastructure_similarity(breakdown, evidence_ids=("infra-1",))
    assert bundle.signals.infrastructure == 0.7
    assert bundle.evidence_for(Channel.INFRASTRUCTURE) == ("infra-1",)


def test_explicit_channels_preserve_channel_evidence_and_order() -> None:
    bundle = from_explicit_channels(
        handle=1.0,
        pgp=0.8,
        wallet=0.7,
        evidence_ids={
            Channel.WALLET: ("w1",),
            Channel.HANDLE: ("h1",),
            Channel.PGP: ("p1",),
        },
    )
    assert bundle.all_evidence_ids() == ("h1", "p1", "w1")
