"""Adapters from existing AEGIS signal producers into attribution channels.

Phase 16.2 keeps attribution orchestration thin: upstream modules continue to
own their domain-specific scoring, while this adapter only maps already-
computed pair signals into the six canonical attribution channels.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from aegis.attribution.signals import Channel, ChannelSignals
from aegis.behavior.similarity import ProfileSimilarity
from aegis.infrastructure.types import SimilarityBreakdown
from aegis.resolution.features import CandidatePairFeatures


@dataclass(frozen=True)
class AttributionSignalBundle:
    """Six-channel attribution inputs plus traceable evidence by channel."""

    signals: ChannelSignals
    evidence_ids: Mapping[Channel, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[Channel, tuple[str, ...]] = {}
        for channel, ids in self.evidence_ids.items():
            if not isinstance(channel, Channel):
                channel = Channel(channel)
            cleaned = tuple(dict.fromkeys(str(eid).strip() for eid in ids if str(eid).strip()))
            normalized[channel] = cleaned
        object.__setattr__(self, "evidence_ids", normalized)

    def evidence_for(self, channel: Channel) -> tuple[str, ...]:
        """Return deterministic evidence ids supporting one channel."""
        return self.evidence_ids.get(channel, ())

    def all_evidence_ids(self) -> tuple[str, ...]:
        """Union all channel evidence ids in canonical channel order."""
        return tuple(
            dict.fromkeys(
                evidence_id for channel in Channel for evidence_id in self.evidence_for(channel)
            )
        )


def _bundle(
    signals: ChannelSignals,
    evidence_ids: Mapping[Channel | str, Iterable[str]] | None = None,
) -> AttributionSignalBundle:
    evidence = {
        channel if isinstance(channel, Channel) else Channel(channel): tuple(ids)
        for channel, ids in (evidence_ids or {}).items()
    }
    return AttributionSignalBundle(signals=signals, evidence_ids=evidence)


def from_resolution_features(
    features: CandidatePairFeatures,
    *,
    evidence_ids: Iterable[str] = (),
) -> AttributionSignalBundle:
    """Map exact resolution signals available from Phase 09.

    Only semantically direct mappings are made here: handle similarity maps
    to ``S_h`` and temporal/behavior similarities map to their corresponding
    channels. PGP, wallet and infrastructure remain explicitly supplied by
    their own upstream evidence producers.
    """
    return _bundle(
        ChannelSignals(
            handle=features.handle_similarity,
            pgp=0.0,
            wallet=0.0,
            temporal=features.temporal_overlap,
            behavior=features.behavior_similarity,
            infrastructure=0.0,
        ),
        {
            Channel.HANDLE: evidence_ids,
            Channel.TEMPORAL: evidence_ids,
            Channel.BEHAVIOR: evidence_ids,
        },
    )


def from_behavior_similarity(
    similarity: ProfileSimilarity,
    *,
    evidence_ids: Iterable[str] = (),
) -> AttributionSignalBundle:
    """Map the Phase 12 statistical profile similarity to ``S_b``."""
    return _bundle(
        ChannelSignals(
            handle=0.0,
            pgp=0.0,
            wallet=0.0,
            temporal=0.0,
            behavior=similarity.overall,
            infrastructure=0.0,
        ),
        {Channel.BEHAVIOR: evidence_ids},
    )


def from_infrastructure_similarity(
    similarity: SimilarityBreakdown,
    *,
    evidence_ids: Iterable[str] = (),
) -> AttributionSignalBundle:
    """Map the Phase 13 infrastructure correlation score to ``S_i``."""
    return _bundle(
        ChannelSignals(
            handle=0.0,
            pgp=0.0,
            wallet=0.0,
            temporal=0.0,
            behavior=0.0,
            infrastructure=similarity.overall,
        ),
        {Channel.INFRASTRUCTURE: evidence_ids},
    )


def from_explicit_channels(
    *,
    handle: float = 0.0,
    pgp: float = 0.0,
    wallet: float = 0.0,
    temporal: float = 0.0,
    behavior: float = 0.0,
    infrastructure: float = 0.0,
    evidence_ids: Mapping[Channel | str, Iterable[str]] | None = None,
) -> AttributionSignalBundle:
    """Build a complete bundle when upstream evidence already has six scores."""
    return _bundle(
        ChannelSignals(
            handle=handle,
            pgp=pgp,
            wallet=wallet,
            temporal=temporal,
            behavior=behavior,
            infrastructure=infrastructure,
        ),
        evidence_ids,
    )
