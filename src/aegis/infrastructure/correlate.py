"""Candidate correlation of infrastructure observations (Phase 13).

Implementation Plan section 14 requires the correlation output to carry
*candidate correlation, similarity, evidence IDs, time range, source,
limitations* and to "test false correlations using unrelated
infrastructure".  This module compares two frozen
:class:`~aegis.infrastructure.types.InfrastructureFeatures` views and
emits an :class:`~aegis.infrastructure.types.InfrastructureCorrelation`
only when all three conditions hold:

1.  the observation windows **overlap in time** (metadata seen at
    disjoint times cannot be shown to coexist);
2.  the weighted overall similarity clears
    :attr:`CorrelationThresholds.min_similarity`; and
3.  at least one *strong channel* — certificate equality,
    near-duplicate content, or a near-identical HTTP header profile —
    clears its own cutoff.

Commodity signals (TLS configuration, technology stacks) contribute
weight but can never trigger a candidate on their own: unrelated
services routinely run the same nginx/PHP stack and the same TLS
settings, and Phase 13 must not report those as shared infrastructure.

Every correlation records explicit ``limitations`` stating what it does
NOT prove.  Nothing in this module performs network I/O — comparison is
pure arithmetic over already-extracted features.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Final

from aegis.infrastructure.types import (
    CertificateMetadata,
    ContentFingerprint,
    CorrelationError,
    CorrelationThresholds,
    HTTPMetadata,
    InfrastructureCorrelation,
    InfrastructureFeatures,
    SimilarityBreakdown,
    TimeRange,
    TLSMetadata,
)
from aegis.normalization import hamming_distance, jaccard_from_signatures, jaccard_sets
from aegis.ontology import RelationshipType

#: Channel weights of the overall similarity.  The weighted mean is
#: normalised by the weights of the *available* channels, so the
#: absolute sum is irrelevant — but the prior ranking matters:
#: identity-bearing signals (certificate, content) dominate.
CHANNEL_WEIGHTS: Final[Mapping[str, float]] = {
    "certificate": 0.30,
    "content": 0.25,
    "technology": 0.15,
    "http": 0.15,
    "tls": 0.10,
    "temporal": 0.05,
}

#: Fixed channel evaluation order (deterministic breakdowns).
CHANNEL_ORDER: Final[tuple[str, ...]] = (
    "certificate",
    "content",
    "technology",
    "http",
    "tls",
    "temporal",
)

#: Weight of the SimHash half of content similarity (the MinHash
#: Jaccard estimate takes the remainder).
CONTENT_SIMHASH_WEIGHT: Final[float] = 0.5

#: Default decision rule; callers may pass their own thresholds.
DEFAULT_THRESHOLDS: Final[CorrelationThresholds] = CorrelationThresholds()


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("_mean requires at least one value")
    return sum(values) / len(values)


# ------------------------------------------------------------ channel similarity


def certificate_similarity(left: CertificateMetadata, right: CertificateMetadata) -> float:
    """Certificate identity in ``[0, 1]``.

    Identical fingerprints are an exact match (``1.0``); a shared SPKI
    (re-issued certificate, same key) scores ``0.9``; otherwise the score
    is the mean agreement over subject, issuer, and SAN Jaccard — the
    parts comparable on both sides.  Unrelated certificates from
    different CAs with different subjects and SANs score ``0.0``.
    """
    if left.fingerprint_sha256 == right.fingerprint_sha256:
        return 1.0
    if (
        left.spki_sha256 is not None
        and right.spki_sha256 is not None
        and left.spki_sha256 == right.spki_sha256
    ):
        return 0.9
    comparisons = [
        1.0 if left.subject.casefold() == right.subject.casefold() else 0.0,
        1.0 if left.issuer.casefold() == right.issuer.casefold() else 0.0,
    ]
    if left.sans or right.sans:
        comparisons.append(jaccard_sets(left.sans, right.sans))
    return _mean(comparisons)


def tls_similarity(left: TLSMetadata, right: TLSMetadata) -> float:
    """TLS configuration agreement over the fields both sides expose."""
    comparisons = [
        1.0 if left.version.casefold() == right.version.casefold() else 0.0,
    ]
    if left.cipher_suite is not None and right.cipher_suite is not None:
        comparisons.append(
            1.0 if left.cipher_suite.casefold() == right.cipher_suite.casefold() else 0.0
        )
    if left.alpn and right.alpn:
        comparisons.append(jaccard_sets(left.alpn, right.alpn))
    if left.ja3 is not None and right.ja3 is not None:
        comparisons.append(1.0 if left.ja3 == right.ja3 else 0.0)
    return _mean(comparisons)


def normalized_content_type(content_type: str) -> str:
    """Media type without parameters, case-folded (``text/html; ...`` -> ``text/html``)."""
    return content_type.split(";")[0].strip().casefold()


def http_similarity(left: HTTPMetadata, right: HTTPMetadata) -> float | None:
    """Header-profile agreement in ``[0, 1]``, or ``None`` when uncomparable.

    Compares header *names* (Jaccard, skipped when either side recorded
    no headers — absence is missing data, not disagreement), the
    ``server`` product token, and the normalised content type.
    ``status_code`` is deliberately excluded: it is path-dependent.
    """
    comparisons: list[float] = []
    if left.headers and right.headers:
        comparisons.append(jaccard_sets(left.header_names, right.header_names))
    if left.server is not None and right.server is not None:
        comparisons.append(1.0 if left.server.casefold() == right.server.casefold() else 0.0)
    if left.content_type is not None and right.content_type is not None:
        comparisons.append(
            1.0
            if normalized_content_type(left.content_type)
            == normalized_content_type(right.content_type)
            else 0.0
        )
    if not comparisons:
        return None
    return _mean(comparisons)


def technology_similarity(left: frozenset[str], right: frozenset[str]) -> float | None:
    """Jaccard of canonical technology keys; ``None`` when neither side reports any."""
    if not left and not right:
        return None
    return jaccard_sets(left, right)


def content_similarity(left: ContentFingerprint, right: ContentFingerprint) -> float:
    """Near-duplicate content score in ``[0, 1]``.

    Mean of the SimHash similarity (``1 - hamming/64``) and the MinHash
    Jaccard estimate, both from :mod:`aegis.normalization`.  Unrelated
    bodies land near ``0.25`` (random SimHashes are half-similar by
    construction while their MinHash Jaccard is ~0), so the ``0.8``
    strong-channel cutoff has wide separation from noise.
    """
    simhash_score = 1.0 - hamming_distance(left.simhash, right.simhash) / 64.0
    jaccard_score = jaccard_from_signatures(left.minhash, right.minhash)
    return CONTENT_SIMHASH_WEIGHT * simhash_score + (1.0 - CONTENT_SIMHASH_WEIGHT) * jaccard_score


def temporal_similarity(left: TimeRange, right: TimeRange) -> float:
    """Overlap of the two observation windows over the shorter duration."""
    return left.overlap_similarity(right)


# ------------------------------------------------------------------- comparison


def compare_features(
    left: InfrastructureFeatures, right: InfrastructureFeatures
) -> SimilarityBreakdown:
    """Score every channel and the weighted ``overall`` for one pair.

    Unavailable channels (``None``) are dropped from the weighted mean
    together with their weights, so missing metadata never counts as
    either agreement or disagreement.
    """
    for side, features in (("left", left), ("right", right)):
        if not isinstance(features, InfrastructureFeatures):
            raise CorrelationError(
                f"{side} must be InfrastructureFeatures, got {type(features).__name__}"
            )
    certificate: float | None = None
    if left.observation.certificate is not None and right.observation.certificate is not None:
        certificate = certificate_similarity(
            left.observation.certificate, right.observation.certificate
        )
    content: float | None = None
    if left.content is not None and right.content is not None:
        content = content_similarity(left.content, right.content)
    http: float | None = None
    if left.observation.http is not None and right.observation.http is not None:
        http = http_similarity(left.observation.http, right.observation.http)
    tls: float | None = None
    if left.observation.tls is not None and right.observation.tls is not None:
        tls = tls_similarity(left.observation.tls, right.observation.tls)
    temporal = temporal_similarity(left.observed_range, right.observed_range)
    channels: dict[str, float | None] = {
        "certificate": certificate,
        "content": content,
        "technology": technology_similarity(left.technology_keys, right.technology_keys),
        "http": http,
        "tls": tls,
        "temporal": temporal,
    }
    available: dict[str, float] = {}
    for name in CHANNEL_ORDER:
        value = channels[name]
        if value is not None:
            available[name] = value
    weight_sum = sum(CHANNEL_WEIGHTS[name] for name in available)
    overall = (
        sum(CHANNEL_WEIGHTS[name] * value for name, value in available.items()) / weight_sum
        if weight_sum > 0.0
        else 0.0
    )
    return SimilarityBreakdown(
        temporal=temporal,
        overall=overall,
        certificate=certificate,
        content=content,
        technology=channels["technology"],
        http=http,
        tls=tls,
    )


# ----------------------------------------------------------------- correlation


def _channel_limitations(breakdown: SimilarityBreakdown) -> list[str]:
    """Missing-channel disclosures: what did NOT contribute to the score."""
    labels = {
        "certificate": "certificate metadata",
        "content": "body content",
        "technology": "technology fingerprints",
        "http": "HTTP metadata",
        "tls": "TLS metadata",
    }
    notes: list[str] = []
    for name in CHANNEL_ORDER:
        if name == "temporal":
            continue
        if getattr(breakdown, name) is None:
            notes.append(
                f"Comparable {labels[name]} was not observed on both sides; "
                f"the {name} channel did not contribute to the score."
            )
    return notes


def _strong_channel_limitation(strong_channel: str) -> str:
    caveats = {
        "certificate": (
            "A matching certificate links the observations to one certificate, which "
            "mirrors, migrations, and shared hosting can also produce; it does not "
            "establish common control."
        ),
        "content": (
            "Near-duplicate content shows mirrored material, not who operates each "
            "endpoint; scraped or templated pages can coincide."
        ),
        "http": (
            "Header profiles are easily replicated and are frequently identical across "
            "unrelated default deployments of the same software."
        ),
    }
    return caveats[strong_channel]


def _correlation_limitations(
    breakdown: SimilarityBreakdown,
    *,
    strong_channel: str,
    time_range: TimeRange,
    overlaps: bool,
    sources: tuple[str, ...],
) -> tuple[str, ...]:
    notes = [
        "Passive metadata similarity only: shared infrastructure does not establish "
        "common control, ownership, or operation of the two subjects.",
        "Derived from stored observations with no intrusive origin discovery, scanning, "
        "or probing (Implementation Plan section 14).",
        "A candidate correlation for analyst review — not an attribution conclusion.",
        _strong_channel_limitation(strong_channel),
    ]
    notes.extend(_channel_limitations(breakdown))
    if overlaps:
        notes.append(
            f"Similarity is evidenced only for {time_range.start.isoformat()} -- "
            f"{time_range.end.isoformat()}; behaviour of either subject outside that "
            "window is unverified."
        )
    else:
        notes.append(
            "Observation windows do not overlap: the time range spans both windows and "
            "does not imply the two configurations were ever simultaneously active."
        )
    if len(sources) == 1:
        notes.append(
            f"Both observations originate from source '{sources[0]}'; the corroboration "
            "is not independent."
        )
    else:
        notes.append(
            "Observations originate from distinct sources; source independence is "
            "assumed, not verified."
        )
    return tuple(notes)


def correlate(
    left: InfrastructureFeatures,
    right: InfrastructureFeatures,
    *,
    thresholds: CorrelationThresholds = DEFAULT_THRESHOLDS,
) -> InfrastructureCorrelation | None:
    """Candidate correlation between two observations, or ``None``.

    Returns ``None`` — rather than a low-scoring record — whenever the
    pair fails the temporal gate, the overall floor, or the
    strong-channel requirement, so downstream consumers only ever see
    records that passed the full decision rule.
    """
    if not isinstance(thresholds, CorrelationThresholds):
        raise CorrelationError(
            f"thresholds must be CorrelationThresholds, got {type(thresholds).__name__}"
        )
    breakdown = compare_features(left, right)
    if thresholds.require_temporal_overlap and breakdown.temporal <= 0.0:
        return None
    if breakdown.temporal < thresholds.min_temporal_overlap:
        return None
    if breakdown.overall < thresholds.min_similarity:
        return None
    strong_channel = thresholds.strong_channel(breakdown)
    if strong_channel is None:
        return None
    if left.observation_id <= right.observation_id:
        first, second = left, right
    else:
        first, second = right, left
    intersection = first.observed_range.intersection(second.observed_range)
    overlaps = intersection is not None
    time_range = (
        intersection
        if intersection is not None
        else first.observed_range.union(second.observed_range)
    )
    sources = tuple(sorted({first.source, second.source}))
    evidence_ids = tuple(sorted(set(first.evidence_ids) | set(second.evidence_ids)))
    limitations = _correlation_limitations(
        breakdown,
        strong_channel=strong_channel,
        time_range=time_range,
        overlaps=overlaps,
        sources=sources,
    )
    relationship = (
        RelationshipType.CERTIFICATE_ASSOCIATED_WITH
        if strong_channel == "certificate"
        else RelationshipType.INFRASTRUCTURE_SIMILAR_TO
    )
    return InfrastructureCorrelation(
        left_observation_id=first.observation_id,
        right_observation_id=second.observation_id,
        left_subject=first.subject,
        right_subject=second.subject,
        similarity=breakdown.overall,
        breakdown=breakdown,
        evidence_ids=evidence_ids,
        time_range=time_range,
        sources=sources,
        limitations=limitations,
        strong_channel=strong_channel,
        relationship_type=relationship,
    )


def correlate_all(
    observations: Sequence[InfrastructureFeatures],
    *,
    thresholds: CorrelationThresholds = DEFAULT_THRESHOLDS,
) -> tuple[InfrastructureCorrelation, ...]:
    """Score every distinct pair once and return the passing candidates.

    Endpoints are canonically ordered inside each record, and the result
    is sorted by descending similarity (observation ids break ties), so
    repeated runs over the same inputs are byte-identical.  Duplicate
    observation ids are rejected: they would silently collapse two
    different subjects into one endpoint.
    """
    ids = [features.observation_id for features in observations]
    if len(set(ids)) != len(ids):
        duplicates = sorted({oid for oid in ids if ids.count(oid) > 1})
        raise CorrelationError(f"duplicate observation ids: {', '.join(duplicates)}")
    results: list[InfrastructureCorrelation] = []
    for first, second in combinations(observations, 2):
        record = correlate(first, second, thresholds=thresholds)
        if record is not None:
            results.append(record)
    results.sort(
        key=lambda item: (-item.similarity, item.left_observation_id, item.right_observation_id)
    )
    return tuple(results)
