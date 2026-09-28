"""Infrastructure evidence value objects (Phase 13).

Implementation Plan section 14 ("Phase 13 --- Infrastructure Evidence")
fixes the passive feature families extracted from *stored* observation
payloads::

    TLS metadata
    HTTP metadata
    content fingerprints
    technology fingerprints
    certificate metadata
    historical changes

and the output contract for candidate correlations::

    candidate correlation
    similarity
    evidence IDs
    time range
    source
    limitations

The plan explicitly forbids intrusive origin discovery, so every type in
this module is a pure, validated value object describing data that has
already been collected: the package performs no network I/O and never
probes, scans, or resolves anything.  Value objects fail loudly in
``__post_init__`` (``InfrastructureValidationError``) instead of
silently normalising bad data, matching the defensive style of the
neighbouring :mod:`aegis.search` and :mod:`aegis.graph` layers.

Entity and relationship vocabulary is reused from
:mod:`aegis.ontology` — observations must carry an *infrastructure*
entity type and correlations may only propose symmetric infrastructure
relationship types.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from aegis.normalization import content_hash
from aegis.ontology import (
    ENTITY_CATEGORIES,
    RELATIONSHIP_DIRECTION,
    EntityCategory,
    EntityType,
    RelationDirection,
    RelationshipType,
)

_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JA3_RE = re.compile(r"^[0-9a-f]{32,64}$")
_MAX_SIMHASH = (1 << 64) - 1


class InfrastructureError(ValueError):
    """Base class for infrastructure-evidence failures (Phase 13)."""


class InfrastructureValidationError(InfrastructureError):
    """A value object was built with invalid data — always loud, never coerced."""


class ExtractionError(InfrastructureError):
    """A stored observation payload is missing keys or holds malformed values."""


class CorrelationError(InfrastructureError):
    """A correlation request is malformed (duplicate ids, unusable thresholds)."""


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InfrastructureValidationError(f"{name} must be a non-empty string, got {value!r}")
    return value.strip()


def _require_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise InfrastructureValidationError(
            f"{name} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None:
        raise InfrastructureValidationError(f"{name} must be timezone-aware (pass tzinfo=UTC)")
    return value


def _require_hex(value: object, name: str, pattern: re.Pattern[str]) -> str:
    text = _require_text(value, name).casefold()
    if not pattern.fullmatch(text):
        raise InfrastructureValidationError(f"{name} must match {pattern.pattern!r}, got {value!r}")
    return text


def _normalize_ids(values: object, name: str) -> tuple[str, ...]:
    """Validate a non-empty id sequence; dedupe and sort deterministically."""
    if isinstance(values, str | bytes):
        raise InfrastructureValidationError(f"{name} must be a sequence of ids, not a bare string")
    if not isinstance(values, Sequence):
        raise InfrastructureValidationError(
            f"{name} must be a sequence of ids, got {type(values).__name__}"
        )
    normalized: set[str] = set()
    for item in values:
        normalized.add(_require_text(item, f"{name} entry"))
    if not normalized:
        raise InfrastructureValidationError(f"{name} must contain at least one id")
    return tuple(sorted(normalized))


def _coerce_infrastructure_type(value: object) -> EntityType:
    """Coerce to an :class:`EntityType` that is ontologically infrastructure."""
    if isinstance(value, EntityType):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = EntityType(value)
        except ValueError as exc:
            allowed = ", ".join(
                member.value
                for member, category in ENTITY_CATEGORIES.items()
                if category is EntityCategory.INFRASTRUCTURE
            )
            raise InfrastructureValidationError(
                f"unknown entity type {value!r}; infrastructure types are: {allowed}"
            ) from exc
    else:
        raise InfrastructureValidationError(
            f"subject_type must be an EntityType or its value, got {type(value).__name__}"
        )
    if ENTITY_CATEGORIES[candidate] is not EntityCategory.INFRASTRUCTURE:
        raise InfrastructureValidationError(
            f"entity type {candidate.value!r} is not an infrastructure type; "
            "Phase 13 extracts infrastructure evidence only"
        )
    return candidate


def _require_range(value: object, name: str) -> TimeRange:
    if not isinstance(value, TimeRange):
        raise InfrastructureValidationError(
            f"{name} must be a TimeRange, got {type(value).__name__}"
        )
    return value


@dataclass(frozen=True)
class TimeRange:
    """Closed interval ``[start, end]`` over which something was observed.

    Both bounds must be timezone-aware and ordered; a zero-width range
    (``start == end``) is a legitimate instant observation.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _require_aware(self.start, "start"))
        object.__setattr__(self, "end", _require_aware(self.end, "end"))
        if self.start > self.end:
            raise InfrastructureValidationError(
                f"start {self.start.isoformat()} must not precede end {self.end.isoformat()}"
            )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def overlaps(self, other: TimeRange) -> bool:
        """True when the two ranges share at least an instant."""
        return self.start <= other.end and other.start <= self.end

    def intersection(self, other: TimeRange) -> TimeRange | None:
        """The window observed by *both* ranges, or ``None`` if disjoint."""
        if not self.overlaps(other):
            return None
        return TimeRange(max(self.start, other.start), min(self.end, other.end))

    def union(self, other: TimeRange) -> TimeRange:
        """The smallest range covering both ranges."""
        return TimeRange(min(self.start, other.start), max(self.end, other.end))

    def overlap_similarity(self, other: TimeRange) -> float:
        """Intersection over the *shorter* duration, in ``[0, 1]``.

        Ranges that merely touch at an endpoint share no duration and
        score ``0.0``; a range contained in the other scores ``1.0``.
        """
        common = self.intersection(other)
        if common is None:
            return 0.0
        shorter = min(self.duration, other.duration)
        if shorter == timedelta(0):
            return 1.0
        return common.duration / shorter


