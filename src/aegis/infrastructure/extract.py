"""Passive extraction of infrastructure features from stored payloads (Phase 13).

Implementation Plan section 14 fixes *passive* feature extraction — TLS
metadata, HTTP metadata, content fingerprints, technology fingerprints,
certificate metadata — over data that has already been collected, and
explicitly forbids intrusive origin discovery.  This module therefore
only ever reads in-memory ``dict`` payloads (synthetic observation
records or the ``metadata`` of a canonical
:class:`aegis.schemas.Evidence`); it opens no sockets, resolves no
names, and probes nothing.

Payload shape (only the wrapper keys are required)::

    observation_id   str
    evidence_ids     sequence[str]           (non-empty)
    subject          str                     e.g. "abcd...onion"
    subject_type     EntityType value        (infrastructure types only)
    source           str
    observed_range   TimeRange | {"start": datetime, "end": datetime}
    tls              {"version", "cipher_suite"?, "alpn"?, "ja3"?}
    http             {"status_code", "server"?, "content_type"?, "headers"?}
    certificate      {"fingerprint_sha256", "subject", "issuer",
                      "serial_number", "not_before"?, "not_after"?,
                      "sans"?, "spki_sha256"?}
    technologies     sequence[str | {"name", "version"?}]
    body             str                    (page text for content fingerprints)

Unknown keys are preserved but ignored so collectors can attach their
own provenance without breaking extraction.  Missing or malformed keys
raise :class:`ExtractionError`; values that reach a value object and
fail its invariants raise :class:`InfrastructureValidationError` — both
subclasses of :class:`InfrastructureError`, and payload entry points
translate the latter into the former so callers see one error type.
Datetime values may be ``datetime`` instances or ISO-8601 strings, but
must be timezone-aware: naive timestamps are rejected rather than
silently localised.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from aegis.infrastructure.types import (
    CertificateMetadata,
    ContentFingerprint,
    ExtractionError,
    HTTPMetadata,
    InfrastructureFeatures,
    InfrastructureObservation,
    InfrastructureValidationError,
    Technology,
    TimeRange,
    TLSMetadata,
)
from aegis.normalization import content_hash, minhash_signatures, simhash64
from aegis.ontology import EntityType
from aegis.schemas import Evidence


def _text(container: Mapping[str, object], key: str, path: str) -> str:
    if key not in container:
        raise ExtractionError(f"{path}.{key}: required text field is missing")
    value = container[key]
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f"{path}.{key} must be a non-empty string, got {value!r}")
    return value.strip()


def _optional_text(container: Mapping[str, object], key: str, path: str) -> str | None:
    if key not in container or container[key] is None:
        return None
    value = container[key]
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f"{path}.{key} must be a non-empty string or null, got {value!r}")
    return value.strip()


def _aware(
    container: Mapping[str, object], key: str, path: str, *, required: bool
) -> datetime | None:
    if key not in container or container[key] is None:
        if required:
            raise ExtractionError(f"{path}.{key}: required datetime field is missing")
        return None
    value = container[key]
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ExtractionError(
                f"{path}.{key} is not a valid ISO-8601 datetime: {value!r}"
            ) from exc
    else:
        raise ExtractionError(
            f"{path}.{key} must be a datetime or ISO-8601 string, got {type(value).__name__}"
        )
    if moment.tzinfo is None:
        raise ExtractionError(f"{path}.{key} must be timezone-aware (pass tzinfo=UTC)")
    return moment


def _string_sequence(container: Mapping[str, object], key: str, path: str) -> tuple[str, ...]:
    if key not in container or container[key] is None:
        return ()
    value = container[key]
    if isinstance(value, str | bytes):
        raise ExtractionError(f"{path}.{key} must be a sequence of strings, not a bare string")
    if not isinstance(value, Sequence):
        raise ExtractionError(f"{path}.{key} must be a sequence, got {type(value).__name__}")
    entries: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ExtractionError(f"{path}.{key}[{index}] must be a non-empty string, got {item!r}")
        entries.append(item.strip())
    return tuple(entries)


def _mapping(container: Mapping[str, object], key: str, path: str) -> Mapping[str, object] | None:
    if key not in container or container[key] is None:
        return None
    value = container[key]
    if not isinstance(value, Mapping):
        raise ExtractionError(f"{path}.{key} must be a mapping, got {type(value).__name__}")
    return value


def _entity_type(container: Mapping[str, object], key: str, path: str) -> EntityType:
    value = container[key]
    if isinstance(value, EntityType):
        return value
    if isinstance(value, str):
        try:
            return EntityType(value)
        except ValueError as exc:
            raise ExtractionError(f"{path}.{key}: unknown entity type {value!r}") from exc
    raise ExtractionError(f"{path}.{key} must be an entity type value, got {type(value).__name__}")


def _wrap_invalid[R, **P](
    path: str, builder: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    """Run a value-object builder, re-raising its invariant error with context."""
    try:
        return builder(*args, **kwargs)
    except InfrastructureValidationError as exc:
        raise ExtractionError(f"invalid {path} payload: {exc}") from exc


# ------------------------------------------------------------ feature families


def extract_tls_metadata(payload: Mapping[str, object]) -> TLSMetadata:
    """TLS metadata family from a stored ``tls`` payload mapping."""
    version = _text(payload, "version", "tls")
    cipher_suite = _optional_text(payload, "cipher_suite", "tls")
    alpn = _string_sequence(payload, "alpn", "tls")
    ja3 = _optional_text(payload, "ja3", "tls")
    return _wrap_invalid(
        "tls",
        TLSMetadata,
        version=version,
        cipher_suite=cipher_suite,
        alpn=alpn,
        ja3=ja3,
    )


def extract_http_metadata(payload: Mapping[str, object]) -> HTTPMetadata:
    """HTTP metadata family from a stored ``http`` payload mapping."""
    if "status_code" not in payload:
        raise ExtractionError("http.status_code: required field is missing")
    raw_status = payload["status_code"]
    status_code: object = raw_status
    if isinstance(raw_status, str) and raw_status.strip().isdigit():
        status_code = int(raw_status.strip())
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise ExtractionError(f"http.status_code must be an int, got {type(raw_status).__name__}")
    server = _optional_text(payload, "server", "http")
    content_type = _optional_text(payload, "content_type", "http")
    headers_payload = _mapping(payload, "headers", "http") or {}
    headers: dict[str, str] = {}
    for raw_name, raw_value in headers_payload.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ExtractionError(f"http.headers has a non-string header name: {raw_name!r}")
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ExtractionError(
                f"http.headers[{raw_name!r}] must be a non-empty string, got {raw_value!r}"
            )
        headers[raw_name] = raw_value
    return _wrap_invalid(
        "http",
        HTTPMetadata,
        status_code=status_code,
        server=server,
        content_type=content_type,
        headers=headers,
    )


def extract_certificate_metadata(payload: Mapping[str, object]) -> CertificateMetadata:
    """Certificate metadata family from a stored ``certificate`` payload mapping."""
    fingerprint = _text(payload, "fingerprint_sha256", "certificate")
    subject = _text(payload, "subject", "certificate")
    issuer = _text(payload, "issuer", "certificate")
    serial_number = _text(payload, "serial_number", "certificate")
    not_before = _aware(payload, "not_before", "certificate", required=False)
    not_after = _aware(payload, "not_after", "certificate", required=False)
    sans = _string_sequence(payload, "sans", "certificate")
    spki_sha256 = _optional_text(payload, "spki_sha256", "certificate")
    return _wrap_invalid(
        "certificate",
        CertificateMetadata,
        fingerprint_sha256=fingerprint,
        subject=subject,
        issuer=issuer,
        serial_number=serial_number,
        not_before=not_before,
        not_after=not_after,
        sans=sans,
        spki_sha256=spki_sha256,
    )


def extract_technologies(values: object, *, path: str = "technologies") -> tuple[Technology, ...]:
    """Technology fingerprint family: ``"nginx:1.18"`` strings or mappings."""
    if values is None:
        return ()
    if isinstance(values, str | bytes):
        raise ExtractionError(f"{path} must be a sequence, not a bare string")
    if not isinstance(values, Sequence):
        raise ExtractionError(f"{path} must be a sequence, got {type(values).__name__}")
    technologies: list[Technology] = []
    for index, item in enumerate(values):
        item_path = f"{path}[{index}]"
        if isinstance(item, str):
            raw = item.strip()
            if not raw:
                raise ExtractionError(f"{item_path} must be a non-empty string")
            raw_name, separator, raw_version = raw.partition(":")
            technologies.append(
                _wrap_invalid(
                    item_path,
                    Technology,
                    name=raw_name.strip(),
                    version=raw_version.strip() if separator and raw_version.strip() else None,
                )
            )
        elif isinstance(item, Mapping):
            name = _text(item, "name", item_path)
            version = _optional_text(item, "version", item_path)
            technologies.append(_wrap_invalid(item_path, Technology, name=name, version=version))
        else:
            raise ExtractionError(
                f"{item_path} must be a string or a mapping with 'name', got {type(item).__name__}"
            )
    return tuple(technologies)


def content_fingerprint(text: str) -> ContentFingerprint:
    """Fingerprint a body through the Phase 06 normalization vocabulary.

    SHA-256, 64-bit SimHash, and 64-permutation MinHash come straight
    from :mod:`aegis.normalization` — no second fingerprint algorithm is
    introduced here.
    """
    if not isinstance(text, str) or not text.strip():
        raise InfrastructureValidationError("cannot fingerprint blank content")
    return ContentFingerprint(
        sha256=content_hash(text),
        simhash=simhash64(text),
        minhash=minhash_signatures(text),
    )


def extract_observation(payload: Mapping[str, object]) -> InfrastructureObservation:
    """Build one validated observation from a stored payload mapping."""
    if not isinstance(payload, Mapping):
        raise ExtractionError(
            f"observation payload must be a mapping, got {type(payload).__name__}"
        )
    observation_id = _text(payload, "observation_id", "observation")
    evidence_ids = _string_sequence(payload, "evidence_ids", "observation")
    subject = _text(payload, "subject", "observation")
    subject_type = _entity_type(payload, "subject_type", "observation")
    source = _text(payload, "source", "observation")
    observed_range = _observed_range(payload)
    tls_payload = _mapping(payload, "tls", "observation")
    http_payload = _mapping(payload, "http", "observation")
    certificate_payload = _mapping(payload, "certificate", "observation")
    tls = extract_tls_metadata(tls_payload) if tls_payload is not None else None
    http = extract_http_metadata(http_payload) if http_payload is not None else None
    certificate = (
        extract_certificate_metadata(certificate_payload)
        if certificate_payload is not None
        else None
    )
    technologies = extract_technologies(payload.get("technologies"))
    body_text = payload.get("body", "")
    if not isinstance(body_text, str):
        raise ExtractionError(f"observation.body must be a string, got {type(body_text).__name__}")
    return _wrap_invalid(
        "observation",
        InfrastructureObservation,
        observation_id=observation_id,
        evidence_ids=evidence_ids,
        subject=subject,
        subject_type=subject_type,
        source=source,
        observed_range=observed_range,
        tls=tls,
        http=http,
        certificate=certificate,
        technologies=technologies,
        body_text=body_text,
    )


def _observed_range(payload: Mapping[str, object]) -> TimeRange:
    if "observed_range" not in payload or payload["observed_range"] is None:
        raise ExtractionError("observation.observed_range: required field is missing")
    value = payload["observed_range"]
    if isinstance(value, TimeRange):
        return value
    if not isinstance(value, Mapping):
        raise ExtractionError(
            "observed_range must be a TimeRange or a {'start', 'end'} mapping, "
            f"got {type(value).__name__}"
        )
    start = _aware(value, "start", "observed_range", required=True)
    end = _aware(value, "end", "observed_range", required=True)
    if start is None or end is None:  # required=True: unreachable, kept for the type checker
        raise ExtractionError("observed_range.start and observed_range.end are required")
    return _wrap_invalid("observed_range", TimeRange, start, end)


def extract_features(observation: InfrastructureObservation) -> InfrastructureFeatures:
    """Freeze an observation's derived feature view (content + tech keys)."""
    if not isinstance(observation, InfrastructureObservation):
        raise ExtractionError(
            f"extract_features expects an InfrastructureObservation, "
            f"got {type(observation).__name__}"
        )
    content = content_fingerprint(observation.body_text) if observation.body_text.strip() else None
    return InfrastructureFeatures(
        observation=observation,
        content=content,
        technology_keys=observation.technology_keys,
    )


