"""Tests for the Tor hidden-service infrastructure API.

These assert the properties a schema cannot: that the filters actually narrow,
that a match carries the per-channel breakdown it was scored on rather than a
bare number, that an observation is never paired with itself, that
``correlate`` refuses to write without a case to attribute the write to, that
the correlation's own limitations survive the round trip to the response, and
that the summary's single-channel count is derived from the stored rows
instead of asserted.

The fixture builds its observations through
:func:`aegis.api.infrastructure.features_document` and its expected match
through :func:`aegis.infrastructure.correlate.correlate_all`, so a test that
"expects" a correlation is expecting one the library would actually produce
from the features stored beside it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from aegis.api.app import app
from aegis.api.infrastructure import features_document
from aegis.db.models import (
    CaseRecord,
    InfrastructureFindingRecord,
    InfrastructureMatchRecord,
    InfrastructureObservationRecord,
)
from aegis.db.session import SessionLocal
from aegis.infrastructure.correlate import correlate_all
from aegis.infrastructure.extract import extract_features, extract_observation
from aegis.infrastructure.types import CorrelationThresholds, SimilarityBreakdown

#: Every test in this module writes observations, findings and matches, so
#: every one of them needs PostgreSQL. Without this marker the `backend` job —
#: which deliberately runs no service container — collects them, fails to open
#: a session in the fixture, and errors 19 times. `pytest_runtest_setup` reads
#: this before any fixture is instantiated, so the skip happens first and
#: `AEGIS_REQUIRE_DB=1` in the `integration` job still turns the absence into
#: a failure rather than a silently reduced run.
pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
WINDOW_START = NOW - timedelta(days=6)
WINDOW_END = NOW - timedelta(days=1)

#: The rule the tests state explicitly. ``POST /correlate`` has no default:
#: a correlation that silently used one would read as a deliberate choice.
RULE = CorrelationThresholds(
    min_similarity=0.42,
    min_certificate=0.9,
    min_content=0.8,
    min_http=0.9,
    min_temporal_overlap=0.0,
    require_temporal_overlap=True,
)

RULE_BODY: dict[str, float | bool] = {
    "min_similarity": 0.42,
    "min_certificate": 0.9,
    "min_content": 0.8,
    "min_http": 0.9,
    "min_temporal_overlap": 0.0,
    "require_temporal_overlap": True,
}

BASE32 = "abcdefghijklmnopqrstuvwxyz234567"

#: Pools the fixture varies per subject. Every channel that can corroborate a
#: correlation has to differ between unrelated observations, or the fixture
#: correlates subjects that share nothing: an identical ``Server`` header and
#: content type is itself a strong channel in this library, because header
#: profiles are one of the three signals allowed to start a candidate.
_SERVERS = (
    "nginx/1.24.0 (edge)",
    "lighttpd/1.4.69",
    "Caddy",
    "nginx/1.18.0 (Ubuntu)",
    "openresty/1.21.4.1",
    "envoy",
)
_CONTENT_TYPES = (
    "text/html; charset=utf-8",
    "application/json",
    "text/plain; charset=utf-8",
    "application/xhtml+xml",
)
_VERSIONS = ("TLSv1.2", "TLSv1.3")
_CIPHERS = (
    "TLS_AES_256_GCM_SHA384",
    "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
    "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
)
_HEADERS = (
    "server",
    "date",
    "content-type",
    "x-powered-by",
    "x-frame-options",
    "cache-control",
    "etag",
    "vary",
)
_TECHS = (
    ("nginx:1.24.0", "php:8.1"),
    ("debian:11",),
    ("envoy:1.27", "envoy:1.27"),
    ("python:3.11", "python:3.11"),
    ("haproxy:2.8",),
    ("docker:24.0", "debian:12"),
)


def _slot(label: str, size: int) -> int:
    """A stable per-label index, so two subjects land on different profiles."""
    return sum(ord(character) for character in label) % size


def _hex(seed: str, length: int = 64) -> str:
    """A deterministic hex string of exactly ``length`` characters.

    Derived from SHA-256 rather than from ``hash()``: a Python hash is small
    enough that zero-padding it to 64 places puts every subject's first
    characters in the same leading zeros, which silently gives every fixture
    observation the same JA3 and the same page body.
    """
    out = ""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(f"{seed}:{counter}".encode()).hexdigest()
        counter += 1
    return out[:length]


def _onion(seed: str) -> str:
    """A deterministic, syntactically shaped v3 address.

    Derived from ``_hex`` rather than ``hash()``: Python randomises string
    hashing per process, so a ``hash()``-derived subject changed on every run
    and the fixture's per-subject HTTP profiles changed with it. The pair
    meant to correlate on the certificate alone would then sometimes also
    match on the header profile — and the test would pass or fail depending
    on the interpreter's hash seed.
    """
    return "".join(BASE32[int(_hex(f"{seed}:{i}", 2), 16) % 32] for i in range(56))


def _page(label: str) -> str:
    """A body whose every token belongs to ``label`` and nothing else.

    SimHash weights a word above a character 3-gram, so a shared word or a
    shared skeleton lifts the content channel of two unrelated services and
    the fixture ends up correlating pages that say nothing alike.
    """
    return " ".join(_hex(f"{label}:{index}", 8) for index in range(120))


def _certificate(label: str, *, fingerprint: str | None = None) -> dict[str, object]:
    return {
        "fingerprint_sha256": fingerprint or _hex(f"cert:{label}"),
        "subject": f"CN={label}",
        "issuer": f"C=Synthetic CA, O={label}",
        "serial_number": _hex(f"serial:{label}", 16).upper(),
        "not_before": (WINDOW_START - timedelta(days=90)).isoformat(),
        "not_after": (WINDOW_END + timedelta(days=200)).isoformat(),
        "sans": [label],
        "spki_sha256": _hex(f"spki:{label}"),
    }


def _features(
    *,
    label: str,
    observation_id: str | None = None,
    fingerprint: str | None = None,
    server: str | None = None,
    ja3: str | None = None,
    technologies: tuple[str, ...] | None = None,
    content_type: str | None = None,
    header_names: tuple[str, ...] | None = None,
    body: str | None = None,
    status: int = 200,
) -> dict[str, object]:
    return features_document(
        observation_id=observation_id or str(uuid4()),
        evidence_ids=[str(uuid4())],
        subject=label,
        subject_type="onion_service" if label.endswith(".onion") else "domain",
        source="synthetic-test-collector",
        observed_range={"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        tls={
            "version": _VERSIONS[_slot(label, len(_VERSIONS))],
            "cipher_suite": _CIPHERS[_slot(label + "c", len(_CIPHERS))],
            "alpn": ["h2", "http/1.1"] if _slot(label, 2) == 0 else ["http/1.1"],
            "ja3": ja3 or _hex(f"ja3:{label}", 32),
        },
        http={
            "status_code": status,
            "server": server or _SERVERS[_slot(label, len(_SERVERS))],
            "content_type": content_type or _CONTENT_TYPES[_slot(label + "t", len(_CONTENT_TYPES))],
            "headers": {
                name: "synthetic"
                for name in (
                    header_names
                    if header_names is not None
                    else _HEADERS[_slot(label, 4) : _slot(label, 4) + 4]
                )
            },
        },
        certificate=_certificate(label, fingerprint=fingerprint),
        technologies=list(
            technologies if technologies is not None else _TECHS[_slot(label, len(_TECHS))]
        ),
        body=body if body is not None else _page(label),
    )


def _observation(
    *,
    observation_id: UUID,
    subject: str,
    network: str,
    features: dict[str, object],
    case_id: UUID,
) -> InfrastructureObservationRecord:
    return InfrastructureObservationRecord(
        observation_id=observation_id,
        subject=subject,
        network=network,
        source="synthetic-test-collector",
        observed_at=WINDOW_START,
        features_json=features,
        case_id=case_id,
        metadata_json={"synthetic": True},
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def world() -> Iterator[dict[str, object]]:
    """A case, three observations, one genuine correlation, and findings.

    ``onion_a`` and ``host_a`` share a certificate fingerprint, the header
    profile, the client fingerprint, the technology stack and the page body:
    the origin-server story. ``onion_b`` shares *only* the certificate with
    ``host_a``: the single-channel finding, and the one most likely to be
    shared hosting. ``onion_c`` shares nothing and must not correlate.
    """
    with SessionLocal() as db:
        case = CaseRecord(
            case_id=uuid4(),
            name="Infrastructure API test case",
            description="synthetic",
            status="active",
            priority="high",
            severity="high",
            tags=["infrastructure"],
        )
        db.add(case)
        db.flush()
        case_id = case.case_id

        mirror_cert = _hex("mirror-origin-cert")
        origin_cert = _hex("shared-origin-cert")
        host_a_label = "host-a.example"
        host_b_label = "host-b.example"
        onion_a = _onion("onion-a")
        onion_b = _onion("onion-b")
        onion_c = _onion("onion-c")
        ids = {name: uuid4() for name in ("onion_a", "host_a", "onion_b", "host_b", "onion_c")}

        shared_page = _page("shared-origin")
        plans = [
            # The mirror: identical on every channel, including the certificate.
            _observation(
                observation_id=ids["onion_a"],
                subject=onion_a,
                network="onion",
                case_id=case_id,
                features=_features(
                    label=onion_a,
                    observation_id=str(ids["onion_a"]),
                    fingerprint=mirror_cert,
                    server="nginx/1.24.0 (edge)",
                    ja3=_hex("ja3-mirror", 32),
                    technologies=("nginx:1.24.0", "php:8.1"),
                    body=shared_page,
                    content_type="text/html; charset=utf-8",
                    header_names=("server", "date", "content-type", "x-powered-by"),
                ),
            ),
            _observation(
                observation_id=ids["host_a"],
                subject=host_a_label,
                network="clearnet",
                case_id=case_id,
                features=_features(
                    label=host_a_label,
                    observation_id=str(ids["host_a"]),
                    fingerprint=mirror_cert,
                    server="nginx/1.24.0 (edge)",
                    ja3=_hex("ja3-mirror", 32),
                    technologies=("nginx:1.24.0", "php:8.1"),
                    body=shared_page,
                    content_type="text/html; charset=utf-8",
                    header_names=("server", "date", "content-type", "x-powered-by"),
                ),
            ),
            # Certificate only: a *different* certificate from the mirror's,
            # and every other channel disagreeing. This is the shape shared
            # hosting and a key reuse both produce.
            _observation(
                observation_id=ids["onion_b"],
                subject=onion_b,
                network="onion",
                case_id=case_id,
                features=_features(
                    label=onion_b,
                    observation_id=str(ids["onion_b"]),
                    fingerprint=origin_cert,
                    server="lighttpd/1.4.69",
                    ja3=_hex("ja3-b", 32),
                    technologies=("debian:11",),
                    content_type="text/html; charset=utf-8",
                    header_names=("date", "content-length", "x-powered-by", "etag"),
                ),
            ),
            _observation(
                observation_id=ids["host_b"],
                subject=host_b_label,
                network="clearnet",
                case_id=case_id,
                features=_features(
                    label=host_b_label,
                    observation_id=str(ids["host_b"]),
                    fingerprint=origin_cert,
                    server="lighttpd/1.4.69",
                    ja3=_hex("ja3-b2", 32),
                    technologies=("debian:12",),
                    # Same product banner, different response shape: the
                    # header profile and content type are the only thing that
                    # could turn this into a two-channel match, and they are
                    # pinned apart so the test means what it claims.
                    content_type="application/json",
                    header_names=("server", "vary", "cache-control", "last-modified"),
                ),
            ),
            # Shares nothing with anybody.
            _observation(
                observation_id=ids["onion_c"],
                subject=onion_c,
                network="onion",
                case_id=case_id,
                features=_features(
                    label=onion_c,
                    observation_id=str(ids["onion_c"]),
                    fingerprint=_hex("cert:onion-c"),
                    server="Caddy",
                    ja3=_hex("ja3-c", 32),
                    technologies=("envoy:1.27",),
                ),
            ),
        ]
        db.add_all(plans)
        db.flush()

        # Ask the library what correlates, rather than asserting a score.
        views = []
        for record in plans:
            payload = dict(record.features_json["observation"])  # type: ignore[index]
            payload["observation_id"] = str(record.observation_id)
            views.append(extract_features(extract_observation(payload)))
        candidates = correlate_all(views, thresholds=RULE)
        assert len(candidates) == 2, (
            "the fixture must produce exactly the two designed correlations; "
            f"the library returned {len(candidates)}"
        )

        now = NOW
        matches: list[InfrastructureMatchRecord] = []
        for candidate in candidates:
            left = UUID(candidate.left_observation_id)
            right = UUID(candidate.right_observation_id)
            by_id = {record.observation_id: record for record in plans}
            onion_side = by_id[left] if by_id[left].network == "onion" else by_id[right]
            clearnet_side = by_id[right] if by_id[left].network == "onion" else by_id[left]
            matches.append(
                InfrastructureMatchRecord(
                    match_id=uuid4(),
                    onion_observation_id=onion_side.observation_id,
                    clearnet_observation_id=clearnet_side.observation_id,
                    case_id=case_id,
                    overall=candidate.similarity,
                    breakdown_json={
                        "overall": candidate.breakdown.overall,
                        "certificate": candidate.breakdown.certificate,
                        "content": candidate.breakdown.content,
                        "technology": candidate.breakdown.technology,
                        "http": candidate.breakdown.http,
                        "tls": candidate.breakdown.tls,
                        "temporal": candidate.breakdown.temporal,
                    },
                    limitations=list(candidate.limitations),
                    strongest_channel=candidate.strong_channel,
                    detected_at=now,
                    metadata_json={"sources": list(candidate.sources)},
                )
            )
        db.add_all(matches)

        findings = [
            InfrastructureFindingRecord(
                finding_id=uuid4(),
                observation_id=plans[0].observation_id,
                case_id=case_id,
                kind="clearnet_certificate",
                severity="high",
                detail="The certificate carries a clearnet SAN.",
                limitations=["A mirror operator holds the domain legitimately."],
                confidence=0.85,
                detected_at=now - timedelta(hours=2),
            ),
            InfrastructureFindingRecord(
                finding_id=uuid4(),
                observation_id=plans[2].observation_id,
                case_id=case_id,
                kind="default_banner",
                severity="low",
                detail="Unmodified product banner still advertised.",
                limitations=["Thousands of unrelated hosts serve the same banner."],
                confidence=0.7,
                detected_at=now - timedelta(days=3),
            ),
            InfrastructureFindingRecord(
                finding_id=uuid4(),
                observation_id=plans[1].observation_id,
                case_id=case_id,
                kind="shared_fingerprint",
                severity="high",
                detail="Certificate fingerprint identical to a clearnet host.",
                limitations=["Shared hosting and CDNs produce the same signal."],
                # Deliberately unscored: the platform will not put a number on
                # "these two certificates are the same certificate".
                confidence=None,
                detected_at=now - timedelta(days=200),
            ),
        ]
        db.add_all(findings)
        db.commit()

        yield {
            "case_id": str(case_id),
            "onion_a": str(ids["onion_a"]),
            "host_a": str(ids["host_a"]),
            "onion_b": str(ids["onion_b"]),
            "host_b": str(ids["host_b"]),
            "onion_c": str(ids["onion_c"]),
            "match_ids": [str(row.match_id) for row in matches],
            "finding_ids": [str(row.finding_id) for row in findings],
        }


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_findings_filter_by_kind(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    body = client.get(
        "/api/v1/infrastructure/findings",
        params={"case_id": world["case_id"], "kind": "default_banner"},
        headers=auth_headers,
    )
    assert body.status_code == 200
    rows = body.json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "default_banner"
    assert rows[0]["kind_label"] == "Default service banner"
    # The subject and network are joined in, so a finding is actionable
    # without a second request.
    assert rows[0]["subject"]
    assert rows[0]["network"] in {"onion", "clearnet"}


def test_findings_filter_by_severity(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    body = client.get(
        "/api/v1/infrastructure/findings",
        params={"case_id": world["case_id"], "severity": "high"},
        headers=auth_headers,
    )
    assert body.status_code == 200
    kinds = {row["kind"] for row in body.json()}
    assert kinds == {"clearnet_certificate", "shared_fingerprint"}


def test_findings_filter_by_time_window(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """`since`/`until` bound `detected_at`, so an old finding drops out."""
    recent = client.get(
        "/api/v1/infrastructure/findings",
        params={"case_id": world["case_id"], "since": (NOW - timedelta(days=30)).isoformat()},
        headers=auth_headers,
    ).json()
    assert len(recent) == 2
    assert all(row["detected_at"] >= (NOW - timedelta(days=30)).isoformat() for row in recent)

    everything = client.get(
        "/api/v1/infrastructure/findings",
        params={"case_id": world["case_id"]},
        headers=auth_headers,
    ).json()
    assert len(everything) == 3

    bounded = client.get(
        "/api/v1/infrastructure/findings",
        params={
            "case_id": world["case_id"],
            "since": (NOW - timedelta(days=30)).isoformat(),
            "until": (NOW - timedelta(days=2)).isoformat(),
        },
        headers=auth_headers,
    ).json()
    # The 2-hour-old finding is now outside the upper bound.
    assert [row["kind"] for row in bounded] == ["default_banner"]


def test_findings_min_confidence_excludes_unscored(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """An unscored detector is excluded, not treated as confidence 0."""
    body = client.get(
        "/api/v1/infrastructure/findings",
        params={"case_id": world["case_id"], "min_confidence": 0.0},
        headers=auth_headers,
    ).json()
    assert [row["kind"] for row in body] == ["clearnet_certificate", "default_banner"]
    assert all(row["confidence"] is not None for row in body)

    unscored = client.get(
        "/api/v1/infrastructure/findings",
        params={"case_id": world["case_id"], "kind": "shared_fingerprint"},
        headers=auth_headers,
    ).json()
    assert unscored[0]["confidence"] is None
    assert unscored[0]["limitations"], "a finding carries its alternative reading"


def test_finding_detail_route(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    finding_id = world["finding_ids"][0]
    body = client.get(f"/api/v1/infrastructure/findings/{finding_id}", headers=auth_headers)
    assert body.status_code == 200
    assert body.json()["finding_id"] == finding_id
    missing = client.get(f"/api/v1/infrastructure/findings/{uuid4()}", headers=auth_headers)
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def test_matches_carry_breakdown_and_named_strongest_channel(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    body = client.get(
        "/api/v1/infrastructure/matches",
        params={"case_id": world["case_id"]},
        headers=auth_headers,
    )
    assert body.status_code == 200
    rows = body.json()
    assert len(rows) == 2

    for row in rows:
        breakdown = row["breakdown"]
        # Every channel is present as a key, and the unobservable ones are
        # null rather than 0 — a client that renders null as 0 would turn a
        # missing measurement into evidence against the correlation.
        assert set(breakdown) >= {
            "certificate",
            "content",
            "technology",
            "http",
            "tls",
            "temporal",
            "available_channels",
            "decisive_channels",
        }
        assert row["strongest_channel"] in {"certificate", "content", "http"}
        assert breakdown["decisive_channels"], "a match names what carries it"
        assert row["limitations"], "a match carries what it does not prove"
        assert row["onion_subject"] and row["clearnet_subject"]
        assert row["overall"] > 0

    # The strongest channel is the highest-scoring decisive one.
    for row in rows:
        decisive = row["breakdown"]["decisive_channels"]
        assert decisive[0] == row["strongest_channel"]


def test_matches_report_single_channel_matches(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """The corroborated mirror and the certificate-only pair must not read alike."""
    rows = client.get(
        "/api/v1/infrastructure/matches",
        params={"case_id": world["case_id"]},
        headers=auth_headers,
    ).json()
    by_single = sorted(row["single_channel"] for row in rows)
    assert by_single == [False, True]

    single = next(row for row in rows if row["single_channel"])
    assert single["breakdown"]["decisive_channels"] == ["certificate"]
    # A certificate on its own: the other channels are genuinely near zero,
    # which is why it needs labelling rather than a high score.
    assert single["breakdown"]["http"] < 0.9
    assert single["breakdown"]["content"] < 0.8

    corroborated = next(row for row in rows if not row["single_channel"])
    assert len(corroborated["breakdown"]["decisive_channels"]) > 1


def test_match_never_pairs_an_observation_with_itself() -> None:
    """The library, the API and the table all refuse a self-pairing."""
    from aegis.infrastructure.correlate import correlate_all as run_all
    from aegis.infrastructure.types import CorrelationError

    solo = _features(label="solo.example")
    view = extract_features(
        extract_observation(
            {
                **dict(solo["observation"]),  # type: ignore[arg-type]
                "observation_id": "11111111-1111-4111-8111-111111111111",
            }
        )
    )
    # One observation is fewer than the two a correlation needs.
    assert run_all([view], thresholds=RULE) == ()

    # Two views over the same endpoint collapse to one id, which the library
    # rejects rather than quietly correlating an observation with itself.
    with pytest.raises(CorrelationError):
        run_all([view, view], thresholds=RULE)

    # And the table refuses it even if a caller bypasses both.
    with SessionLocal() as db:
        record = db.scalar(select(InfrastructureObservationRecord).limit(1))
        assert record is not None
        db.add(
            InfrastructureMatchRecord(
                match_id=uuid4(),
                onion_observation_id=record.observation_id,
                clearnet_observation_id=record.observation_id,
                overall=0.9,
                breakdown_json={"temporal": 1.0},
                limitations=["n/a"],
                strongest_channel="certificate",
                detected_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_matches_filter_by_overall_and_subject(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """Filtering the clearnet side must not require knowing the onion side."""
    rows = client.get(
        "/api/v1/infrastructure/matches",
        params={"case_id": world["case_id"], "clearnet_subject": "host-a.example"},
        headers=auth_headers,
    ).json()
    assert len(rows) == 1
    assert all("host-a.example" in row["clearnet_subject"] for row in rows)

    by_channel = client.get(
        "/api/v1/infrastructure/matches",
        params={"case_id": world["case_id"], "strongest_channel": "certificate"},
        headers=auth_headers,
    ).json()
    assert len(by_channel) == 2

    none_here = client.get(
        "/api/v1/infrastructure/matches",
        params={"case_id": world["case_id"], "strongest_channel": "content"},
        headers=auth_headers,
    ).json()
    assert none_here == []


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


def test_observations_expose_features(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    rows = client.get(
        "/api/v1/infrastructure/observations",
        params={"case_id": world["case_id"]},
        headers=auth_headers,
    )
    assert rows.status_code == 200
    body = rows.json()
    assert len(body) == 5
    for row in body:
        features = row["features"]
        assert features["schema_version"] == "aegis-infrastructure/1"
        assert features["content"]["sha256"]
        assert features["technology_keys"]
        assert features["observation"]["tls"]["version"] in {"TLSv1.2", "TLSv1.3"}
        assert len(features["observation"]["tls"]["ja3"]) == 32
        assert features["observation"]["certificate"]["fingerprint_sha256"]
        assert row["network"] in {"onion", "clearnet"}

    single = client.get(
        f"/api/v1/infrastructure/observations/{world['onion_a']}",
        headers=auth_headers,
    )
    assert single.status_code == 200
    assert single.json()["observation_id"] == world["onion_a"]
    assert single.json()["match_count"] >= 1


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summary_counts_are_derived_from_stored_rows(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    body = client.get(
        "/api/v1/infrastructure/summary",
        params={"case_id": world["case_id"]},
        headers=auth_headers,
    )
    assert body.status_code == 200
    summary = body.json()

    assert summary["findings_total"] == 3
    assert summary["findings_by_kind"]["clearnet_certificate"] == 1
    assert summary["findings_by_kind"]["default_banner"] == 1
    assert summary["findings_by_kind"]["shared_fingerprint"] == 1
    assert summary["findings_by_severity"]["high"] == 2
    assert summary["findings_by_severity"]["low"] == 1
    # The unscored detector is counted separately rather than averaged in.
    assert summary["findings_unscored"] == 1

    assert summary["observations_total"] == 5
    assert summary["onion_services"] == 3
    assert summary["clearnet_hosts"] == 2
    assert summary["matches_total"] == 2


def test_summary_single_channel_count_is_computed(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """The headline is a count over the rows, not a stored constant.

    Recomputing it here from the breakdown the API returned for each match
    pins the definition: a match whose decisive-channel list is empty or has
    one entry is a single-channel match.
    """
    summary = client.get(
        "/api/v1/infrastructure/summary",
        params={"case_id": world["case_id"]},
        headers=auth_headers,
    ).json()
    matches = client.get(
        "/api/v1/infrastructure/matches",
        params={"case_id": world["case_id"]},
        headers=auth_headers,
    ).json()

    expected = sum(1 for row in matches if len(row["breakdown"]["decisive_channels"]) <= 1)
    assert expected == 1
    assert summary["single_channel_matches"] == expected
    assert summary["matches_total"] - summary["single_channel_matches"] == 1
    assert summary["matches_by_strongest_channel"]["certificate"] == 2


# ---------------------------------------------------------------------------
# correlate
# ---------------------------------------------------------------------------


def test_correlate_requires_a_case_id(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """No case, no write: an unattributable finding is not a finding."""
    body = client.post(
        "/api/v1/infrastructure/correlate",
        json={"thresholds": RULE_BODY},
        headers=auth_headers,
    )
    assert body.status_code == 422
    assert "case_id" in str(body.json()["detail"])


def test_correlate_requires_explicit_thresholds(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """The rule must be stated, not inherited from a library default."""
    body = client.post(
        "/api/v1/infrastructure/correlate",
        json={"case_id": world["case_id"]},
        headers=auth_headers,
    )
    assert body.status_code == 422
    assert "thresholds" in str(body.json()["detail"])

    partial = client.post(
        "/api/v1/infrastructure/correlate",
        json={"case_id": world["case_id"], "thresholds": {"min_similarity": 0.5}},
        headers=auth_headers,
    )
    assert partial.status_code == 422


def test_correlate_unknown_case_is_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.post(
        "/api/v1/infrastructure/correlate",
        json={"case_id": str(uuid4()), "thresholds": RULE_BODY},
        headers=auth_headers,
    )
    assert body.status_code == 404


def test_correlate_limitations_survive_to_the_response(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    body = client.post(
        "/api/v1/infrastructure/correlate",
        json={
            "case_id": world["case_id"],
            "thresholds": RULE_BODY,
            "observation_ids": [world["onion_a"], world["host_a"]],
            "networks": ["onion", "clearnet"],
        },
        headers=auth_headers,
    )
    assert body.status_code == 200
    payload = body.json()

    # The library's own notes, verbatim — not summarised into a sentence.
    assert len(payload["limitations"]) >= 4
    joined = " ".join(payload["limitations"]).casefold()
    assert "does not establish common control" in joined
    assert "no intrusive origin discovery" in joined
    assert "not an attribution conclusion" in joined
    # The strong-channel caveat is present and names the channel that fired.
    assert "certificate" in joined

    for match in payload["existing"]:
        assert match["limitations"], "a stored match keeps its limitations"
        assert any("common control" in note.casefold() for note in match["limitations"]), (
            "the per-match list is the library's, not a restatement"
        )
    assert payload["existing"], "an already-recorded match is reported, not rewritten"
    assert payload["created"] == [], "nothing new is created for a recorded pair"
    assert payload["thresholds"]["min_similarity"] == 0.42


def test_correlate_does_not_overwrite_an_existing_match(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    with SessionLocal() as db:
        before = {
            str(row.match_id): row.overall
            for row in db.scalars(
                select(InfrastructureMatchRecord).where(
                    InfrastructureMatchRecord.case_id == UUID(str(world["case_id"]))
                )
            ).all()
        }
    assert before

    body = client.post(
        "/api/v1/infrastructure/correlate",
        json={
            "case_id": world["case_id"],
            "thresholds": RULE_BODY,
            "observation_ids": [
                world["onion_a"],
                world["host_a"],
                world["onion_b"],
                world["host_b"],
                world["onion_c"],
            ],
        },
        headers=auth_headers,
    )
    assert body.status_code == 200
    payload = body.json()
    assert payload["created"] == []
    assert len(payload["existing"]) == 2
    assert payload["candidates"] == 2
    assert payload["same_network_candidates"] >= 0

    with SessionLocal() as db:
        after = {
            str(row.match_id): row.overall
            for row in db.scalars(
                select(InfrastructureMatchRecord).where(
                    InfrastructureMatchRecord.case_id == UUID(str(world["case_id"]))
                )
            ).all()
        }
    assert after == before, "a re-run must not rewrite a stored score in place"


def test_correlate_creates_a_match_for_an_unrecorded_pair(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    """A pair the store has never seen is written, with its own breakdown."""
    with SessionLocal() as db:
        # Clear this case's matches so the run has something to create. Scoped
        # to the case on purpose: an unscoped delete would take out every
        # other test's rows and every seeded match with them.
        db.query(InfrastructureMatchRecord).filter(
            InfrastructureMatchRecord.case_id == UUID(str(world["case_id"]))
        ).delete()
        db.commit()

    body = client.post(
        "/api/v1/infrastructure/correlate",
        json={
            "case_id": world["case_id"],
            "thresholds": RULE_BODY,
            "observation_ids": [
                world["onion_a"],
                world["host_a"],
                world["onion_b"],
                world["host_b"],
                world["onion_c"],
            ],
        },
        headers=auth_headers,
    )
    assert body.status_code == 200
    payload = body.json()
    assert len(payload["created"]) == 2
    assert payload["existing"] == []
    assert payload["observations_considered"] == 5
    assert payload["pairs_evaluated"] == 10
    for match in payload["created"]:
        assert match["onion_observation_id"] != match["clearnet_observation_id"]
        assert match["single_channel"] in {True, False}
        # The stored breakdown must itself satisfy the library's invariants.
        SimilarityBreakdown(
            temporal=match["breakdown"]["temporal"],
            overall=match["overall"],
            certificate=match["breakdown"]["certificate"],
        )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_csv_carries_the_limitations(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    body = client.get(
        "/api/v1/infrastructure/export",
        params={"format": "csv", "case_id": world["case_id"], "dataset": "findings"},
        headers=auth_headers,
    )
    assert body.status_code == 200
    text = body.text
    assert "limitations" in text.splitlines()[0]
    # The alternative explanation travels with the row, or the spreadsheet
    # reads as an accusation.
    assert "Shared hosting and CDNs" in text
    # An unscored detector writes an empty cell, not 0.
    assert "0.85" in text


def test_export_json_bundle(
    client: TestClient, world: dict[str, object], auth_headers: dict[str, str]
) -> None:
    body = client.get(
        "/api/v1/infrastructure/export",
        params={"format": "json", "case_id": world["case_id"], "dataset": "matches"},
        headers=auth_headers,
    )
    assert body.status_code == 200
    payload = body.json()
    assert payload["filters"]["dataset"] == "matches"
    assert len(payload["matches"]) == 2
    assert payload["returned"] == 2
    for row in payload["matches"]:
        assert row["breakdown"]["decisive_channels"] is not None
        assert row["limitations"]