@dataclass(frozen=True)
class Technology:
    """One observed technology stack element (name with optional version)."""

    name: str
    version: str | None = None

    def __post_init__(self) -> None:
        name = _require_text(self.name, "technology name")
        if any(character.isspace() for character in name):
            raise InfrastructureValidationError(
                f"technology name must not contain whitespace, got {self.name!r}"
            )
        object.__setattr__(self, "name", name)
        if self.version is not None:
            object.__setattr__(self, "version", _require_text(self.version, "technology version"))

    @property
    def key(self) -> str:
        """Canonical, case-folded identity used for Jaccard comparison."""
        name = self.name.casefold()
        if self.version is None:
            return name
        return f"{name}:{self.version.casefold()}"


@dataclass(frozen=True)
class TLSMetadata:
    """Passively observed TLS parameters of one endpoint.

    All fields describe metadata that was *already* recorded by a
    collector; nothing here negotiates a connection.
    """

    version: str
    cipher_suite: str | None = None
    alpn: tuple[str, ...] = ()
    ja3: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _require_text(self.version, "tls version"))
        if self.cipher_suite is not None:
            object.__setattr__(
                self, "cipher_suite", _require_text(self.cipher_suite, "tls cipher_suite")
            )
        if isinstance(self.alpn, str | bytes) or not isinstance(self.alpn, Sequence):
            raise InfrastructureValidationError(
                f"alpn must be a sequence of protocol ids, got {type(self.alpn).__name__}"
            )
        protocols = tuple(_require_text(item, "alpn entry") for item in self.alpn)
        object.__setattr__(self, "alpn", tuple(dict.fromkeys(protocols)))
        if self.ja3 is not None:
            object.__setattr__(self, "ja3", _require_hex(self.ja3, "tls ja3", _JA3_RE))