# ------------------------------------------------ canonical evidence adapter


def payload_from_evidence(
    evidence: Evidence,
    *,
    subject: str,
    subject_type: EntityType | str,
    observed_range: TimeRange | None = None,
) -> dict[str, object]:
    """Build an observation payload from a canonical :class:`Evidence` record.

    The evidence ``metadata`` supplies the feature families (``tls``,
    ``http``, ``certificate``, ``technologies``, ``body``); the wrapper
    fields come from the evidence record itself, so the observation's
    ``source`` is the registry ``source_id`` and its ``evidence_ids`` is
    exactly the record's own id.  When no range is supplied it is derived
    from ``observed_at``/``collected_at`` — the interval during which the
    artifact was true of the world and reached the collector.  Explicit
    wrapper keys in the payload always win over colliding metadata keys.
    """
    if not isinstance(evidence, Evidence):
        raise ExtractionError(
            f"expected a canonical Evidence record, got {type(evidence).__name__}"
        )
    if observed_range is None:
        observed_range = _range_from_evidence(evidence)
    payload: dict[str, object] = dict(evidence.metadata)
    payload.update(
        {
            "observation_id": str(evidence.evidence_id),
            "evidence_ids": (str(evidence.evidence_id),),
            "subject": subject,
            "subject_type": subject_type,
            "source": str(evidence.source_id),
            "observed_range": observed_range,
        }
    )
    return payload


def _range_from_evidence(evidence: Evidence) -> TimeRange:
    collected = evidence.collected_at
    if collected.tzinfo is None:
        raise ExtractionError("evidence.collected_at must be timezone-aware (pass tzinfo=UTC)")
    start = evidence.observed_at if evidence.observed_at is not None else collected
    if start.tzinfo is None:
        raise ExtractionError("evidence.observed_at must be timezone-aware (pass tzinfo=UTC)")
    if start > collected:
        raise ExtractionError(
            f"evidence.observed_at {start.isoformat()} must not precede "
            f"collected_at {collected.isoformat()}"
        )
    return TimeRange(start, collected)


def observation_from_evidence(
    evidence: Evidence,
    *,
    subject: str,
    subject_type: EntityType | str,
    observed_range: TimeRange | None = None,
) -> InfrastructureObservation:
    """Extract an observation directly from a canonical evidence record."""
    return extract_observation(
        payload_from_evidence(
            evidence, subject=subject, subject_type=subject_type, observed_range=observed_range
        )
    )
