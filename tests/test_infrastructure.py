"""Phase 13 infrastructure-evidence tests.

Covers the plan's six passive feature families (TLS metadata, HTTP
metadata, content fingerprints, technology fingerprints, certificate
metadata, historical changes), the correlation output contract
(candidate correlation + similarity + evidence IDs + time range +
source + limitations), the plan's explicit false-correlation
requirement (unrelated infrastructure must NOT correlate), historical
change ordering, and the defensive validation of every value object.

The suite also proves the passive-only boundary: the package's source
must import no networking module (no socket, ssl, httpx, requests,
urllib, subprocess, ...), so intrusive origin discovery is impossible
by construction rather than by convention.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

import aegis.infrastructure
from aegis.infrastructure import (
    CHANNEL_WEIGHTS,
    DEFAULT_THRESHOLDS,
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
    certificate_similarity,
    compare_features,
    content_fingerprint,
    content_similarity,
    correlate,
    correlate_all,
    detect_changes,
    extract_certificate_metadata,
    extract_features,
    extract_http_metadata,
    extract_observation,
    extract_technologies,
    extract_tls_metadata,
    http_similarity,
    normalized_content_type,
    observation_from_evidence,
    payload_from_evidence,
    technology_similarity,
    temporal_similarity,
    tls_similarity,
)
from aegis.normalization import content_hash
from aegis.ontology import (
    ENTITY_CATEGORIES,
    RELATIONSHIP_DIRECTION,
    EntityCategory,
    EntityType,
    RelationDirection,
    RelationshipType,
)
from aegis.schemas import Evidence, SourceType

# ----------------------------------------------------------------- fixtures

DAY_ONE = datetime(2026, 1, 1, tzinfo=UTC)


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "observation_id": "obs-1",
        "evidence_ids": ["ev-1"],
        "subject": "alpha.onion",
        "subject_type": "onion_service",
        "source": "source-a",
        "observed_range": {
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-03-31T00:00:00+00:00",
        },
    }
    payload.update(overrides)
    return payload


def _observation(**overrides: object) -> InfrastructureObservation:
    return extract_observation(_payload(**overrides))


def _features(**overrides: object) -> InfrastructureFeatures:
    return extract_features(_observation(**overrides))


#: Certificate family in payload form (the extract layer reads mappings).
CERTIFICATE_PAYLOAD: dict[str, object] = {
    "fingerprint_sha256": "a" * 64,
    "subject": "CN=alpha.onion",
    "issuer": "CN=R3",
    "serial_number": "01",
    "sans": ["alpha.onion"],
}


def _certificate(**overrides: object) -> CertificateMetadata:
    fields: dict[str, object] = {
        "fingerprint_sha256": "a" * 64,
        "subject": "CN=alpha.onion",
        "issuer": "CN=R3",
        "serial_number": "01",
        "sans": ["alpha.onion"],
    }
    fields.update(overrides)
    return CertificateMetadata(**fields)  # type: ignore[arg-type]


def _tls(**overrides: object) -> TLSMetadata:
    fields: dict[str, object] = {
        "version": "TLSv1.3",
        "cipher_suite": "TLS_AES_128_GCM_SHA256",
        "alpn": ("h2", "http/1.1"),
        "ja3": "ab" * 16,
    }
    fields.update(overrides)
    return TLSMetadata(**fields)  # type: ignore[arg-type]


def _http(**overrides: object) -> HTTPMetadata:
    fields: dict[str, object] = {
        "status_code": 200,
        "server": "nginx/1.18.0",
        "content_type": "text/html; charset=utf-8",
        "headers": {
            "Server": "nginx/1.18.0",
            "Content-Type": "text/html",
            "Connection": "keep-alive",
            "X-Powered-By": "PHP/8.1",
        },
    }
    fields.update(overrides)
    return HTTPMetadata(**fields)  # type: ignore[arg-type]


#: The two observations of one service behind two subjects: same
#: certificate, stack, header profile, and near-identical body, with
#: overlapping (but distinct) observation windows.
POSITIVE_A = {
    "observation_id": "obs-a",
    "evidence_ids": ["ev-a"],
    "subject": "alpha.onion",
    "subject_type": "onion_service",
    "source": "dir-alpha",
    "observed_range": {
        "start": "2026-01-01T00:00:00+00:00",
        "end": "2026-03-31T00:00:00+00:00",
    },
    "tls": {
        "version": "TLSv1.3",
        "cipher_suite": "TLS_AES_128_GCM_SHA256",
        "alpn": ["h2", "http/1.1"],
        "ja3": "ab" * 16,
    },
    "http": {
        "status_code": 200,
        "server": "nginx/1.18.0",
        "content_type": "text/html; charset=utf-8",
        "headers": {
            "Server": "nginx/1.18.0",
            "Content-Type": "text/html",
            "Connection": "keep-alive",
            "X-Powered-By": "PHP/8.1",
        },
    },
    "certificate": {
        "fingerprint_sha256": "a" * 64,
        "subject": "CN=alpha.onion",
        "issuer": "CN=R3",
        "serial_number": "01",
        "sans": ["alpha.onion"],
    },
    "technologies": ["nginx:1.18", "php:8.1"],
    "body": "Alpha marketplace home page. Trusted vendors only. Escrow protected trading.",
}
POSITIVE_B = {
    **POSITIVE_A,
    "observation_id": "obs-b",
    "evidence_ids": ["ev-b"],
    "subject": "alpha-mirror.example",
    "subject_type": "domain",
    "source": "scan-beta",
    "observed_range": {
        "start": "2026-02-01T00:00:00+00:00",
        "end": "2026-04-30T00:00:00+00:00",
    },
    "body": "Alpha marketplace home page. Trusted vendors only. Escrow protected deals.",
}


def _positive_a() -> InfrastructureFeatures:
    return extract_features(extract_observation(dict(POSITIVE_A)))


def _positive_b() -> InfrastructureFeatures:
    return extract_features(extract_observation(dict(POSITIVE_B)))


#: Two unrelated services: different certificates, issuers, SANs,
#: stacks, header profiles, TLS configuration, bodies, and subjects.
UNRELATED_X = {
    "observation_id": "obs-x",
    "evidence_ids": ["ev-x"],
    "subject": "beta.onion",
    "subject_type": "onion_service",
    "source": "dir-x",
    "observed_range": {
        "start": "2026-05-01T00:00:00+00:00",
        "end": "2026-06-30T00:00:00+00:00",
    },
    "tls": {"version": "TLSv1.2", "cipher_suite": "ECDHE-RSA-AES128-GCM-SHA256", "ja3": "cd" * 16},
    "http": {
        "status_code": 200,
        "server": "apache/2.4.41",
        "content_type": "text/html",
        "headers": {"Server": "apache/2.4.41", "X-Powered-By": "PHP/7.4"},
    },
    "certificate": {
        "fingerprint_sha256": "c" * 64,
        "subject": "CN=beta.onion",
        "issuer": "CN=ZeroSSL",
        "serial_number": "aa",
        "sans": ["beta.onion"],
    },
    "technologies": ["apache:2.4.41", "php:7.4"],
    "body": "Beta forum index. Discussion boards and user avatars.",
}
UNRELATED_Y = {
    **UNRELATED_X,
    "observation_id": "obs-y",
    "evidence_ids": ["ev-y"],
    "subject": "gamma.example",
    "subject_type": "domain",
    "source": "dir-y",
    # overlapping window: proves rejection is not merely the time gate
    "observed_range": {
        "start": "2026-05-15T00:00:00+00:00",
        "end": "2026-07-15T00:00:00+00:00",
    },
    "tls": {
        "version": "TLSv1.3",
        "cipher_suite": "TLS_AES_256_GCM_SHA384",
        "alpn": ["h2"],
        "ja3": "ef" * 16,
    },
    "http": {
        "status_code": 404,
        "server": "nginx/1.24.0",
        "content_type": "application/json",
        "headers": {"Server": "nginx/1.24.0", "Content-Security-Policy": "default-src"},
    },
    "certificate": {
        "fingerprint_sha256": "d" * 64,
        "subject": "CN=gamma.example",
        "issuer": "CN=DigiCert",
        "serial_number": "bb",
        "sans": ["gamma.example"],
    },
    "technologies": ["nginx:1.24"],
    "body": '{"error": "gateway unavailable", "retry": 5}',
}
UNRELATED_Y_DISJOINT = {
    **UNRELATED_Y,
    "observed_range": {
        "start": "2026-10-01T00:00:00+00:00",
        "end": "2026-11-30T00:00:00+00:00",
    },
}

#: Two services sharing only *commodity* signals (identical TLS and
#: technology stack), no certificate, no body, no HTTP metadata.
COMMODITY_ONE = {
    "observation_id": "obs-c1",
    "evidence_ids": ["ev-c1"],
    "subject": "delta.onion",
    "subject_type": "onion_service",
    "source": "source-c1",
    "observed_range": {
        "start": "2026-06-01T00:00:00+00:00",
        "end": "2026-07-01T00:00:00+00:00",
    },
    "tls": {"version": "TLSv1.3", "cipher_suite": "TLS_AES_128_GCM_SHA256", "alpn": ["h2"]},
    "technologies": ["nginx:1.18", "php:8.1"],
}
COMMODITY_TWO = {
    **COMMODITY_ONE,
    "observation_id": "obs-c2",
    "evidence_ids": ["ev-c2"],
    "subject": "epsilon.example",
    "subject_type": "domain",
    "source": "source-c2",
    "observed_range": {
        "start": "2026-06-10T00:00:00+00:00",
        "end": "2026-07-20T00:00:00+00:00",
    },
}


# ------------------------------------------------------- passive-only boundary


def test_package_source_imports_no_networking_module() -> None:
    """Phase 13 forbids intrusive origin discovery: no network stack at all."""
    banned = {
        "socket",
        "ssl",
        "httpx",
        "requests",
        "urllib",
        "subprocess",
        "telnetlib",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "asyncio",
    }
    package_dir = Path(aegis.infrastructure.__file__).resolve().parent
    sources = sorted(package_dir.glob("*.py"))
    assert len(sources) == 5  # __init__, types, extract, correlate, history
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for module in imported:
                root = module.split(".")[0]
                assert root not in banned, f"{path.name} imports banned module {module!r}"


# ------------------------------------------------------------------ TimeRange


def test_timerange_rejects_naive_bounds() -> None:
    with pytest.raises(InfrastructureValidationError, match="timezone-aware"):
        TimeRange(datetime(2026, 1, 1), datetime(2026, 2, 1))


def test_timerange_rejects_inverted_bounds() -> None:
    with pytest.raises(InfrastructureValidationError, match="must not precede"):
        TimeRange(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))


def test_timerange_rejects_non_datetime() -> None:
    with pytest.raises(InfrastructureValidationError, match="must be a datetime"):
        TimeRange("2026-01-01", DAY_ONE)  # type: ignore[arg-type]


def test_timerange_accepts_zero_width_instant() -> None:
    instant = TimeRange(DAY_ONE, DAY_ONE)
    assert instant.duration == timedelta(0)


def test_timerange_intersection_union_and_overlap_similarity() -> None:
    jan_mar = TimeRange(_dt("2026-01-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    feb_apr = TimeRange(_dt("2026-02-01T00:00:00+00:00"), _dt("2026-04-30T00:00:00+00:00"))
    intersection = jan_mar.intersection(feb_apr)
    assert intersection == TimeRange(
        _dt("2026-02-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00")
    )
    assert intersection is not None
    assert jan_mar.union(feb_apr) == TimeRange(
        _dt("2026-01-01T00:00:00+00:00"), _dt("2026-04-30T00:00:00+00:00")
    )
    # overlap over the *shorter* window (feb_apr, 89 days), not the longer one
    assert jan_mar.overlap_similarity(feb_apr) == pytest.approx(
        intersection.duration / min(jan_mar.duration, feb_apr.duration)
    )


def test_timerange_disjoint_and_touching_windows_score_zero() -> None:
    first = TimeRange(_dt("2026-01-01T00:00:00+00:00"), _dt("2026-02-01T00:00:00+00:00"))
    second = TimeRange(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-04-01T00:00:00+00:00"))
    touching = TimeRange(_dt("2026-02-01T00:00:00+00:00"), _dt("2026-03-01T00:00:00+00:00"))
    assert first.intersection(second) is None
    assert first.overlap_similarity(second) == 0.0
    assert first.intersection(touching) is not None
    assert first.overlap_similarity(touching) == 0.0  # shares an endpoint, not a duration


def test_timerange_contained_window_scores_one() -> None:
    outer = TimeRange(_dt("2026-01-01T00:00:00+00:00"), _dt("2026-12-31T00:00:00+00:00"))
    inner = TimeRange(_dt("2026-05-01T00:00:00+00:00"), _dt("2026-06-01T00:00:00+00:00"))
    assert temporal_similarity(outer, inner) == 1.0


# -------------------------------------------------------- value-object validation


def test_technology_key_is_casefolded_with_version() -> None:
    assert Technology("Nginx", "1.18").key == "nginx:1.18"
    assert Technology("PHP").key == "php"


def test_technology_rejects_empty_and_whitespace_names() -> None:
    with pytest.raises(InfrastructureValidationError, match="non-empty"):
        Technology("   ")
    with pytest.raises(InfrastructureValidationError, match="whitespace"):
        Technology("nginx http")
    with pytest.raises(InfrastructureValidationError, match="non-empty"):
        Technology("nginx", "  ")


def test_tls_metadata_validation() -> None:
    with pytest.raises(InfrastructureValidationError, match="tls version"):
        TLSMetadata(version="")
    with pytest.raises(InfrastructureValidationError, match="tls ja3"):
        TLSMetadata(version="TLSv1.3", ja3="not-hex")
    with pytest.raises(InfrastructureValidationError, match="alpn"):
        TLSMetadata(version="TLSv1.3", alpn="h2")  # type: ignore[arg-type]
    normalized = TLSMetadata(version="TLSv1.3", ja3="AB" * 16, alpn=("h2", "h2"))
    assert normalized.ja3 == "ab" * 16
    assert normalized.alpn == ("h2",)


def test_http_metadata_validation_and_header_casefolding() -> None:
    with pytest.raises(InfrastructureValidationError, match="100..599"):
        HTTPMetadata(status_code=60)
    with pytest.raises(InfrastructureValidationError, match="status_code must be an int"):
        HTTPMetadata(status_code=True)  # type: ignore[arg-type]
    with pytest.raises(InfrastructureValidationError, match="headers must be a mapping"):
        HTTPMetadata(status_code=200, headers=["Server"])  # type: ignore[arg-type]
    http = HTTPMetadata(status_code=200, headers={"SERVER": "nginx"})
    assert http.headers == {"server": "nginx"}
    assert http.header_names == frozenset({"server"})


def test_certificate_metadata_validation_and_normalization() -> None:
    with pytest.raises(InfrastructureValidationError, match="fingerprint"):
        _certificate(fingerprint_sha256="xyz")
    with pytest.raises(InfrastructureValidationError, match="not_before"):
        _certificate(
            not_before=datetime(2026, 2, 1, tzinfo=UTC),
            not_after=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(InfrastructureValidationError, match="timezone-aware"):
        _certificate(not_before=datetime(2026, 1, 1))
    with pytest.raises(InfrastructureValidationError, match="spki_sha256"):
        _certificate(spki_sha256="short")
    certificate = _certificate(sans=["Alpha.onion", "alpha.onion", "www.alpha.onion"])
    assert certificate.sans == ("alpha.onion", "www.alpha.onion")  # deduped, sorted, folded
    assert certificate.fingerprint_sha256 == "a" * 64


def test_content_fingerprint_validation() -> None:
    with pytest.raises(InfrastructureValidationError, match="sha256"):
        ContentFingerprint(sha256="a" * 63, simhash=1, minhash=(1,))
    with pytest.raises(InfrastructureValidationError, match="64-bit"):
        ContentFingerprint(sha256="a" * 64, simhash=1 << 64, minhash=(1,))
    with pytest.raises(InfrastructureValidationError, match="minhash must not be empty"):
        ContentFingerprint(sha256="a" * 64, simhash=1, minhash=())
    with pytest.raises(InfrastructureValidationError, match="non-negative"):
        ContentFingerprint(sha256="a" * 64, simhash=1, minhash=(-1,))


def test_observation_requires_evidence_ids_and_infrastructure_type() -> None:
    # payload-level problems surface as ExtractionError (the extract layer
    # translates value-object invariant failures for its callers)
    with pytest.raises(ExtractionError, match="at least one id"):
        _observation(evidence_ids=[])
    with pytest.raises(ExtractionError, match="not a bare string"):
        _observation(evidence_ids="ev-1")
    with pytest.raises(ExtractionError, match="not an infrastructure type"):
        _observation(subject_type="post")
    with pytest.raises(ExtractionError, match="unknown entity type"):
        _observation(subject_type="no_such_type")


def test_observation_normalizes_ids_and_technologies() -> None:
    observation = _observation(
        evidence_ids=["ev-2", "ev-1", "ev-2"],
        technologies=["php:8.1", "Nginx:1.18", "php:8.1"],
    )
    assert observation.evidence_ids == ("ev-1", "ev-2")
    assert [technology.key for technology in observation.technologies] == [
        "nginx:1.18",
        "php:8.1",
    ]
    assert observation.technology_keys == frozenset({"nginx:1.18", "php:8.1"})


def test_observation_rejects_non_infrastructure_and_bad_bodies() -> None:
    with pytest.raises(ExtractionError, match="observation.body must be a string"):
        _observation(body=b"<html>")
    with pytest.raises(InfrastructureValidationError, match="must be a TimeRange"):
        InfrastructureObservation(
            observation_id="obs-1",
            evidence_ids=("ev-1",),
            subject="alpha.onion",
            subject_type=EntityType.ONION_SERVICE,
            source="source-a",
            observed_range="2026-01-01",  # type: ignore[arg-type]
        )
    with pytest.raises(InfrastructureValidationError, match="not an infrastructure type"):
        InfrastructureObservation(
            observation_id="obs-1",
            evidence_ids=("ev-1",),
            subject="alpha.onion",
            subject_type=EntityType.POST,
            source="source-a",
            observed_range=TimeRange(DAY_ONE, DAY_ONE),
        )


def test_features_enforce_content_and_technology_consistency() -> None:
    body = "Alpha marketplace home page."
    observation = _observation(body=body)
    fingerprint = content_fingerprint(body)
    with pytest.raises(InfrastructureValidationError, match="required when the observation"):
        InfrastructureFeatures(observation=observation, content=None, technology_keys=frozenset())
    with pytest.raises(InfrastructureValidationError, match="must be None for an observation"):
        InfrastructureFeatures(
            observation=_observation(body=""),
            content=fingerprint,
            technology_keys=frozenset(),
        )
    with pytest.raises(InfrastructureValidationError, match="does not match the observation"):
        InfrastructureFeatures(
            observation=observation,
            content=ContentFingerprint(sha256="b" * 64, simhash=1, minhash=(1,)),
            technology_keys=frozenset(),
        )
    with pytest.raises(InfrastructureValidationError, match="technology_keys must equal"):
        InfrastructureFeatures(
            observation=observation, content=fingerprint, technology_keys=frozenset({"ruby:3.3"})
        )


def test_breakdown_and_thresholds_reject_out_of_range_values() -> None:
    with pytest.raises(InfrastructureValidationError, match="overall"):
        SimilarityBreakdown(temporal=1.0, overall=1.5)
    with pytest.raises(InfrastructureValidationError, match="certificate"):
        SimilarityBreakdown(temporal=1.0, overall=0.5, certificate=-0.1)
    with pytest.raises(InfrastructureValidationError, match="min_similarity"):
        CorrelationThresholds(min_similarity=0.0)
    with pytest.raises(InfrastructureValidationError, match="min_content"):
        CorrelationThresholds(min_content=1.5)
    with pytest.raises(InfrastructureValidationError, match="min_temporal_overlap"):
        CorrelationThresholds(min_temporal_overlap=-0.1)
    with pytest.raises(InfrastructureValidationError, match="require_temporal_overlap"):
        CorrelationThresholds(require_temporal_overlap="yes")  # type: ignore[arg-type]


def test_threshold_strong_channel_priority_is_deterministic() -> None:
    breakdown = SimilarityBreakdown(temporal=1.0, overall=0.95, certificate=1.0, http=1.0)
    assert DEFAULT_THRESHOLDS.strong_channel(breakdown) == "certificate"
    without_cert = SimilarityBreakdown(temporal=1.0, overall=0.95, content=0.9, http=1.0)
    assert DEFAULT_THRESHOLDS.strong_channel(without_cert) == "content"
    commodity = SimilarityBreakdown(temporal=1.0, overall=1.0, technology=1.0, tls=1.0)
    assert DEFAULT_THRESHOLDS.strong_channel(commodity) is None


def test_breakdown_available_channels_excludes_unavailable() -> None:
    breakdown = SimilarityBreakdown(temporal=0.5, overall=0.5, content=0.9)
    assert breakdown.available_channels == ("content", "temporal")


# ------------------------------------------------------------- extraction: families


def test_extract_tls_metadata_full_and_minimal() -> None:
    full = extract_tls_metadata(
        {
            "version": "TLSv1.3",
            "cipher_suite": "TLS_AES_128_GCM_SHA256",
            "alpn": ["h2"],
            "ja3": "ab" * 16,
        }
    )
    assert full.version == "TLSv1.3"
    assert full.alpn == ("h2",)
    minimal = extract_tls_metadata({"version": "TLSv1.2"})
    assert minimal.cipher_suite is None
    assert minimal.ja3 is None
    assert minimal.alpn == ()


def test_extract_tls_metadata_failures() -> None:
    with pytest.raises(ExtractionError, match=r"tls.version"):
        extract_tls_metadata({"cipher_suite": "X"})
    with pytest.raises(ExtractionError, match="non-empty string"):
        extract_tls_metadata({"version": "   "})
    with pytest.raises(ExtractionError, match="sequence of strings"):
        extract_tls_metadata({"version": "TLSv1.3", "alpn": "h2"})
    with pytest.raises(ExtractionError, match="invalid tls payload"):
        extract_tls_metadata({"version": "TLSv1.3", "ja3": "zz"})


def test_extract_http_metadata_full_and_string_status() -> None:
    full = extract_http_metadata(
        {
            "status_code": 200,
            "server": "nginx/1.18.0",
            "content_type": "text/html",
            "headers": {"Server": "nginx/1.18.0", "X-Powered-By": "PHP/8.1"},
        }
    )
    assert full.status_code == 200
    assert full.headers == {"server": "nginx/1.18.0", "x-powered-by": "PHP/8.1"}
    coerced = extract_http_metadata({"status_code": "301"})
    assert coerced.status_code == 301
    assert coerced.server is None
    assert coerced.headers == {}


def test_extract_http_metadata_failures() -> None:
    with pytest.raises(ExtractionError, match="http.status_code"):
        extract_http_metadata({"server": "nginx"})
    with pytest.raises(ExtractionError, match="must be an int"):
        extract_http_metadata({"status_code": "redirect"})
    with pytest.raises(ExtractionError, match="http.headers"):
        extract_http_metadata({"status_code": 200, "headers": {"Server": 42}})


def test_extract_certificate_metadata_full_and_failures() -> None:
    certificate = extract_certificate_metadata(
        {
            "fingerprint_sha256": "A" * 64,
            "subject": "CN=alpha.onion",
            "issuer": "CN=R3",
            "serial_number": "01",
            "not_before": "2025-11-01T00:00:00+00:00",
            "not_after": "2026-02-01T00:00:00+00:00",
            "sans": ["alpha.onion"],
            "spki_sha256": "B" * 64,
        }
    )
    assert certificate.fingerprint_sha256 == "a" * 64  # case-folded
    assert certificate.not_before == datetime(2025, 11, 1, tzinfo=UTC)
    assert certificate.spki_sha256 == "b" * 64
    with pytest.raises(ExtractionError, match=r"certificate.fingerprint_sha256"):
        extract_certificate_metadata({"subject": "CN=x", "issuer": "CN=y", "serial_number": "1"})
    with pytest.raises(ExtractionError, match="timezone-aware"):
        extract_certificate_metadata(
            {
                "fingerprint_sha256": "a" * 64,
                "subject": "CN=x",
                "issuer": "CN=y",
                "serial_number": "1",
                "not_before": "2025-11-01T00:00:00",
            }
        )


def test_extract_technologies_from_strings_and_mappings() -> None:
    technologies = extract_technologies(
        ["nginx:1.18", {"name": "PHP", "version": "8.1"}, "redis", {"name": "mysql"}]
    )
    assert [technology.key for technology in technologies] == [
        "nginx:1.18",
        "php:8.1",
        "redis",
        "mysql",
    ]
    assert extract_technologies(None) == ()


def test_extract_technologies_failures() -> None:
    with pytest.raises(ExtractionError, match="not a bare string"):
        extract_technologies("nginx:1.18")
    with pytest.raises(ExtractionError, match="must be a sequence"):
        extract_technologies(42)
    with pytest.raises(ExtractionError, match="string or a mapping"):
        extract_technologies([42])
    with pytest.raises(ExtractionError, match=r"technologies\[0\]"):
        extract_technologies(["  "])


# ---------------------------------------------------------- extraction: observations


def test_extract_observation_full_payload() -> None:
    observation = _observation(**POSITIVE_A)
    assert observation.observation_id == "obs-a"
    assert observation.evidence_ids == ("ev-a",)
    assert observation.subject_type is EntityType.ONION_SERVICE
    assert observation.certificate is not None
    assert observation.tls is not None
    assert observation.http is not None
    assert observation.observed_range.start == datetime(2026, 1, 1, tzinfo=UTC)


def test_extract_observation_minimal_payload_leaves_families_unset() -> None:
    observation = _observation()
    assert observation.tls is None
    assert observation.http is None
    assert observation.certificate is None
    assert observation.technologies == ()
    assert observation.body_text == ""


def test_extract_observation_accepts_timerange_and_iso_bounds() -> None:
    explicit = _observation(
        observed_range=TimeRange(_dt("2026-01-01T00:00:00+00:00"), _dt("2026-01-02T00:00:00+00:00"))
    )
    assert explicit.observed_range.duration == timedelta(days=1)
    with pytest.raises(ExtractionError, match="timezone-aware"):
        _observation(observed_range={"start": "2026-01-01T00:00:00", "end": "2026-02-01T00:00:00"})


def test_extract_observation_rejects_missing_or_malformed_wrapper_keys() -> None:
    with pytest.raises(ExtractionError, match="observation.subject"):
        extract_observation({"observation_id": "o", "evidence_ids": ["e"]})
    with pytest.raises(ExtractionError, match="observed_range"):
        extract_observation({**_payload(), "observed_range": None})
    with pytest.raises(ExtractionError, match="must be a TimeRange or a"):
        _observation(observed_range="2026-01-01")
    with pytest.raises(ExtractionError, match="invalid observed_range payload"):
        _observation(
            observed_range={
                "start": "2026-02-01T00:00:00+00:00",
                "end": "2026-01-01T00:00:00+00:00",
            }
        )
    with pytest.raises(ExtractionError, match="unknown entity type"):
        _observation(subject_type="figment")
    with pytest.raises(ExtractionError, match="must be a mapping"):
        extract_observation("not a payload")  # type: ignore[arg-type]


def test_extract_observation_ignores_unknown_keys() -> None:
    observation = _observation(collector_note="field team photo of the rack")
    assert observation.observation_id == "obs-1"


def test_extract_features_content_presence_and_hash() -> None:
    without_body = _features()
    assert without_body.content is None
    assert without_body.technology_keys == frozenset()
    with_body = _features(body="Alpha marketplace home page.")
    assert with_body.content is not None
    assert with_body.content.sha256 == content_hash("Alpha marketplace home page.")
    assert with_body.content.simhash >= 0


def test_content_fingerprint_stability_and_discrimination() -> None:
    text = "Alpha marketplace home page. Trusted vendors only."
    first = content_fingerprint(text)
    second = content_fingerprint(text)
    assert first == second  # stable across calls
    other = content_fingerprint("Completely unrelated documentation about submarine cables.")
    assert other.sha256 != first.sha256
    assert other.simhash != first.simhash
    assert other.minhash != first.minhash


def test_content_fingerprint_rejects_blank_text() -> None:
    with pytest.raises(InfrastructureValidationError, match="blank content"):
        content_fingerprint("   ")


def test_payload_and_observation_from_canonical_evidence() -> None:
    evidence = Evidence(
        source_id=uuid4(),
        source_type=SourceType.SYNTHETIC,
        observed_at=datetime(2026, 1, 10, tzinfo=UTC),
        collected_at=datetime(2026, 1, 20, tzinfo=UTC),
        raw_artifact_uri="s3://aegis/evidence/2026/01/case/evidence/raw",
        sha256="c" * 64,
        collector_name="synthetic",
        collector_version="0.1.0",
        source_reliability=0.8,
        independence_group="synthetic-1",
        metadata={
            "tls": {"version": "TLSv1.3"},
            "http": {"status_code": 200, "server": "nginx/1.18.0"},
            "technologies": ["nginx:1.18"],
            "body": "Alpha marketplace home page.",
        },
    )
    payload = payload_from_evidence(evidence, subject="alpha.onion", subject_type="onion_service")
    observation = extract_observation(payload)
    assert observation.evidence_ids == (str(evidence.evidence_id),)
    assert observation.source == str(evidence.source_id)
    assert observation.observed_range == TimeRange(
        datetime(2026, 1, 10, tzinfo=UTC), datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert observation.tls is not None and observation.tls.version == "TLSv1.3"

    direct = observation_from_evidence(
        evidence, subject="alpha.onion", subject_type=EntityType.ONION_SERVICE
    )
    assert direct == observation


def test_payload_from_evidence_rejects_naive_or_inverted_timestamps() -> None:
    base = {
        "source_id": uuid4(),
        "source_type": SourceType.SYNTHETIC,
        "collected_at": datetime(2026, 1, 20, tzinfo=UTC),
        "raw_artifact_uri": "s3://aegis/evidence/2026/01/case/evidence/raw",
        "sha256": "c" * 64,
        "collector_name": "synthetic",
        "collector_version": "0.1.0",
        "source_reliability": 0.8,
        "independence_group": "synthetic-1",
    }
    naive = Evidence(**base, observed_at=datetime(2026, 1, 10))  # type: ignore[arg-type]
    with pytest.raises(ExtractionError, match="observed_at must be timezone-aware"):
        payload_from_evidence(naive, subject="alpha.onion", subject_type="onion_service")
    inverted = Evidence(**base, observed_at=datetime(2026, 2, 1, tzinfo=UTC))
    with pytest.raises(ExtractionError, match="must not precede"):
        payload_from_evidence(inverted, subject="alpha.onion", subject_type="onion_service")
    with pytest.raises(ExtractionError, match="canonical Evidence"):
        payload_from_evidence("evidence", subject="x", subject_type="domain")  # type: ignore[arg-type]


# ------------------------------------------------------------- channel similarity


def test_certificate_similarity_identity_and_reissue() -> None:
    assert certificate_similarity(_certificate(), _certificate()) == 1.0
    reissued = _certificate(fingerprint_sha256="b" * 64, spki_sha256="e" * 64)
    same_key = _certificate(fingerprint_sha256="c" * 64, spki_sha256="e" * 64)
    assert certificate_similarity(reissued, same_key) == 0.9


def test_certificate_similarity_unrelated_certificates_score_zero() -> None:
    unrelated = _certificate(
        fingerprint_sha256="d" * 64,
        subject="CN=gamma.example",
        issuer="CN=DigiCert",
        serial_number="bb",
        sans=["gamma.example"],
    )
    assert certificate_similarity(_certificate(), unrelated) == 0.0


def test_certificate_similarity_partial_agreement_is_the_mean_of_comparisons() -> None:
    # subject differs, issuer matches, no SANs recorded: mean(0, 1) == 0.5
    no_sans = _certificate(sans=())
    shared_issuer_only = _certificate(
        fingerprint_sha256="d" * 64,
        subject="CN=gamma.example",
        issuer="CN=R3",
        serial_number="bb",
        sans=(),
    )
    assert certificate_similarity(no_sans, shared_issuer_only) == pytest.approx(0.5)
    # mean(subject=0, issuer=1, SAN Jaccard=0.5) == 0.5
    half_sans = _certificate(
        fingerprint_sha256="d" * 64,
        subject="CN=gamma.example",
        issuer="CN=R3",
        serial_number="bb",
        sans=["alpha.onion", "www.alpha.onion"],
    )
    assert certificate_similarity(_certificate(), half_sans) == pytest.approx(0.5)


def test_tls_similarity_field_means() -> None:
    assert tls_similarity(_tls(), _tls()) == 1.0
    assert tls_similarity(_tls(), TLSMetadata(version="TLSv1.3")) == 1.0  # version-only pair
    assert tls_similarity(_tls(), TLSMetadata(version="TLSv1.2")) == 0.0
    half = tls_similarity(
        _tls(), TLSMetadata(version="TLSv1.3", cipher_suite="TLS_AES_256_GCM_SHA384")
    )
    # version matches, cipher differs, no ALPN/JA3 comparable on the right
    assert half == pytest.approx(0.5)


def test_http_similarity_returns_none_without_comparable_fields() -> None:
    bare_left = HTTPMetadata(status_code=200)
    bare_right = HTTPMetadata(status_code=301)
    assert http_similarity(bare_left, bare_right) is None
    assert http_similarity(bare_left, _http()) is None  # nothing comparable on the left


def test_http_similarity_header_profile_and_content_type_normalization() -> None:
    assert http_similarity(_http(), _http()) == 1.0
    assert normalized_content_type("text/html; charset=utf-8") == "text/html"
    # identical header names + server, content type differing only by case and
    # parameters: the normalisation must make the pair a perfect match despite
    # the differing status codes (which are deliberately not compared).
    same_profile_other_params = HTTPMetadata(
        status_code=201,
        server="nginx/1.18.0",
        content_type="TEXT/HTML; boundary=x",
        headers={
            "Server": "nginx/1.18.0",
            "Content-Type": "text/html",
            "Connection": "keep-alive",
            "X-Powered-By": "PHP/8.1",
        },
    )
    assert http_similarity(_http(), same_profile_other_params) == 1.0
    different_type = HTTPMetadata(
        status_code=200,
        server="nginx/1.18.0",
        content_type="application/json",
        headers={
            "Server": "nginx/1.18.0",
            "Content-Type": "text/html",
            "Connection": "keep-alive",
            "X-Powered-By": "PHP/8.1",
        },
    )
    # mean(names=1, server=1, type=0)
    assert http_similarity(_http(), different_type) == pytest.approx(2 / 3)


def test_technology_similarity_jaccard_and_unavailability() -> None:
    left = frozenset({"nginx:1.18", "php:8.1"})
    assert technology_similarity(left, left) == 1.0
    assert technology_similarity(left, frozenset()) == 0.0
    assert technology_similarity(frozenset(), frozenset()) is None
    assert technology_similarity(left, frozenset({"nginx:1.18", "ruby:3.3"})) == pytest.approx(
        1 / 3
    )


def test_content_similarity_stability_and_discrimination() -> None:
    text = "Alpha marketplace home page. Trusted vendors only. Escrow protected trading."
    near_duplicate = content_fingerprint(
        "Alpha marketplace home page. Trusted vendors only. Escrow protected deals."
    )
    unrelated = content_fingerprint("Submarine cable maps, routing tables, and port scans.")
    identical = content_fingerprint(text)
    assert content_similarity(identical, identical) == 1.0
    assert content_similarity(identical, near_duplicate) >= 0.8
    assert content_similarity(identical, unrelated) < 0.5


def test_temporal_similarity_is_overlap_over_shorter_window() -> None:
    outer = TimeRange(_dt("2026-01-01T00:00:00+00:00"), _dt("2026-12-31T00:00:00+00:00"))
    inner = TimeRange(_dt("2026-05-01T00:00:00+00:00"), _dt("2026-06-01T00:00:00+00:00"))
    disjoint = TimeRange(_dt("2027-01-01T00:00:00+00:00"), _dt("2027-02-01T00:00:00+00:00"))
    assert temporal_similarity(outer, inner) == 1.0
    assert temporal_similarity(outer, disjoint) == 0.0


# ------------------------------------------------------------------- comparison


def test_compare_features_reports_unavailable_channels_as_none() -> None:
    breakdown = compare_features(_features(), _features())
    assert breakdown.certificate is None
    assert breakdown.content is None
    assert breakdown.http is None
    assert breakdown.tls is None
    assert breakdown.technology is None  # neither side reports any technology
    assert 0.0 <= breakdown.temporal <= 1.0
    assert breakdown.available_channels == ("temporal",)


def test_compare_features_overall_is_the_weighted_mean_of_available_channels() -> None:
    left = _features(certificate=CERTIFICATE_PAYLOAD, technologies=["nginx:1.18"])
    right = _features(
        certificate=CERTIFICATE_PAYLOAD,
        technologies=["ruby:3.3"],
        observed_range={
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-03-31T00:00:00+00:00",
        },
    )
    breakdown = compare_features(left, right)
    # certificate 1.0 (w .30), technology 0.0 (w .15), temporal 1.0 (w .05)
    assert breakdown.certificate == 1.0
    assert breakdown.technology == 0.0
    assert breakdown.temporal == 1.0
    assert breakdown.overall == pytest.approx(0.35 / 0.50)


def test_compare_features_weights_sum_to_one_so_full_scores_are_comparable() -> None:
    assert sum(CHANNEL_WEIGHTS.values()) == pytest.approx(1.0)
    breakdown = compare_features(_positive_a(), _positive_b())
    expected = sum(
        CHANNEL_WEIGHTS[name] * float(getattr(breakdown, name))
        for name in breakdown.available_channels
    )
    assert breakdown.overall == pytest.approx(expected)


def test_compare_features_rejects_wrong_input_types() -> None:
    with pytest.raises(CorrelationError, match="left must be InfrastructureFeatures"):
        compare_features("features", _positive_a())  # type: ignore[arg-type]


# ----------------------------------------------------------- correlation: positive


def test_positive_correlation_carries_the_full_plan_output_contract() -> None:
    record = correlate(_positive_a(), _positive_b())
    assert record is not None
    assert record.similarity == record.breakdown.overall
    assert record.similarity >= 0.6
    assert record.left_observation_id == "obs-a"
    assert record.right_observation_id == "obs-b"
    assert record.evidence_ids == ("ev-a", "ev-b")
    assert record.sources == ("dir-alpha", "scan-beta")
    assert record.time_range == TimeRange(
        _dt("2026-02-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00")
    )  # the window both observations were valid
    assert record.strong_channel == "certificate"
    assert record.relationship_type is RelationshipType.CERTIFICATE_ASSOCIATED_WITH
    assert len(record.limitations) >= 4
    joined = " ".join(record.limitations)
    assert "does not establish common control" in joined
    assert "no intrusive origin discovery" in joined
    assert "not an attribution conclusion" in joined
    assert "2026-02-01" in joined  # the time range is disclosed as bounded evidence


def test_correlation_is_symmetric() -> None:
    forward = correlate(_positive_a(), _positive_b())
    backward = correlate(_positive_b(), _positive_a())
    assert forward is not None and backward is not None
    assert forward == backward  # endpoints canonically ordered by observation id


def test_correlation_rejects_joining_an_observation_with_itself() -> None:
    features = _positive_a()
    with pytest.raises(InfrastructureError, match="distinct observations"):
        correlate(features, features)


def test_correlation_without_certificate_uses_content_channel() -> None:
    left = _features(
        body="Alpha marketplace home page. Trusted vendors only. Escrow protected trading.",
        technologies=["nginx:1.18"],
    )
    right = _features(
        observation_id="obs-2",
        evidence_ids=["ev-2"],
        subject="alpha-mirror.example",
        source="source-b",
        body="Alpha marketplace home page. Trusted vendors only. Escrow protected deals.",
        technologies=["nginx:1.18"],
        observed_range={
            "start": "2026-02-01T00:00:00+00:00",
            "end": "2026-04-30T00:00:00+00:00",
        },
    )
    record = correlate(left, right)
    assert record is not None
    assert record.strong_channel == "content"
    assert record.relationship_type is RelationshipType.INFRASTRUCTURE_SIMILAR_TO
    assert record.breakdown.certificate is None
    assert any(
        "certificate metadata was not observed on both sides" in note for note in record.limitations
    )


def test_single_source_correlation_discloses_non_independent_corroboration() -> None:
    same_source_b = {**POSITIVE_B, "source": "dir-alpha"}
    record = correlate(_positive_a(), extract_features(extract_observation(same_source_b)))
    assert record is not None
    assert record.sources == ("dir-alpha",)
    assert any("not independent" in note for note in record.limitations)


def test_relaxed_temporal_gate_exposes_non_overlapping_windows_as_limitation() -> None:
    disjoint_b = {
        **POSITIVE_B,
        "observed_range": {
            "start": "2026-07-01T00:00:00+00:00",
            "end": "2026-09-30T00:00:00+00:00",
        },
    }
    default = correlate(_positive_a(), extract_features(extract_observation(disjoint_b)))
    assert default is None  # default rule: disjoint windows never correlate
    relaxed = correlate(
        _positive_a(),
        extract_features(extract_observation(disjoint_b)),
        thresholds=CorrelationThresholds(require_temporal_overlap=False),
    )
    assert relaxed is not None
    assert relaxed.time_range == TimeRange(
        _dt("2026-01-01T00:00:00+00:00"), _dt("2026-09-30T00:00:00+00:00")
    )  # union: both windows, explicitly not simultaneous
    assert any("do not overlap" in note for note in relaxed.limitations)


# ------------------------------------------------- correlation: false correlations


def test_unrelated_infrastructure_with_disjoint_windows_does_not_correlate() -> None:
    left = extract_features(extract_observation(dict(UNRELATED_X)))
    right = extract_features(extract_observation(dict(UNRELATED_Y_DISJOINT)))
    assert correlate(left, right) is None


def test_unrelated_infrastructure_with_overlapping_windows_does_not_correlate() -> None:
    """The plan's false-correlation test: differing certs, fingerprints,
    hosts, stacks, and bodies must fail even when the time gate passes."""
    left = extract_features(extract_observation(dict(UNRELATED_X)))
    right = extract_features(extract_observation(dict(UNRELATED_Y)))
    breakdown = compare_features(left, right)
    assert breakdown.temporal > 0.0  # the temporal gate would let this through
    assert breakdown.certificate == 0.0
    assert (breakdown.content or 1.0) < 0.8
    assert breakdown.technology == 0.0
    assert correlate(left, right) is None


def test_shared_commodity_stack_alone_never_correlates() -> None:
    """Identical TLS + technology stacks give a perfect overall score, yet
    commodity signals cannot start a candidate correlation."""
    left = extract_features(extract_observation(dict(COMMODITY_ONE)))
    right = extract_features(extract_observation(dict(COMMODITY_TWO)))
    breakdown = compare_features(left, right)
    assert breakdown.overall >= 0.9  # the naive "high similarity" trap
    assert breakdown.certificate is None and breakdown.content is None
    assert correlate(left, right) is None


def test_thresholds_can_be_tightened_or_relaxed_consciously() -> None:
    left = extract_features(extract_observation(dict(COMMODITY_ONE)))
    right = extract_features(extract_observation(dict(COMMODITY_TWO)))
    # no threshold set makes a commodity-only pair a candidate: the strong
    # channel requirement is part of the rule, not just the floor
    permissive = CorrelationThresholds(min_similarity=0.1, min_temporal_overlap=0.0)
    assert correlate(left, right, thresholds=permissive) is None
    strict = CorrelationThresholds(min_similarity=0.99, min_certificate=0.99)
    positive = correlate(_positive_a(), _positive_b(), thresholds=strict)
    assert positive is None


# ------------------------------------------------------------ correlation: batch


def test_correlate_all_returns_only_passing_pairs_sorted_by_similarity() -> None:
    features = [
        extract_features(extract_observation(dict(payload)))
        for payload in (
            POSITIVE_A,
            POSITIVE_B,
            UNRELATED_X,
            UNRELATED_Y,
            COMMODITY_ONE,
            COMMODITY_TWO,
        )
    ]
    results = correlate_all(features)
    assert len(results) == 1  # exactly the positive pair survives
    assert {results[0].left_observation_id, results[0].right_observation_id} == {
        "obs-a",
        "obs-b",
    }
    assert correlate_all([]) == ()


def test_correlate_all_is_deterministic_and_rejects_duplicate_ids() -> None:
    features = [
        extract_features(extract_observation(dict(payload)))
        for payload in (POSITIVE_B, POSITIVE_A, UNRELATED_X, UNRELATED_Y)
    ]
    forward = correlate_all(features)
    backward = correlate_all(list(reversed(features)))
    assert forward == backward
    duplicate = [
        extract_features(extract_observation(dict(POSITIVE_A))),
        extract_features(extract_observation({**POSITIVE_A, "subject": "other.onion"})),
    ]
    with pytest.raises(CorrelationError, match="duplicate observation ids"):
        correlate_all(duplicate)


def test_correlate_rejects_non_threshold_arguments() -> None:
    with pytest.raises(CorrelationError, match="thresholds must be CorrelationThresholds"):
        correlate(_positive_a(), _positive_b(), thresholds={"min_similarity": 0.1})  # type: ignore[arg-type]


# ------------------------------------------------------- correlation: validation


def _raw_correlation(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "left_observation_id": "obs-a",
        "right_observation_id": "obs-b",
        "left_subject": "alpha.onion",
        "right_subject": "alpha-mirror.example",
        "similarity": 0.9,
        "breakdown": SimilarityBreakdown(temporal=1.0, overall=0.9),
        "evidence_ids": ("ev-a", "ev-b"),
        "time_range": TimeRange(_dt("2026-01-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00")),
        "sources": ("dir-alpha", "scan-beta"),
        "limitations": ("Shared infrastructure does not prove common control.",),
        "strong_channel": "certificate",
    }
    fields.update(overrides)
    return fields


def test_correlation_record_validation_failures() -> None:
    with pytest.raises(InfrastructureValidationError, match="distinct observations"):
        InfrastructureCorrelation(**{**_raw_correlation(), "right_observation_id": "obs-a"})
    with pytest.raises(InfrastructureValidationError, match="within \\[0, 1\\]"):
        InfrastructureCorrelation(**{**_raw_correlation(), "similarity": 1.5})
    with pytest.raises(InfrastructureValidationError, match="must equal breakdown.overall"):
        InfrastructureCorrelation(**{**_raw_correlation(), "similarity": 0.5})
    with pytest.raises(InfrastructureValidationError, match="limitations"):
        InfrastructureCorrelation(**{**_raw_correlation(), "limitations": ()})
    with pytest.raises(InfrastructureValidationError, match="strong_channel"):
        InfrastructureCorrelation(**{**_raw_correlation(), "strong_channel": "tls"})
    with pytest.raises(InfrastructureValidationError, match="symmetric"):
        InfrastructureCorrelation(
            **{**_raw_correlation(), "relationship_type": RelationshipType.USES_INFRASTRUCTURE}
        )


def test_emitted_relationship_types_are_infrastructure_symmetric_vocabulary() -> None:
    emitted = {
        correlate(_positive_a(), _positive_b()).relationship_type,
        correlate(
            _features(
                body="Alpha marketplace home page. Trusted vendors only. Escrow protected trading.",
                technologies=["nginx:1.18"],
            ),
            _features(
                observation_id="obs-2",
                evidence_ids=["ev-2"],
                subject="alpha-mirror.example",
                source="source-b",
                body="Alpha marketplace home page. Trusted vendors only. Escrow protected deals.",
                technologies=["nginx:1.18"],
            ),
        ).relationship_type,
    }
    assert emitted == {
        RelationshipType.CERTIFICATE_ASSOCIATED_WITH,
        RelationshipType.INFRASTRUCTURE_SIMILAR_TO,
    }
    for relationship in emitted:
        assert RELATIONSHIP_DIRECTION[relationship] is RelationDirection.SYMMETRIC


def test_every_infrastructure_entity_type_is_accepted_as_subject_type() -> None:
    infrastructure_types = [
        entity_type
        for entity_type, category in ENTITY_CATEGORIES.items()
        if category is EntityCategory.INFRASTRUCTURE
    ]
    assert len(infrastructure_types) == 8
    for entity_type in infrastructure_types:
        observation = _observation(subject_type=entity_type.value)
        assert observation.subject_type is entity_type


def test_non_infrastructure_entity_types_are_rejected() -> None:
    for entity_type in (EntityType.POST, EntityType.WALLET_ADDRESS, EntityType.HANDLE):
        with pytest.raises(ExtractionError, match="not an infrastructure type"):
            _observation(subject_type=entity_type)
        with pytest.raises(InfrastructureValidationError, match="not an infrastructure type"):
            InfrastructureObservation(
                observation_id="obs-1",
                evidence_ids=("ev-1",),
                subject="alpha.onion",
                subject_type=entity_type,
                source="source-a",
                observed_range=TimeRange(DAY_ONE, DAY_ONE),
            )


# ------------------------------------------------------------ historical changes


def _history_observation(
    observation_id: str,
    *,
    start: str,
    end: str,
    certificate_fingerprint: str | None,
    server: str,
    technologies: list[str],
    header_names: list[str],
    evidence_ids: list[str],
    subject: str = "rot.onion",
) -> InfrastructureObservation:
    return extract_observation(
        {
            "observation_id": observation_id,
            "evidence_ids": evidence_ids,
            "subject": subject,
            "subject_type": "onion_service",
            "source": "source-h",
            "observed_range": {"start": start, "end": end},
            "http": {
                "status_code": 200,
                "server": server,
                "content_type": "text/html",
                "headers": {name: "1" for name in header_names},
            },
            "certificate": (
                {
                    "fingerprint_sha256": certificate_fingerprint,
                    "subject": "CN=rot.onion",
                    "issuer": "CN=R3",
                    "serial_number": "01",
                }
                if certificate_fingerprint is not None
                else None
            ),
            "technologies": technologies,
        }
    )


def _history_series() -> list[InfrastructureObservation]:
    shared_headers = ["Server", "Connection"]
    return [
        _history_observation(
            "obs-1",
            start="2026-01-01T00:00:00+00:00",
            end="2026-01-31T00:00:00+00:00",
            certificate_fingerprint="a" * 64,
            server="nginx/1.18.0",
            technologies=["nginx:1.18"],
            header_names=shared_headers,
            evidence_ids=["ev-1"],
        ),
        _history_observation(
            "obs-2",
            start="2026-02-15T00:00:00+00:00",
            end="2026-03-15T00:00:00+00:00",
            certificate_fingerprint="b" * 64,  # certificate rotation
            server="nginx/1.18.0",
            technologies=["nginx:1.18"],
            header_names=shared_headers,
            evidence_ids=["ev-2"],
        ),
        _history_observation(
            "obs-3",
            start="2026-03-15T00:00:00+00:00",
            end="2026-04-15T00:00:00+00:00",
            certificate_fingerprint="b" * 64,
            server="nginx/1.24.0",  # server + header + stack change
            technologies=["nginx:1.24"],
            header_names=[*shared_headers, "X-Frame-Options"],
            evidence_ids=["ev-3", "ev-4"],
        ),
    ]


def test_detect_changes_finds_rotation_header_and_technology_changes() -> None:
    changes = detect_changes(_history_series())
    assert [change.field for change in changes] == [
        "certificate.fingerprint_sha256",
        "http.header_names",
        "http.server",
        "technologies",
    ]
    assert [change.kind for change in changes] == [
        ChangeKind.CERTIFICATE_ROTATION,
        ChangeKind.HEADER_CHANGE,
        ChangeKind.HEADER_CHANGE,
        ChangeKind.TECHNOLOGY_CHANGE,
    ]
    rotation = changes[0]
    assert rotation.old_value == "a" * 64
    assert rotation.new_value == "b" * 64
    assert rotation.evidence_ids == ("ev-1", "ev-2")
    assert rotation.sources == ("source-h",)


def test_detect_changes_windows_bound_the_transition() -> None:
    changes = detect_changes(_history_series())
    rotation, header_names, server, technologies = changes
    assert rotation.window == TimeRange(
        _dt("2026-01-31T00:00:00+00:00"), _dt("2026-02-15T00:00:00+00:00")
    )  # gap between the two observation windows
    for change in (header_names, server, technologies):
        assert change.window == TimeRange(
            _dt("2026-03-15T00:00:00+00:00"), _dt("2026-03-15T00:00:00+00:00")
        )  # touching windows: the change happened in that instant


def test_detect_changes_output_is_ordered_by_window_regardless_of_input_order() -> None:
    series = _history_series()
    forward = detect_changes(series)
    backward = detect_changes(list(reversed(series)))
    assert forward == backward
    starts = [change.window.start for change in forward]
    assert starts == sorted(starts)


def test_detect_changes_deterministic_ids_and_disclosed_limitations() -> None:
    series = _history_series()
    first = detect_changes(series)
    second = detect_changes(series)
    assert [change.change_id for change in first] == [change.change_id for change in second]
    assert len(set(change.change_id for change in first)) == len(first)
    joined = " ".join(first[0].limitations)
    assert "exact time" in joined
    assert "no intrusive origin discovery" in joined
    assert "does not by itself establish" in joined


def test_detect_changes_reports_nothing_for_stable_metadata() -> None:
    stable_headers = ["Server", "Connection"]
    first = _history_observation(
        "obs-stable-1",
        start="2026-01-01T00:00:00+00:00",
        end="2026-01-31T00:00:00+00:00",
        certificate_fingerprint="a" * 64,
        server="nginx/1.18.0",
        technologies=["nginx:1.18"],
        header_names=stable_headers,
        evidence_ids=["ev-1"],
    )
    second = _history_observation(
        "obs-stable-2",
        start="2026-02-15T00:00:00+00:00",
        end="2026-03-15T00:00:00+00:00",
        certificate_fingerprint="a" * 64,
        server="nginx/1.18.0",
        technologies=["nginx:1.18"],
        header_names=stable_headers,
        evidence_ids=["ev-2"],
    )
    assert detect_changes([second, first]) == ()  # identical tracked metadata
    assert detect_changes([first]) == ()  # nothing to compare against


def test_detect_changes_skips_fields_absent_from_either_side() -> None:
    without_certificate = _history_observation(
        "obs-no-cert",
        start="2026-02-15T00:00:00+00:00",
        end="2026-03-15T00:00:00+00:00",
        certificate_fingerprint=None,
        server="nginx/1.18.0",
        technologies=["nginx:1.18"],
        header_names=["Server", "Connection"],
        evidence_ids=["ev-9"],
    )
    changes = detect_changes([_history_series()[0], without_certificate])
    assert changes == ()  # first appearance of a certificate is missing data, not a change


def test_detect_changes_never_spans_subjects() -> None:
    other_subject = _history_observation(
        "obs-other",
        start="2026-02-15T00:00:00+00:00",
        end="2026-03-15T00:00:00+00:00",
        certificate_fingerprint="f" * 64,
        server="iis/10.0",
        technologies=["iis:10"],
        header_names=["Server"],
        evidence_ids=["ev-7"],
        subject="other.onion",
    )
    assert detect_changes([_history_series()[0], other_subject]) == ()


def test_detect_changes_rejects_duplicate_observation_ids() -> None:
    series = _history_series()
    duplicated = [series[0], series[1], series[1]]
    with pytest.raises(InfrastructureValidationError, match="duplicate observation ids"):
        detect_changes(duplicated)


def test_detect_changes_accepts_empty_input() -> None:
    assert detect_changes([]) == ()


def test_historical_change_validation_failures() -> None:
    fields = {
        "change_id": "abc123",
        "subject": "rot.onion",
        "field": "certificate.fingerprint_sha256",
        "kind": ChangeKind.CERTIFICATE_ROTATION,
        "old_value": "a" * 64,
        "new_value": "b" * 64,
        "window": TimeRange(_dt("2026-01-31T00:00:00+00:00"), _dt("2026-02-15T00:00:00+00:00")),
        "evidence_ids": ("ev-1", "ev-2"),
        "sources": ("source-h",),
        "limitations": ("The exact time is unknown.",),
    }
    HistoricalChange(**fields)  # valid as-is
    with pytest.raises(InfrastructureValidationError, match="must alter the value"):
        HistoricalChange(**{**fields, "new_value": "a" * 64})
    with pytest.raises(InfrastructureValidationError, match="limitations"):
        HistoricalChange(**{**fields, "limitations": ()})
    with pytest.raises(InfrastructureValidationError, match="unknown change kind"):
        HistoricalChange(**{**fields, "kind": "sudden_reboot"})
    with pytest.raises(InfrastructureValidationError, match="window"):
        HistoricalChange(**{**fields, "window": "2026-01-31"})