@dataclass(frozen=True)
class HTTPMetadata:
    """Passively observed HTTP response metadata.

    ``headers`` keys are case-folded at construction so comparisons never
    depend on header casing.  ``status_code`` is recorded but deliberately
    excluded from similarity scoring: it is path-dependent, so the same
    infrastructure legitimately serves different statuses per URL.
    """

    status_code: int
    server: str | None = None
    content_type: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise InfrastructureValidationError(
                f"status_code must be an int, got {type(self.status_code).__name__}"
            )
        if not 100 <= self.status_code <= 599:
            raise InfrastructureValidationError(
                f"status_code must be within 100..599, got {self.status_code}"
            )
        if self.server is not None:
            object.__setattr__(self, "server", _require_text(self.server, "http server"))
        if self.content_type is not None:
            object.__setattr__(
                self, "content_type", _require_text(self.content_type, "http content_type")
            )
        if not isinstance(self.headers, Mapping):
            raise InfrastructureValidationError(
                f"headers must be a mapping of name -> value, got {type(self.headers).__name__}"
            )
        normalized: dict[str, str] = {}
        for raw_name, raw_value in self.headers.items():
            name = _require_text(raw_name, "header name").casefold()
            normalized[name] = _require_text(raw_value, f"header {name!r} value")
        object.__setattr__(self, "headers", dict(sorted(normalized.items())))

    @property
    def header_names(self) -> frozenset[str]:
        return frozenset(self.headers)


@dataclass(frozen=True)
class CertificateMetadata:
    """Certificate metadata observed in stored traffic.

    ``fingerprint_sha256`` is the certificate's identity; ``spki_sha256``
    identifies the public key so a re-issued certificate for the same key
    can be linked without pretending the certificates are identical.
    """

    fingerprint_sha256: str
    subject: str
    issuer: str
    serial_number: str
    not_before: datetime | None = None
    not_after: datetime | None = None
    sans: tuple[str, ...] = ()
    spki_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fingerprint_sha256",
            _require_hex(self.fingerprint_sha256, "fingerprint", _HEX_SHA256_RE),
        )
        object.__setattr__(self, "subject", _require_text(self.subject, "certificate subject"))
        object.__setattr__(self, "issuer", _require_text(self.issuer, "certificate issuer"))
        object.__setattr__(
            self, "serial_number", _require_text(self.serial_number, "certificate serial_number")
        )
        if self.not_before is not None:
            object.__setattr__(self, "not_before", _require_aware(self.not_before, "not_before"))
        if self.not_after is not None:
            object.__setattr__(self, "not_after", _require_aware(self.not_after, "not_after"))
        if self.not_before is not None and self.not_after is not None:
            if self.not_before > self.not_after:
                raise InfrastructureValidationError(
                    f"not_before {self.not_before.isoformat()} must not precede "
                    f"not_after {self.not_after.isoformat()}"
                )
        if isinstance(self.sans, str | bytes) or not isinstance(self.sans, Sequence):
            raise InfrastructureValidationError(
                f"sans must be a sequence of names, got {type(self.sans).__name__}"
            )
        names = {_require_text(entry, "san entry").casefold() for entry in self.sans}
        object.__setattr__(self, "sans", tuple(sorted(names)))
        if self.spki_sha256 is not None:
            object.__setattr__(
                self, "spki_sha256", _require_hex(self.spki_sha256, "spki_sha256", _HEX_SHA256_RE)
            )


@dataclass(frozen=True)
class ContentFingerprint:
    """Fingerprints of one body's content.

    Built through :mod:`aegis.normalization` (SHA-256, 64-bit SimHash,
    64-permutation MinHash) so infrastructure content shares the exact
    same fingerprint vocabulary as Phase 06 document deduplication.
    """

    sha256: str
    simhash: int
    minhash: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", _require_hex(self.sha256, "sha256", _HEX_SHA256_RE))
        if isinstance(self.simhash, bool) or not isinstance(self.simhash, int):
            raise InfrastructureValidationError(
                f"simhash must be an int, got {type(self.simhash).__name__}"
            )
        if not 0 <= self.simhash <= _MAX_SIMHASH:
            raise InfrastructureValidationError(
                f"simhash must be a 64-bit unsigned value, got {self.simhash}"
            )
        if isinstance(self.minhash, str | bytes) or not isinstance(self.minhash, Sequence):
            raise InfrastructureValidationError(
                f"minhash must be a sequence of permutation minima, "
                f"got {type(self.minhash).__name__}"
            )
        if not self.minhash:
            raise InfrastructureValidationError("minhash must not be empty")
        for value in self.minhash:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InfrastructureValidationError(
                    f"minhash entries must be non-negative ints, got {value!r}"
                )
        object.__setattr__(self, "minhash", tuple(self.minhash))


