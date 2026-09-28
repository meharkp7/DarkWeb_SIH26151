"""Infrastructure evidence layer (Phase 13).

Implementation Plan section 14 ("Phase 13 --- Infrastructure Evidence")
specifies passive feature extraction over stored observations — TLS
metadata, HTTP metadata, content fingerprints, technology fingerprints,
certificate metadata, historical changes — and explicitly forbids
intrusive origin discovery.  The package honours that boundary by
construction: it imports no networking module, opens no sockets, and
operates only on in-memory payloads / canonical :class:`aegis.schemas.Evidence`
records.

Module split:

* :mod:`aegis.infrastructure.types` — validated frozen value objects
  (observation, features, breakdown, thresholds, correlation, change).
* :mod:`aegis.infrastructure.extract` — passive payload -> observation /
  feature extraction, fingerprinting via :mod:`aegis.normalization`,
  and the canonical-evidence adapter.
* :mod:`aegis.infrastructure.correlate` — channel similarities, the
  three-part decision rule, and candidate correlations carrying the
  plan's output contract (similarity, evidence IDs, time range, source,
  limitations).
* :mod:`aegis.infrastructure.history` — ordered historical change
  records bounded by observation windows (cert rotation, header /
  technology / TLS changes).

Entity and relationship vocabulary comes from :mod:`aegis.ontology` and
is never redefined here.
"""

from __future__ import annotations

from aegis.infrastructure.correlate import (
    CHANNEL_ORDER,
    CHANNEL_WEIGHTS,
    CONTENT_SIMHASH_WEIGHT,
    DEFAULT_THRESHOLDS,
    certificate_similarity,
    compare_features,
    content_similarity,
    correlate,
    correlate_all,
    http_similarity,
    normalized_content_type,
    technology_similarity,
    temporal_similarity,
    tls_similarity,
)
from aegis.infrastructure.extract import (
    content_fingerprint,
    extract_certificate_metadata,
    extract_features,
    extract_http_metadata,
    extract_observation,
    extract_technologies,
    extract_tls_metadata,
    observation_from_evidence,
    payload_from_evidence,
)
from aegis.infrastructure.history import detect_changes
from aegis.infrastructure.types import (
    CertificateMetadata,
    ChangeKind,
    ContentFingerprint,
    CorrelationError,
    CorrelationThresholds,
    ExtractionError,
    HistoricalChange,
    HTTPMetadata,
    InfrastructureCorrelation,
    InfrastructureError,
    InfrastructureFeatures,
    InfrastructureObservation,
    InfrastructureValidationError,
    SimilarityBreakdown,
    Technology,
    TimeRange,
    TLSMetadata,
)

__all__ = [
    "CHANNEL_ORDER",
    "CHANNEL_WEIGHTS",
    "CONTENT_SIMHASH_WEIGHT",
    "DEFAULT_THRESHOLDS",
    "CertificateMetadata",
    "ChangeKind",
    "ContentFingerprint",
    "CorrelationError",
    "CorrelationThresholds",
    "ExtractionError",
    "HistoricalChange",
    "HTTPMetadata",
    "InfrastructureCorrelation",
    "InfrastructureError",
    "InfrastructureFeatures",
    "InfrastructureObservation",
    "InfrastructureValidationError",
    "SimilarityBreakdown",
    "Technology",
    "TimeRange",
    "TLSMetadata",
    "certificate_similarity",
    "compare_features",
    "content_fingerprint",
    "content_similarity",
    "correlate",
    "correlate_all",
    "detect_changes",
    "extract_certificate_metadata",
    "extract_features",
    "extract_http_metadata",
    "extract_observation",
    "extract_technologies",
    "extract_tls_metadata",
    "http_similarity",
    "normalized_content_type",
    "observation_from_evidence",
    "payload_from_evidence",
    "technology_similarity",
    "temporal_similarity",
    "tls_similarity",
]