@dataclass(frozen=True)
class InfrastructureObservation:
    """One stored, passive observation of an infrastructure subject.

    ``subject_type`` must be an ontologically *infrastructure* entity
    type (``ONION_SERVICE``, ``DOMAIN``, ``URL``, ``IP_OBSERVATION``,
    ``CERTIFICATE``, ``HOSTING_ENTITY``, ``TECHNOLOGY_FINGERPRINT``,
    ``SERVICE_FINGERPRINT``); anything else fails validation so Phase 13
    can never claim evidence about content, identity, or financial
    entities.  ``evidence_ids`` is non-empty by construction: every
    observation is evidence-backed.
    """

    observation_id: str
    evidence_ids: tuple[str, ...]
    subject: str
    subject_type: EntityType
    source: str
    observed_range: TimeRange
    tls: TLSMetadata | None = None
    http: HTTPMetadata | None = None
    certificate: CertificateMetadata | None = None
    technologies: tuple[Technology, ...] = ()
    body_text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _require_text(self.observation_id, "observation_id")
        )
        object.__setattr__(self, "evidence_ids", _normalize_ids(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "subject", _require_text(self.subject, "subject"))
        object.__setattr__(self, "subject_type", _coerce_infrastructure_type(self.subject_type))
        object.__setattr__(self, "source", _require_text(self.source, "source"))
        object.__setattr__(
            self, "observed_range", _require_range(self.observed_range, "observed_range")
        )
        for name in ("tls", "http", "certificate"):
            value = getattr(self, name)
            expected = {
                "tls": TLSMetadata,
                "http": HTTPMetadata,
                "certificate": CertificateMetadata,
            }[name]
            if value is not None and not isinstance(value, expected):
                raise InfrastructureValidationError(
                    f"{name} must be a {expected.__name__} or None, got {type(value).__name__}"
                )
        if isinstance(self.technologies, str | bytes) or not isinstance(
            self.technologies, Sequence
        ):
            raise InfrastructureValidationError(
                f"technologies must be a sequence of Technology, "
                f"got {type(self.technologies).__name__}"
            )
        by_key: dict[str, Technology] = {}
        for item in self.technologies:
            if not isinstance(item, Technology):
                raise InfrastructureValidationError(
                    f"technologies entries must be Technology, got {type(item).__name__}"
                )
            by_key.setdefault(item.key, item)
        object.__setattr__(self, "technologies", tuple(by_key[key] for key in sorted(by_key)))
        if not isinstance(self.body_text, str):
            raise InfrastructureValidationError(
                f"body_text must be a string, got {type(self.body_text).__name__}"
            )

    @property
    def technology_keys(self) -> frozenset[str]:
        """Canonical technology keys used by the similarity channel."""
        return frozenset(technology.key for technology in self.technologies)


@dataclass(frozen=True)
class InfrastructureFeatures:
    """Frozen feature view produced by passive extraction.

    ``content`` is ``None`` exactly when the observation carries no body
    (an onion service answering no HTML, a header-only capture); the
    content channel then reports "unavailable" instead of comparing two
    empty fingerprints, which would otherwise score a perfect match.
    ``technology_keys`` is validated equal to the observation's own keys
    so the feature view can never drift from its source.
    """

    observation: InfrastructureObservation
    content: ContentFingerprint | None
    technology_keys: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.observation, InfrastructureObservation):
            raise InfrastructureValidationError(
                f"observation must be an InfrastructureObservation, "
                f"got {type(self.observation).__name__}"
            )
        body = self.observation.body_text
        if not body.strip():
            if self.content is not None:
                raise InfrastructureValidationError(
                    "content fingerprint must be None for an observation without body text"
                )
        else:
            if self.content is None:
                raise InfrastructureValidationError(
                    "content fingerprint is required when the observation has body text"
                )
            if not isinstance(self.content, ContentFingerprint):
                got = type(self.content).__name__
                raise InfrastructureValidationError(
                    f"content must be a ContentFingerprint or None, got {got}"
                )
            if self.content.sha256 != content_hash(body):
                raise InfrastructureValidationError(
                    "content fingerprint does not match the observation body text"
                )
        keys = frozenset(self.technology_keys)
        if keys != self.observation.technology_keys:
            raise InfrastructureValidationError(
                "technology_keys must equal the observation's technology keys "
                f"({sorted(self.observation.technology_keys)!r})"
            )
        object.__setattr__(self, "technology_keys", keys)

    @property
    def observation_id(self) -> str:
        return self.observation.observation_id

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return self.observation.evidence_ids

    @property
    def subject(self) -> str:
        return self.observation.subject

    @property
    def source(self) -> str:
        return self.observation.source

    @property
    def observed_range(self) -> TimeRange:
        return self.observation.observed_range


@dataclass(frozen=True)
class SimilarityBreakdown:
    """Per-channel similarities plus the weighted ``overall`` score.

    ``None`` marks an *unavailable* channel (metadata missing on at least
    one side); unavailable channels are excluded from the weighted mean
    rather than scored as mismatches, so missing data never masquerades
    as disagreement.  ``temporal`` is always available because every
    observation carries an :class:`TimeRange`.
    """

    temporal: float
    overall: float
    certificate: float | None = None
    content: float | None = None
    technology: float | None = None
    http: float | None = None
    tls: float | None = None

    def __post_init__(self) -> None:
        for name in ("temporal", "overall", "certificate", "content", "technology", "http", "tls"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise InfrastructureValidationError(
                    f"{name} similarity must be a number in [0, 1] or None, got {value!r}"
                )
            if not 0.0 <= float(value) <= 1.0:
                raise InfrastructureValidationError(
                    f"{name} similarity must be within [0, 1], got {value}"
                )

    @property
    def available_channels(self) -> tuple[str, ...]:
        """Names of the channels that contributed to ``overall``, in order."""
        ordered = (
            ("certificate", self.certificate),
            ("content", self.content),
            ("technology", self.technology),
            ("http", self.http),
            ("tls", self.tls),
            ("temporal", self.temporal),
        )
        return tuple(name for name, value in ordered if value is not None)


@dataclass(frozen=True)
class CorrelationThresholds:
    """Decision rule for emitting a candidate correlation.

    ``min_similarity`` is the weighted-overall floor.  A *strong channel*
    is additionally required: only identity-bearing or near-duplicate
    signals (certificate equality, near-duplicate content, near-identical
    HTTP header profile) may trigger a candidate on their own.  Commodity
    signals — TLS configuration and technology stacks — are shared by
    large numbers of unrelated services, so they can support a
    correlation but never start one (plan section 14: "Test false
    correlations using unrelated infrastructure").

    ``require_temporal_overlap`` is a hard gate: disjoint observation
    windows never correlate, because metadata seen at disjoint times
    cannot be shown to coexist.
    """

    min_similarity: float = 0.6
    min_certificate: float = 0.9
    min_content: float = 0.8
    min_http: float = 0.9
    min_temporal_overlap: float = 0.0
    require_temporal_overlap: bool = True

    def __post_init__(self) -> None:
        for name in ("min_similarity", "min_certificate", "min_content", "min_http"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise InfrastructureValidationError(
                    f"{name} must be a number in (0, 1], got {value!r}"
                )
            if not 0.0 < float(value) <= 1.0:
                raise InfrastructureValidationError(f"{name} must be within (0, 1], got {value}")
        if isinstance(self.min_temporal_overlap, bool) or not isinstance(
            self.min_temporal_overlap, int | float
        ):
            raise InfrastructureValidationError(
                f"min_temporal_overlap must be within [0, 1], got {self.min_temporal_overlap!r}"
            )
        if not 0.0 <= float(self.min_temporal_overlap) <= 1.0:
            raise InfrastructureValidationError(
                f"min_temporal_overlap must be within [0, 1], got {self.min_temporal_overlap}"
            )
        if not isinstance(self.require_temporal_overlap, bool):
            raise InfrastructureValidationError(
                "require_temporal_overlap must be a bool, "
                f"got {type(self.require_temporal_overlap).__name__}"
            )

    def strong_channel(self, breakdown: SimilarityBreakdown) -> str | None:
        """First decisive channel meeting its cutoff, or ``None``.

        Priority order is fixed (certificate, content, http) so the same
        breakdown always names the same channel and the emitted
        relationship type is deterministic.
        """
        checks = (
            ("certificate", self.min_certificate, breakdown.certificate),
            ("content", self.min_content, breakdown.content),
            ("http", self.min_http, breakdown.http),
        )
        for name, cutoff, value in checks:
            if value is not None and value >= cutoff:
                return name
        return None


#: Relationship proposed by a correlation whose certificate channel was
#: decisive; both ontology types are symmetric infrastructure relations.
_STRONG_CHANNEL_RELATIONSHIPS: dict[str, RelationshipType] = {
    "certificate": RelationshipType.CERTIFICATE_ASSOCIATED_WITH,
    "content": RelationshipType.INFRASTRUCTURE_SIMILAR_TO,
    "http": RelationshipType.INFRASTRUCTURE_SIMILAR_TO,
}


@dataclass(frozen=True)
class InfrastructureCorrelation:
    """Candidate correlation between two infrastructure observations.

    Carries the plan's full output contract: the correlation itself
    (endpoint observation ids and subjects), the ``similarity`` score and
    its per-channel breakdown, the ``evidence_ids`` involved, the
    ``time_range`` in which both observations were simultaneously valid,
    the ``sources`` that produced them, and an explicit non-empty
    ``limitations`` record of what the correlation does *not* prove.
    """

    left_observation_id: str
    right_observation_id: str
    left_subject: str
    right_subject: str
    similarity: float
    breakdown: SimilarityBreakdown
    evidence_ids: tuple[str, ...]
    time_range: TimeRange
    sources: tuple[str, ...]
    limitations: tuple[str, ...]
    strong_channel: str
    relationship_type: RelationshipType = RelationshipType.INFRASTRUCTURE_SIMILAR_TO

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "left_observation_id",
            _require_text(self.left_observation_id, "left_observation_id"),
        )
        object.__setattr__(
            self,
            "right_observation_id",
            _require_text(self.right_observation_id, "right_observation_id"),
        )
        if self.left_observation_id == self.right_observation_id:
            raise InfrastructureValidationError(
                "a correlation must join two distinct observations, "
                f"got {self.left_observation_id!r} twice"
            )
        object.__setattr__(self, "left_subject", _require_text(self.left_subject, "left_subject"))
        object.__setattr__(
            self, "right_subject", _require_text(self.right_subject, "right_subject")
        )
        if isinstance(self.similarity, bool) or not isinstance(self.similarity, int | float):
            raise InfrastructureValidationError(
                f"similarity must be a number in [0, 1], got {self.similarity!r}"
            )
        if not 0.0 <= float(self.similarity) <= 1.0:
            raise InfrastructureValidationError(
                f"similarity must be within [0, 1], got {self.similarity}"
            )
        if not isinstance(self.breakdown, SimilarityBreakdown):
            raise InfrastructureValidationError(
                f"breakdown must be a SimilarityBreakdown, got {type(self.breakdown).__name__}"
            )
        if float(self.similarity) != self.breakdown.overall:
            raise InfrastructureValidationError(
                f"similarity {self.similarity} must equal breakdown.overall "
                f"{self.breakdown.overall}"
            )
        object.__setattr__(self, "evidence_ids", _normalize_ids(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "time_range", _require_range(self.time_range, "time_range"))
        object.__setattr__(self, "sources", _normalize_ids(self.sources, "sources"))
        if isinstance(self.limitations, str) or not isinstance(self.limitations, Sequence):
            raise InfrastructureValidationError(
                f"limitations must be a sequence of statements, "
                f"got {type(self.limitations).__name__}"
            )
        notes = tuple(_require_text(note, "limitations entry") for note in self.limitations)
        if not notes:
            raise InfrastructureValidationError(
                "limitations must state at least what the correlation does not prove"
            )
        object.__setattr__(self, "limitations", notes)
        object.__setattr__(
            self, "strong_channel", _require_text(self.strong_channel, "strong_channel")
        )
        if self.strong_channel not in _STRONG_CHANNEL_RELATIONSHIPS:
            raise InfrastructureValidationError(
                f"strong_channel must be one of {sorted(_STRONG_CHANNEL_RELATIONSHIPS)}, "
                f"got {self.strong_channel!r}"
            )
        if isinstance(self.relationship_type, str) and not isinstance(
            self.relationship_type, RelationshipType
        ):
            try:
                object.__setattr__(
                    self, "relationship_type", RelationshipType(self.relationship_type)
                )
            except ValueError as exc:
                raise InfrastructureValidationError(
                    f"unknown relationship type {self.relationship_type!r}"
                ) from exc
        if RELATIONSHIP_DIRECTION.get(self.relationship_type) is not RelationDirection.SYMMETRIC:
            raise InfrastructureValidationError(
                f"relationship {self.relationship_type.value!r} must be symmetric: a candidate "
                "correlation joins two undirected infrastructure observations"
            )


class ChangeKind(StrEnum):
    """Kinds of historical change detected between observation windows."""

    CERTIFICATE_ROTATION = "certificate_rotation"
    HEADER_CHANGE = "header_change"
    TECHNOLOGY_CHANGE = "technology_change"
    TLS_CHANGE = "tls_change"


@dataclass(frozen=True)
class HistoricalChange:
    """One observed metadata change, bounded by two observation windows.

    ``window`` is the interval in which the change must have occurred:
    the space between the previous window's end and the next window's
    start (their intersection when the windows overlap).  The exact
    moment is unknowable from passive observation and is listed under
    ``limitations`` rather than invented.
    """

    change_id: str
    subject: str
    field: str
    kind: ChangeKind
    old_value: str
    new_value: str
    window: TimeRange
    evidence_ids: tuple[str, ...]
    sources: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", _require_text(self.change_id, "change_id"))
        object.__setattr__(self, "subject", _require_text(self.subject, "subject"))
        object.__setattr__(self, "field", _require_text(self.field, "field"))
        if isinstance(self.kind, str) and not isinstance(self.kind, ChangeKind):
            try:
                object.__setattr__(self, "kind", ChangeKind(self.kind))
            except ValueError as exc:
                raise InfrastructureValidationError(f"unknown change kind {self.kind!r}") from exc
        object.__setattr__(self, "old_value", _require_text(self.old_value, "old_value"))
        object.__setattr__(self, "new_value", _require_text(self.new_value, "new_value"))
        if self.old_value == self.new_value:
            raise InfrastructureValidationError(
                f"change of {self.field!r} must alter the value, got {self.old_value!r} twice"
            )
        object.__setattr__(self, "window", _require_range(self.window, "window"))
        object.__setattr__(self, "evidence_ids", _normalize_ids(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "sources", _normalize_ids(self.sources, "sources"))
        if isinstance(self.limitations, str) or not isinstance(self.limitations, Sequence):
            got = type(self.limitations).__name__
            raise InfrastructureValidationError(
                f"limitations must be a sequence of statements, got {got}"
            )
        notes = tuple(_require_text(note, "limitations entry") for note in self.limitations)
        if not notes:
            raise InfrastructureValidationError(
                "limitations must state at least what the change does not prove"
            )
        object.__setattr__(self, "limitations", notes)
