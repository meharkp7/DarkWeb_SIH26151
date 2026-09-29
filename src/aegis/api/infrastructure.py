"""Tor hidden-service misconfiguration and clearnet-correlation API.

The problem statement asks for two things this router exists to serve:

* the **misconfigurations** in Tor hidden services — exposed server-status
  pages, certificates tied to clearnet domains, default service banners,
  descriptor inconsistencies, and fingerprints shared with a clearnet host;
* the **correlation** of those services against clearnet infrastructure, so a
  candidate origin server can be pointed at.

The value objects and the scoring that produce both already exist in
:mod:`aegis.infrastructure`.  What was missing was anywhere to *read* the
results, which is what this module adds.  Four rules hold across every route:

* **The library is the only scorer.**  Nothing here reimplements a similarity
  function, and nothing here invents a score.  A stored observation is
  reconstructed into an :class:`InfrastructureFeatures` view and handed to
  :func:`aegis.infrastructure.correlate.correlate_all`, which decides what
  correlates.  If a record cannot be reconstructed it is *reported as skipped
  with a reason*, never scored against a guess.
* **Limitations travel with the finding.**  Every row carries the detector's
  own ``limitations`` list verbatim.  Shared hosting, a CDN terminating TLS
  and a reused default banner all produce these signals legitimately, so a
  misconfiguration rendered without its alternative explanation is a false
  accusation with a number attached.
* **Absence is not zero.**  ``confidence`` is nullable in the model and stays
  nullable here: a detector the platform declines to score reads as "not
  scored", and a ``min_confidence`` filter excludes it rather than treating it
  as the worst possible score.
* **Only ``POST /correlate`` writes.**  Every other route is a read, and the
  read routes apply their filters server-side because the row count a filter
  returns is part of what an analyst is reading.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from aegis.api.deps import get_db
from aegis.db.audit import AuditService
from aegis.db.models import (
    CaseRecord,
    InfrastructureFindingRecord,
    InfrastructureMatchRecord,
    InfrastructureObservationRecord,
)
from aegis.infrastructure.correlate import CHANNEL_ORDER, correlate_all
from aegis.infrastructure.extract import extract_features, extract_observation
from aegis.infrastructure.types import (
    CorrelationThresholds,
    InfrastructureCorrelation,
    InfrastructureError,
    InfrastructureFeatures,
    SimilarityBreakdown,
)

router = APIRouter(prefix="/api/v1/infrastructure", tags=["infrastructure"])

#: Version of the ``features_json`` document this router reads.  Bumped when
#: the stored shape changes; an unreadable version is a reported skip rather
#: than a silent empty correlation run.
FEATURES_SCHEMA_VERSION = "aegis-infrastructure/1"

#: The five misconfiguration classes the problem statement names, in the order
#: they read on screen.  ``InfrastructureFindingRecord.kind`` is constrained to
#: exactly this set, so a detector can never file a finding as a category the
#: platform does not actually detect.
FINDING_KINDS: tuple[str, ...] = (
    "exposed_status_page",
    "clearnet_certificate",
    "default_banner",
    "descriptor_inconsistency",
    "shared_fingerprint",
)

FINDING_KIND_LABELS: dict[str, str] = {
    "exposed_status_page": "Exposed status page",
    "clearnet_certificate": "Clearnet-tied certificate",
    "default_banner": "Default service banner",
    "descriptor_inconsistency": "Descriptor inconsistency",
    "shared_fingerprint": "Shared fingerprint",
}

FINDING_SEVERITIES: tuple[str, ...] = (
    "critical",
    "high",
    "medium",
    "low",
    "informational",
)

SEVERITY_RANK: dict[str, int] = {name: index for index, name in enumerate(FINDING_SEVERITIES)}

#: A commodity channel — TLS configuration, technology stack — is shared by
#: large numbers of unrelated services, so :func:`correlate_all` will never
#: start a candidate on one.  It still counts as *corroboration* at or above
#: this score, which is what separates "one 0.92 on JA3" from "0.92 confirmed
#: by certificate, TLS and content".
NEAR_IDENTICAL = 0.9

#: Channels that can corroborate a match.  ``temporal`` is deliberately absent:
#: every observation carries a time range, so it is always available and would
#: count as a second voice in almost every pair — including two services that
#: have nothing else in common and were simply both online at the same time.
CORROBORATING_CHANNELS: tuple[str, ...] = (
    "certificate",
    "content",
    "http",
    "tls",
    "technology",
)


# --------------------------------------------------------------------------
# features_json  ->  InfrastructureFeatures
#
# The adapter lives here rather than in ``aegis.infrastructure`` because that
# package is a tested, shared value-object library: the storage envelope is an
# API concern, the scoring is not, and the two must not be entangled.
# --------------------------------------------------------------------------


class _FeatureReconstructionError(InfrastructureError):
    """A stored observation could not be turned back into a feature view."""


def _read_rule(
    min_similarity: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    min_certificate: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    min_content: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    min_http: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    min_temporal_overlap: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    require_temporal_overlap: bool | None = None,
) -> CorrelationThresholdsInput:
    """Reconstruct a decision rule from query parameters.

    The six cutoffs are supplied as flat parameters rather than as one object
    because a read route needs to *re-interpret* stored rows under a rule, not
    set one. Supplying some of them and not others is refused: a half-stated
    rule is a rule nobody wrote, and silently filling the gaps from the
    library defaults would make the readout disagree with the run that
    produced the rows.
    """
    supplied = (
        min_similarity,
        min_certificate,
        min_content,
        min_http,
        min_temporal_overlap,
        require_temporal_overlap,
    )
    if not any(value is not None for value in supplied):
        return READ_BACK_RULE
    if (
        min_similarity is None
        or min_certificate is None
        or min_content is None
        or min_http is None
        or min_temporal_overlap is None
        or require_temporal_overlap is None
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Supply all six cutoffs together (min_similarity, min_certificate, "
                "min_content, min_http, min_temporal_overlap, require_temporal_overlap) "
                "or none of them."
            ),
        )
    return CorrelationThresholdsInput(
        min_similarity=min_similarity,
        min_certificate=min_certificate,
        min_content=min_content,
        min_http=min_http,
        min_temporal_overlap=min_temporal_overlap,
        require_temporal_overlap=require_temporal_overlap,
    )


def _like(term: str) -> str:
    """Escape LIKE metacharacters so a subject filter matches literally."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _stored_payload(stored: Mapping[str, object]) -> Mapping[str, object]:
    """The extraction payload inside a ``features_json`` document.

    Accepts both the enveloped form written by the seeder
    (``{"observation": {...}}``) and a bare payload, so a record written by
    hand is still readable rather than silently correlating nothing.
    """
    inner = stored.get("observation")
    if isinstance(inner, Mapping):
        return inner
    return stored


def _stored_range(
    payload: Mapping[str, object], record: InfrastructureObservationRecord
) -> dict[str, object]:
    """The observation window, falling back to the instant on the row.

    A zero-width window is a legitimate instant observation, but two
    observations at different instants share no duration and the library's
    temporal gate would reject every pair, so the window is preferred and the
    single ``observed_at`` column is only the fallback.
    """
    value = payload.get("observed_range")
    if isinstance(value, Mapping):
        start = value.get("start") or record.observed_at
        end = value.get("end") or start
        return {"start": start, "end": end}
    return {"start": record.observed_at, "end": record.observed_at}


def features_from_record(record: InfrastructureObservationRecord) -> InfrastructureFeatures:
    """Reconstruct the library's feature view for one stored observation.

    The row's identity, subject and source are authoritative — they are what
    the tables index and filter on — so they override whatever the JSON
    document claims.  Everything the score actually reads (TLS, HTTP,
    certificate, technologies, body) comes from the document.

    Raises :class:`_FeatureReconstructionError` when the document cannot be
    read, which callers surface as a named skip rather than as a zero score.
    """
    stored = record.features_json or {}
    if not isinstance(stored, Mapping):
        raise _FeatureReconstructionError("features_json is not a JSON object")
    version = stored.get("schema_version")
    if version is not None and version != FEATURES_SCHEMA_VERSION:
        raise _FeatureReconstructionError(
            f"features_json schema_version {version!r} is not {FEATURES_SCHEMA_VERSION!r}"
        )
    payload = _stored_payload(stored)

    evidence: list[str] = []
    raw_ids = payload.get("evidence_ids")
    if isinstance(raw_ids, Sequence) and not isinstance(raw_ids, str | bytes):
        evidence.extend(str(item) for item in raw_ids if isinstance(item, str) and item.strip())
    if record.evidence_id is not None:
        evidence.append(str(record.evidence_id))
    if not evidence:
        raise _FeatureReconstructionError(
            "observation carries no evidence id; an observation without evidence is not scoreable"
        )

    body: dict[str, object] = {
        key: value for key, value in payload.items() if key not in {"schema_version", "observation"}
    }
    body.update(
        {
            "observation_id": str(record.observation_id),
            "evidence_ids": sorted(set(evidence)),
            "subject": record.subject,
            "source": record.source,
            "observed_range": _stored_range(payload, record),
        }
    )
    try:
        observation = extract_observation(body)
        features = extract_features(observation)
    except InfrastructureError as exc:
        raise _FeatureReconstructionError(str(exc)) from exc
    _assert_stored_features_agree(stored, features, record)
    return features


def _assert_stored_features_agree(
    stored: Mapping[str, object],
    features: InfrastructureFeatures,
    record: InfrastructureObservationRecord,
) -> None:
    """Refuse to score an observation whose stored features disagree with its payload.

    ``features_json`` holds the derived content fingerprint as well as the
    payload it was derived from.  If the two disagree, the row has been edited
    in one half only, and scoring it would mean scoring against a fingerprint
    the observation does not actually have.
    """
    content = stored.get("content")
    if isinstance(content, Mapping) and features.content is not None:
        recorded = content.get("sha256")
        if isinstance(recorded, str) and recorded != features.content.sha256:
            raise _FeatureReconstructionError(
                "stored content fingerprint does not match the stored body"
            )
    keys = stored.get("technology_keys")
    if isinstance(keys, Sequence) and not isinstance(keys, str | bytes):
        if frozenset(str(key) for key in keys) != features.technology_keys:
            raise _FeatureReconstructionError(
                "stored technology keys do not match the stored technologies"
            )


def features_document(
    *,
    observation_id: str,
    evidence_ids: Sequence[str],
    subject: str,
    subject_type: str,
    source: str,
    observed_range: Mapping[str, object],
    tls: Mapping[str, object] | None,
    http: Mapping[str, object] | None,
    certificate: Mapping[str, object] | None,
    technologies: Sequence[str],
    body: str,
) -> dict[str, object]:
    """Build the ``features_json`` document, with the derived view frozen in.

    Written by the seeder and read back by :func:`features_from_record`.  The
    derived content fingerprint is stored rather than recomputed on every read
    so a drift between the two halves of the document is detectable.
    """
    payload: dict[str, object] = {
        "observation_id": observation_id,
        "evidence_ids": list(evidence_ids),
        "subject": subject,
        "subject_type": subject_type,
        "source": source,
        "observed_range": dict(observed_range),
    }
    if tls is not None:
        payload["tls"] = dict(tls)
    if http is not None:
        payload["http"] = dict(http)
    if certificate is not None:
        payload["certificate"] = dict(certificate)
    if technologies:
        payload["technologies"] = list(technologies)
    if body.strip():
        payload["body"] = body
    observation = extract_observation(payload)
    features: InfrastructureFeatures = extract_features(observation)
    content: dict[str, object] | None = None
    if features.content is not None:
        content = {
            "sha256": features.content.sha256,
            "simhash": features.content.simhash,
            "minhash": list(features.content.minhash),
        }
    return {
        "schema_version": FEATURES_SCHEMA_VERSION,
        "observation": payload,
        "content": content,
        "technology_keys": sorted(features.technology_keys),
    }


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class InfrastructureFinding(BaseModel):
    """One misconfiguration in one hidden service, with its alternative reading.

    ``subject`` and ``network`` are joined in rather than left to a second
    request: a finding without the address it was found on is not actionable.
    """

    model_config = ConfigDict(frozen=True)

    finding_id: UUID
    observation_id: UUID
    case_id: UUID | None
    subject: str
    network: str
    kind: str
    kind_label: str
    severity: str
    detail: str
    #: What this finding does not prove, in the detector's own words.
    limitations: list[str]
    #: ``None`` means the platform does not score this detector. It is not 0.
    confidence: float | None
    detected_at: datetime
    observed_at: datetime
    evidence_id: UUID | None
    metadata: dict[str, object]


class ChannelScores(BaseModel):
    """The per-channel breakdown behind one correlation.

    ``temporal`` is always present; every other channel is ``null`` when the
    metadata was not observed on both sides, which is *missing data* and not
    disagreement.  A client that renders a null channel as 0 turns an absent
    measurement into evidence against the correlation.
    """

    model_config = ConfigDict(frozen=True)

    certificate: float | None
    content: float | None
    technology: float | None
    http: float | None
    tls: float | None
    temporal: float
    available_channels: list[str]
    #: Channels that clear their own decisive cutoff, strongest first.  One
    #: entry here means the whole score rests on a single dimension.
    decisive_channels: list[str]


class InfrastructureMatch(BaseModel):
    """A candidate origin server: one hidden service, one clearnet host.

    ``overall`` is the weighted mean over the *available* channels.
    ``single_channel`` is the honest headline: a high score carried by one
    dimension is a weaker finding than the same score corroborated across
    certificate, TLS and content, and the two must not read alike.
    """

    model_config = ConfigDict(frozen=True)

    match_id: UUID
    case_id: UUID | None
    onion_observation_id: UUID
    clearnet_observation_id: UUID
    onion_subject: str
    clearnet_subject: str
    overall: float
    breakdown: ChannelScores
    strongest_channel: str | None
    single_channel: bool
    limitations: list[str]
    sources: list[str]
    evidence_ids: list[str]
    detected_at: datetime
    metadata: dict[str, object]


class InfrastructureObservation(BaseModel):
    """One stored observation and the features extracted from it."""

    model_config = ConfigDict(frozen=True)

    observation_id: UUID
    subject: str
    network: str
    source: str
    observed_at: datetime
    observed_until: datetime | None
    case_id: UUID | None
    evidence_id: UUID | None
    #: The verbatim ``features_json`` document, including the derived content
    #: fingerprint and technology keys. Returned whole so an analyst can check
    #: a correlation's inputs rather than trust the score.
    features: dict[str, object]
    finding_count: int = 0
    match_count: int = 0


class InfrastructureSummary(BaseModel):
    """Counts for the whole capability, with the weak-match figure up front."""

    model_config = ConfigDict(frozen=True)

    findings_total: int
    findings_by_kind: dict[str, int]
    findings_by_severity: dict[str, int]
    #: Findings the platform declines to score are counted separately rather
    #: than folded into a confidence average.
    findings_unscored: int
    observations_total: int
    onion_services: int
    clearnet_hosts: int
    matches_total: int
    #: The headline: matches whose score is carried by exactly one channel.
    single_channel_matches: int
    matches_by_strongest_channel: dict[str, int]
    earliest_observation: datetime | None
    latest_observation: datetime | None


class CorrelationThresholdsInput(BaseModel):
    """The decision rule for one correlation run, supplied by the caller.

    Every field is required.  A correlation that silently used the library's
    defaults would look like a deliberate threshold choice to whoever read the
    result, and the defaults are a claim about what counts as shared
    infrastructure.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_similarity: float = Field(gt=0.0, le=1.0)
    min_certificate: float = Field(gt=0.0, le=1.0)
    min_content: float = Field(gt=0.0, le=1.0)
    min_http: float = Field(gt=0.0, le=1.0)
    min_temporal_overlap: float = Field(ge=0.0, le=1.0)
    require_temporal_overlap: bool

    def to_thresholds(self) -> CorrelationThresholds:
        return CorrelationThresholds(
            min_similarity=self.min_similarity,
            min_certificate=self.min_certificate,
            min_content=self.min_content,
            min_http=self.min_http,
            min_temporal_overlap=self.min_temporal_overlap,
            require_temporal_overlap=self.require_temporal_overlap,
        )


#: The library's own defaults, used only to *read* stored rows back so their
#: decisive-channel split can be shown.  A correlation run never falls back to
#: them: ``POST /correlate`` requires the caller to state the rule it ran under.
READ_BACK_RULE: Final[CorrelationThresholdsInput] = CorrelationThresholdsInput(
    min_similarity=0.6,
    min_certificate=0.9,
    min_content=0.8,
    min_http=0.9,
    min_temporal_overlap=0.0,
    require_temporal_overlap=True,
)


class SkippedObservation(BaseModel):
    """An observation that could not be scored, and why.

    Reported rather than dropped: a correlation run that quietly ignored a
    twelfth of its inputs presents its result as if it had seen all of them.
    """

    model_config = ConfigDict(frozen=True)

    observation_id: UUID
    subject: str
    reason: str


class InfrastructureCorrelateRequest(BaseModel):
    """Run the library's correlation over stored observations.

    ``case_id`` is required.  The router writes match rows, and an
    unattributable finding is a finding nobody can revisit, contradict or
    close.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    thresholds: CorrelationThresholdsInput
    observation_ids: list[UUID] | None = None
    networks: list[Literal["onion", "clearnet"]] = Field(default=["onion", "clearnet"])
    since: datetime | None = None
    until: datetime | None = None
    #: Cap on rows written, newest scores first. ``None`` writes every
    #: candidate that cleared the thresholds.
    limit: Annotated[int | None, Field(ge=1, le=500)] = None


class InfrastructureCorrelateResponse(BaseModel):
    """What the run created, what it left alone, and what it could not read."""

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    thresholds: CorrelationThresholdsInput
    observations_considered: int
    pairs_evaluated: int
    #: Candidates the library returned, before the cross-network restriction.
    candidates: int
    #: Candidates dropped because both sides were on the same network. The
    #: record has a single onion/clearnet shape and this capability is about
    #: pointing at a clearnet origin, so a same-network pair is not this table.
    same_network_candidates: int
    created: list[InfrastructureMatch]
    #: Candidates that were already recorded. Returned, never overwritten, so
    #: a re-run reports the store rather than pretending to have found it.
    existing: list[InfrastructureMatch]
    skipped_observations: list[SkippedObservation]
    #: The correlation's own limitations, verbatim and deduplicated. This is
    #: what the run does *not* establish, in the library's own words.
    limitations: list[str]
    correlated_at: datetime


# --------------------------------------------------------------------------
# Row -> schema helpers
# --------------------------------------------------------------------------


def decisive_channels(
    breakdown: SimilarityBreakdown, thresholds: CorrelationThresholds
) -> tuple[str, ...]:
    """Channels that clear their own decisive cutoff, strongest first.

    Mirrors :meth:`CorrelationThresholds.strong_channel` for the three
    identity-bearing channels and adds the two commodity channels at a
    near-identical cutoff.  ``temporal`` never counts — see
    :data:`CORROBORATING_CHANNELS`.
    """
    cutoffs: dict[str, float] = {
        "certificate": thresholds.min_certificate,
        "content": thresholds.min_content,
        "http": thresholds.min_http,
        "tls": NEAR_IDENTICAL,
        "technology": NEAR_IDENTICAL,
    }
    found: list[tuple[float, str]] = []
    for name in CORROBORATING_CHANNELS:
        value = getattr(breakdown, name)
        if value is not None and value >= cutoffs[name]:
            found.append((value, name))
    found.sort(key=lambda item: (-item[0], CHANNEL_ORDER.index(item[1])))
    return tuple(name for _, name in found)


def _channel_scores(
    breakdown: SimilarityBreakdown, thresholds: CorrelationThresholds
) -> ChannelScores:
    decisive = decisive_channels(breakdown, thresholds)
    return ChannelScores(
        certificate=breakdown.certificate,
        content=breakdown.content,
        technology=breakdown.technology,
        http=breakdown.http,
        tls=breakdown.tls,
        temporal=breakdown.temporal,
        available_channels=list(breakdown.available_channels),
        decisive_channels=list(decisive),
    )


def _finding_schema(
    record: InfrastructureFindingRecord,
    subject: str,
    network: str,
    observed_at: datetime,
) -> InfrastructureFinding:
    return InfrastructureFinding(
        finding_id=record.finding_id,
        observation_id=record.observation_id,
        case_id=record.case_id,
        subject=subject,
        network=network,
        kind=record.kind,
        kind_label=FINDING_KIND_LABELS.get(record.kind, record.kind),
        severity=record.severity,
        detail=record.detail,
        limitations=list(record.limitations or []),
        confidence=record.confidence,
        detected_at=record.detected_at,
        observed_at=observed_at,
        evidence_id=record.evidence_id,
        metadata=dict(record.metadata_json or {}),
    )


def _match_schema(
    record: InfrastructureMatchRecord,
    onion_subject: str,
    clearnet_subject: str,
    thresholds: CorrelationThresholds,
) -> InfrastructureMatch:
    breakdown_raw = _as_mapping(record.breakdown_json)
    temporal = _as_float(breakdown_raw.get("temporal"))
    breakdown = SimilarityBreakdown(
        temporal=temporal,
        overall=record.overall,
        certificate=_optional_float(breakdown_raw.get("certificate")),
        content=_optional_float(breakdown_raw.get("content")),
        technology=_optional_float(breakdown_raw.get("technology")),
        http=_optional_float(breakdown_raw.get("http")),
        tls=_optional_float(breakdown_raw.get("tls")),
    )
    channels = _channel_scores(breakdown, thresholds)
    metadata = _as_mapping(record.metadata_json)
    return InfrastructureMatch(
        match_id=record.match_id,
        case_id=record.case_id,
        onion_observation_id=record.onion_observation_id,
        clearnet_observation_id=record.clearnet_observation_id,
        onion_subject=onion_subject,
        clearnet_subject=clearnet_subject,
        overall=record.overall,
        breakdown=channels,
        strongest_channel=record.strongest_channel,
        single_channel=len(channels.decisive_channels) <= 1,
        limitations=list(record.limitations or []),
        sources=_string_list(metadata.get("sources")),
        evidence_ids=_string_list(metadata.get("evidence_ids")),
        detected_at=record.detected_at,
        metadata=dict(metadata),
    )


def _observation_schema(
    record: InfrastructureObservationRecord,
    observed_until: datetime | None,
    findings: int,
    matches: int,
) -> InfrastructureObservation:
    return InfrastructureObservation(
        observation_id=record.observation_id,
        subject=record.subject,
        network=record.network,
        source=record.source,
        observed_at=record.observed_at,
        observed_until=observed_until,
        case_id=record.case_id,
        evidence_id=record.evidence_id,
        features=dict(record.features_json or {}),
        finding_count=findings,
        match_count=matches,
    )


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _string_list(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [str(item) for item in value]
    return []


def _as_mapping(value: object) -> Mapping[str, object]:
    """A JSONB column read defensively: a non-object is a reported skip, not a crash."""
    return value if isinstance(value, Mapping) else {}


def _as_float(value: object, default: float = 0.0) -> float:
    """Read a JSONB number without letting a string or null through as a crash."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _observed_until(record: InfrastructureObservationRecord) -> datetime | None:
    stored = _as_mapping(record.features_json)
    payload = _stored_payload(stored)
    window = _stored_range(payload, record)
    end = window.get("end")
    return end if isinstance(end, datetime) else None


def _observation_filters(
    subject: str | None,
    network: str | None,
    since: datetime | None,
    until: datetime | None,
    case_id: UUID | None,
) -> Any:
    """Shared observation predicates, so every route narrows identically."""
    statement = select(InfrastructureObservationRecord)
    if subject:
        statement = statement.where(
            InfrastructureObservationRecord.subject.ilike(_like(subject), escape="\\")
        )
    if network:
        statement = statement.where(InfrastructureObservationRecord.network == network)
    if case_id is not None:
        statement = statement.where(InfrastructureObservationRecord.case_id == case_id)
    if since is not None:
        statement = statement.where(InfrastructureObservationRecord.observed_at >= since)
    if until is not None:
        statement = statement.where(InfrastructureObservationRecord.observed_at <= until)
    return statement


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("/findings", response_model=list[InfrastructureFinding])
def list_findings(
    db: Annotated[Session, Depends(get_db)],
    kind: Annotated[str | None, Query(pattern=f"^({'|'.join(FINDING_KINDS)})$")] = None,
    severity: Annotated[str | None, Query(pattern=f"^({'|'.join(FINDING_SEVERITIES)})$")] = None,
    case_id: UUID | None = None,
    subject: str | None = None,
    network: Annotated[Literal["onion", "clearnet"] | None, Query()] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    #: Excludes unscored findings rather than treating them as 0.
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[InfrastructureFinding]:
    """The misconfiguration list, joined to the observation it was found on.

    ``since``/``until`` bound ``detected_at``, so an analyst can ask what was
    true of a hidden service at a point in the investigation rather than only
    what is true of it now.
    """
    statement = select(InfrastructureFindingRecord, InfrastructureObservationRecord).join(
        InfrastructureObservationRecord,
        InfrastructureFindingRecord.observation_id
        == InfrastructureObservationRecord.observation_id,
    )
    if kind:
        statement = statement.where(InfrastructureFindingRecord.kind == kind)
    if severity:
        statement = statement.where(InfrastructureFindingRecord.severity == severity)
    if case_id is not None:
        statement = statement.where(InfrastructureObservationRecord.case_id == case_id)
    if subject:
        statement = statement.where(
            InfrastructureObservationRecord.subject.ilike(_like(subject), escape="\\")
        )
    if network:
        statement = statement.where(InfrastructureObservationRecord.network == network)
    if since is not None:
        statement = statement.where(InfrastructureFindingRecord.detected_at >= since)
    if until is not None:
        statement = statement.where(InfrastructureFindingRecord.detected_at <= until)
    if min_confidence is not None:
        statement = statement.where(InfrastructureFindingRecord.confidence >= min_confidence)
    statement = statement.order_by(
        InfrastructureFindingRecord.detected_at.desc(),
        InfrastructureFindingRecord.finding_id.desc(),
    ).limit(limit)
    return [
        _finding_schema(finding, observation.subject, observation.network, observation.observed_at)
        for finding, observation in db.execute(statement).all()
    ]


@router.get("/findings/{finding_id}", response_model=InfrastructureFinding)
def get_finding(finding_id: UUID, db: Annotated[Session, Depends(get_db)]) -> InfrastructureFinding:
    record = db.get(InfrastructureFindingRecord, finding_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    observation = db.get(InfrastructureObservationRecord, record.observation_id)
    if observation is None:  # pragma: no cover - enforced by the foreign key
        raise HTTPException(status_code=404, detail="Observation for this finding is missing")
    return _finding_schema(
        record, observation.subject, observation.network, observation.observed_at
    )


@router.get("/matches", response_model=list[InfrastructureMatch])
def list_matches(
    db: Annotated[Session, Depends(get_db)],
    case_id: UUID | None = None,
    #: Substring over either side of the pair, so one address finds both its
    #: hidden service match and its clearnet counterpart.
    subject: str | None = None,
    onion_subject: str | None = None,
    clearnet_subject: str | None = None,
    strongest_channel: str | None = None,
    min_overall: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    rule_input: Annotated[CorrelationThresholdsInput, Depends(_read_rule)] = READ_BACK_RULE,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[InfrastructureMatch]:
    """Onion-to-clearnet correlations, with the breakdown that produced them.

    The decision rule is accepted as a query so the *stored* rows can be
    re-read through the same decisive-channel split that produced them, rather
    than through a hard-coded one that would disagree with a different run.
    """
    rule = rule_input.to_thresholds()
    # The match record names two observations, so the query needs two aliases
    # of the same table: one for each side of the pair.
    clearnet_side = aliased(InfrastructureObservationRecord, name="clearnet_observation")
    statement = (
        select(InfrastructureMatchRecord, InfrastructureObservationRecord, clearnet_side)
        .join(
            InfrastructureObservationRecord,
            InfrastructureMatchRecord.onion_observation_id
            == InfrastructureObservationRecord.observation_id,
        )
        .join(
            clearnet_side,
            InfrastructureMatchRecord.clearnet_observation_id == clearnet_side.observation_id,
        )
    )
    if case_id is not None:
        statement = statement.where(InfrastructureMatchRecord.case_id == case_id)
    if onion_subject:
        statement = statement.where(
            InfrastructureObservationRecord.subject.ilike(_like(onion_subject), escape="\\")
        )
    if clearnet_subject:
        statement = statement.where(
            clearnet_side.subject.ilike(_like(clearnet_subject), escape="\\")
        )
    if subject:
        pattern = _like(subject)
        statement = statement.where(
            InfrastructureObservationRecord.subject.ilike(pattern, escape="\\")
            | clearnet_side.subject.ilike(pattern, escape="\\")
        )
    if strongest_channel:
        statement = statement.where(
            InfrastructureMatchRecord.strongest_channel == strongest_channel
        )
    if min_overall is not None:
        statement = statement.where(InfrastructureMatchRecord.overall >= min_overall)
    if since is not None:
        statement = statement.where(InfrastructureMatchRecord.detected_at >= since)
    if until is not None:
        statement = statement.where(InfrastructureMatchRecord.detected_at <= until)
    statement = statement.order_by(
        InfrastructureMatchRecord.overall.desc(), InfrastructureMatchRecord.match_id.desc()
    ).limit(limit)
    return [
        _match_schema(record, onion_row.subject, clearnet_row.subject, rule)
        for record, onion_row, clearnet_row in db.execute(statement).all()
    ]


@router.get("/observations", response_model=list[InfrastructureObservation])
def list_observations(
    db: Annotated[Session, Depends(get_db)],
    subject: str | None = None,
    network: Annotated[Literal["onion", "clearnet"] | None, Query()] = None,
    case_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[InfrastructureObservation]:
    """Stored observations with the features extracted from each one."""
    statement = _observation_filters(subject, network, since, until, case_id)
    statement = statement.order_by(
        InfrastructureObservationRecord.observed_at.desc(),
        InfrastructureObservationRecord.observation_id.desc(),
    ).limit(limit)
    records = db.scalars(statement).all()
    if not records:
        return []
    counts = _relation_counts(db, records)
    return [
        _observation_schema(
            record,
            _observed_until(record),
            counts.get(("finding", record.observation_id), 0),
            counts.get(("match", record.observation_id), 0),
        )
        for record in records
    ]


@router.get("/observations/{observation_id}", response_model=InfrastructureObservation)
def get_observation(
    observation_id: UUID, db: Annotated[Session, Depends(get_db)]
) -> InfrastructureObservation:
    record = db.get(InfrastructureObservationRecord, observation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    counts = _relation_counts(db, [record])
    return _observation_schema(
        record,
        _observed_until(record),
        counts.get(("finding", record.observation_id), 0),
        counts.get(("match", record.observation_id), 0),
    )


def _relation_counts(
    db: Session, records: Sequence[InfrastructureObservationRecord]
) -> dict[tuple[str, UUID], int]:
    """Findings and matches per observation, in two grouped reads.

    Aggregated rather than looped so the cost does not grow with the page
    size, and so a row's counts come from the same read as its features.
    """
    ids = [record.observation_id for record in records]
    counts: dict[tuple[str, UUID], int] = {}
    findings = db.execute(
        select(InfrastructureFindingRecord.observation_id, func.count())
        .where(InfrastructureFindingRecord.observation_id.in_(ids))
        .group_by(InfrastructureFindingRecord.observation_id)
    ).all()
    for observation_id, total in findings:
        counts[("finding", observation_id)] = int(total)
    # A match is counted under *both* of its endpoints: an observation is
    # equally involved whether it is the hidden service or the clearnet host,
    # and counting it once would make the clearnet side look unexamined.
    for column in (
        InfrastructureMatchRecord.onion_observation_id,
        InfrastructureMatchRecord.clearnet_observation_id,
    ):
        rows = db.execute(
            select(column, func.count()).where(column.in_(ids)).group_by(column)
        ).all()
        for observation_id, total in rows:
            key = ("match", observation_id)
            counts[key] = counts.get(key, 0) + int(total)
    return counts


@router.get("/summary", response_model=InfrastructureSummary)
def infrastructure_summary(
    db: Annotated[Session, Depends(get_db)],
    since: datetime | None = None,
    until: datetime | None = None,
    #: Narrows every count to one investigation. Without it these figures are
    #: platform-wide, which is a different claim from "this case's hidden
    #: services" and cannot be read as one.
    case_id: UUID | None = None,
    rule_input: Annotated[CorrelationThresholdsInput, Depends(_read_rule)] = READ_BACK_RULE,
) -> InfrastructureSummary:
    """Counts across the capability, with the weak-match figure named.

    ``single_channel_matches`` is the headline rather than a footnote: a
    correlation resting on one dimension is a weak finding, and a dashboard
    that reported only the total would let it be read as a strong one.
    """
    rule = rule_input.to_thresholds()

    finding_where = []
    match_where = []
    observation_where = []
    if case_id is not None:
        finding_where.append(InfrastructureFindingRecord.case_id == case_id)
        match_where.append(InfrastructureMatchRecord.case_id == case_id)
        observation_where.append(InfrastructureObservationRecord.case_id == case_id)
    if since is not None:
        finding_where.append(InfrastructureFindingRecord.detected_at >= since)
        match_where.append(InfrastructureMatchRecord.detected_at >= since)
        observation_where.append(InfrastructureObservationRecord.observed_at >= since)
    if until is not None:
        finding_where.append(InfrastructureFindingRecord.detected_at <= until)
        match_where.append(InfrastructureMatchRecord.detected_at <= until)
        observation_where.append(InfrastructureObservationRecord.observed_at <= until)

    by_kind = {kind: 0 for kind in FINDING_KINDS}
    for kind, total in db.execute(
        select(InfrastructureFindingRecord.kind, func.count())
        .where(*finding_where)
        .group_by(InfrastructureFindingRecord.kind)
    ).all():
        by_kind[str(kind)] = int(total)
    by_severity = {name: 0 for name in FINDING_SEVERITIES}
    for severity, total in db.execute(
        select(InfrastructureFindingRecord.severity, func.count())
        .where(*finding_where)
        .group_by(InfrastructureFindingRecord.severity)
    ).all():
        by_severity[str(severity)] = int(total)
    findings_total = sum(by_kind.values())
    unscored = int(
        db.scalar(
            select(func.count())
            .select_from(InfrastructureFindingRecord)
            .where(*finding_where, InfrastructureFindingRecord.confidence.is_(None))
        )
        or 0
    )

    network_rows = db.execute(
        select(
            InfrastructureObservationRecord.network,
            func.count(),
            func.count(func.distinct(InfrastructureObservationRecord.subject)),
        )
        .where(*observation_where)
        .group_by(InfrastructureObservationRecord.network)
    ).all()
    onion_services = 0
    clearnet_hosts = 0
    for network, _rows, distinct_subjects in network_rows:
        if network == "onion":
            onion_services = int(distinct_subjects)
        elif network == "clearnet":
            clearnet_hosts = int(distinct_subjects)
    observations_total = int(
        db.scalar(
            select(func.count())
            .select_from(InfrastructureObservationRecord)
            .where(*observation_where)
        )
        or 0
    )
    window = db.execute(
        select(
            func.min(InfrastructureObservationRecord.observed_at),
            func.max(InfrastructureObservationRecord.observed_at),
        ).where(*observation_where)
    ).one()

    by_strongest: dict[str, int] = {}
    single_channel = 0
    match_rows = db.execute(
        select(
            InfrastructureMatchRecord.overall,
            InfrastructureMatchRecord.breakdown_json,
            InfrastructureMatchRecord.strongest_channel,
        ).where(*match_where)
    ).all()
    for record_overall, breakdown_json, strongest in match_rows:
        name = str(strongest or "unnamed")
        by_strongest[name] = by_strongest.get(name, 0) + 1
        raw = _as_mapping(breakdown_json)
        breakdown = SimilarityBreakdown(
            temporal=_as_float(raw.get("temporal")),
            overall=_as_float(record_overall),
            certificate=_optional_float(raw.get("certificate")),
            content=_optional_float(raw.get("content")),
            technology=_optional_float(raw.get("technology")),
            http=_optional_float(raw.get("http")),
            tls=_optional_float(raw.get("tls")),
        )
        if len(decisive_channels(breakdown, rule)) <= 1:
            single_channel += 1

    return InfrastructureSummary(
        findings_total=findings_total,
        findings_by_kind=by_kind,
        findings_by_severity=by_severity,
        findings_unscored=unscored,
        observations_total=observations_total,
        onion_services=onion_services,
        clearnet_hosts=clearnet_hosts,
        matches_total=len(match_rows),
        single_channel_matches=single_channel,
        matches_by_strongest_channel=by_strongest,
        earliest_observation=window[0],
        latest_observation=window[1],
    )


@router.post("/correlate", response_model=InfrastructureCorrelateResponse)
def run_correlation(
    payload: InfrastructureCorrelateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> InfrastructureCorrelateResponse:
    """Run the library's correlation over stored observations and persist it.

    The only writing route here.  It requires a ``case_id`` and explicit
    ``thresholds``, returns the correlation's own ``limitations`` verbatim,
    and never overwrites an existing match — a re-run reports what is already
    stored next to what it created, because a silently replaced score looks
    identical to a first-time finding.
    """
    case = db.get(CaseRecord, payload.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    thresholds = payload.thresholds.to_thresholds()

    statement = _observation_filters(None, None, payload.since, payload.until, None)
    if payload.networks:
        statement = statement.where(InfrastructureObservationRecord.network.in_(payload.networks))
    if payload.observation_ids:
        statement = statement.where(
            InfrastructureObservationRecord.observation_id.in_(payload.observation_ids)
        )
    records = db.scalars(statement.order_by(InfrastructureObservationRecord.observation_id)).all()

    features: list[InfrastructureFeatures] = []
    network_by_id: dict[UUID, str] = {}
    subject_by_id: dict[UUID, str] = {}
    skipped: list[SkippedObservation] = []
    for record in records:
        try:
            features.append(features_from_record(record))
        except _FeatureReconstructionError as exc:
            skipped.append(
                SkippedObservation(
                    observation_id=record.observation_id,
                    subject=record.subject,
                    reason=str(exc),
                )
            )
            continue
        network_by_id[record.observation_id] = record.network
        subject_by_id[record.observation_id] = record.subject

    if len(features) < 2:
        return InfrastructureCorrelateResponse(
            case_id=payload.case_id,
            thresholds=payload.thresholds,
            observations_considered=len(records),
            pairs_evaluated=0,
            candidates=0,
            same_network_candidates=0,
            created=[],
            existing=[],
            skipped_observations=skipped,
            limitations=_base_limitations(len(features), len(skipped)),
            correlated_at=datetime.now(UTC),
        )

    candidates = correlate_all(features, thresholds=thresholds)
    cross_network: list[tuple[InfrastructureCorrelation, UUID, UUID]] = []
    same_network = 0
    for candidate in candidates:
        left = UUID(candidate.left_observation_id)
        right = UUID(candidate.right_observation_id)
        left_network = network_by_id.get(left)
        right_network = network_by_id.get(right)
        if left_network == right_network:
            same_network += 1
            continue
        onion, clearnet = (left, right) if left_network == "onion" else (right, left)
        cross_network.append((candidate, onion, clearnet))
    if payload.limit is not None:
        cross_network = cross_network[: payload.limit]

    existing_pairs = {
        (record.onion_observation_id, record.clearnet_observation_id): record
        for record in db.scalars(
            select(InfrastructureMatchRecord).where(
                InfrastructureMatchRecord.case_id == payload.case_id
            )
        ).all()
    }

    now = datetime.now(UTC)
    created_records: list[InfrastructureMatchRecord] = []
    reused: list[InfrastructureMatchRecord] = []
    for candidate, onion_id, clearnet_id in cross_network:
        found = existing_pairs.get((onion_id, clearnet_id))
        if found is not None:
            reused.append(found)
            continue
        record = InfrastructureMatchRecord(
            case_id=payload.case_id,
            onion_observation_id=onion_id,
            clearnet_observation_id=clearnet_id,
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
            metadata_json={
                "relationship_type": str(candidate.relationship_type),
                "sources": list(candidate.sources),
                "evidence_ids": list(candidate.evidence_ids),
                "time_range": {
                    "start": candidate.time_range.start.isoformat(),
                    "end": candidate.time_range.end.isoformat(),
                },
                "thresholds": payload.thresholds.model_dump(),
            },
        )
        db.add(record)
        created_records.append(record)
        existing_pairs[(onion_id, clearnet_id)] = record

    db.flush()
    AuditService(db).record(
        "infrastructure.correlated",
        case_id=payload.case_id,
        entity_type="infrastructure",
        entity_id=str(payload.case_id),
        payload={
            "observations_considered": len(records),
            "candidates": len(candidates),
            "created": len(created_records),
            "existing": len(reused),
            "skipped": len(skipped),
            "thresholds": payload.thresholds.model_dump(),
        },
        occurred_at=now,
    )
    db.commit()

    return InfrastructureCorrelateResponse(
        case_id=payload.case_id,
        thresholds=payload.thresholds,
        observations_considered=len(records),
        pairs_evaluated=len(features) * (len(features) - 1) // 2,
        candidates=len(candidates),
        same_network_candidates=same_network,
        created=[
            _match_schema(
                record,
                subject_by_id[record.onion_observation_id],
                subject_by_id[record.clearnet_observation_id],
                thresholds,
            )
            for record in created_records
        ],
        existing=[
            _match_schema(
                record,
                subject_by_id[record.onion_observation_id],
                subject_by_id[record.clearnet_observation_id],
                thresholds,
            )
            for record in reused
        ],
        skipped_observations=skipped,
        limitations=_union_limitations([record.limitations for record in created_records + reused])
        or _base_limitations(len(features), len(skipped)),
        correlated_at=now,
    )


def _union_limitations(groups: Sequence[Sequence[str]]) -> list[str]:
    """Deduplicated limitations, kept verbatim and in first-seen order."""
    seen: list[str] = []
    for group in groups:
        for note in group:
            if note not in seen:
                seen.append(note)
    return seen


def _base_limitations(considered: int, skipped: int) -> list[str]:
    """Run-level caveats, stated even when nothing correlated.

    A run that correlated nothing still has to say what it looked at and what
    it could not read, or an empty result reads as an absence of shared
    infrastructure rather than as an absence of a finding.
    """
    notes = [
        "Passive metadata similarity only: shared infrastructure does not establish "
        "common control, ownership, or operation of the two subjects.",
        "Derived from stored observations with no intrusive origin discovery, scanning, "
        "or probing (Implementation Plan section 14).",
        "A candidate correlation for analyst review — not an attribution conclusion.",
    ]
    if considered < 2:
        notes.append(
            f"Only {considered} observation(s) could be read, which is fewer than the two a "
            "correlation needs; no pair was scored."
        )
    if skipped:
        notes.append(
            f"{skipped} stored observation(s) could not be reconstructed and were not scored; "
            "they are listed under skipped_observations with a reason."
        )
    return notes


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

FINDING_CSV_FIELDS: tuple[str, ...] = (
    "finding_id",
    "case_id",
    "kind",
    "kind_label",
    "severity",
    "subject",
    "network",
    "detail",
    "limitations",
    "confidence",
    "detected_at",
    "observed_at",
    "evidence_id",
)

MATCH_CSV_FIELDS: tuple[str, ...] = (
    "match_id",
    "case_id",
    "onion_subject",
    "clearnet_subject",
    "overall",
    "strongest_channel",
    "decisive_channels",
    "single_channel",
    "certificate",
    "content",
    "technology",
    "http",
    "tls",
    "temporal",
    "limitations",
    "detected_at",
)

OBSERVATION_CSV_FIELDS: tuple[str, ...] = (
    "observation_id",
    "case_id",
    "subject",
    "network",
    "source",
    "observed_at",
    "observed_until",
    "evidence_id",
    "finding_count",
    "match_count",
    "tls_version",
    "ja3",
    "http_server",
    "http_status",
    "certificate_fingerprint_sha256",
    "technologies",
)


@router.get("/export")
def infrastructure_export(
    db: Annotated[Session, Depends(get_db)],
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "csv",
    dataset: Annotated[Literal["findings", "matches", "observations"], Query()] = "findings",
    kind: str | None = None,
    severity: str | None = None,
    case_id: UUID | None = None,
    subject: str | None = None,
    network: Annotated[Literal["onion", "clearnet"] | None, Query()] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    rule_input: Annotated[CorrelationThresholdsInput, Depends(_read_rule)] = READ_BACK_RULE,
) -> Response:
    """The result set as a file, through the same filters the list routes use.

    The CSV carries the ``limitations`` column.  A misconfiguration exported
    without its alternative explanation becomes a spreadsheet row that reads
    as a finding, and it will be read by someone who never sees this screen.
    """
    stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    applied = {
        "dataset": dataset,
        "kind": kind,
        "severity": severity,
        "case_id": str(case_id) if case_id is not None else None,
        "subject": subject,
        "network": network,
        "since": since.isoformat() if since is not None else None,
        "until": until.isoformat() if until is not None else None,
        "min_confidence": min_confidence,
    }

    rows: list[dict[str, object]] = []
    fields: tuple[str, ...] = FINDING_CSV_FIELDS
    if dataset == "findings":
        findings = list_findings(
            db,
            kind=kind,
            severity=severity,
            case_id=case_id,
            subject=subject,
            network=network,
            since=since,
            until=until,
            min_confidence=min_confidence,
            limit=1000,
        )
        payload: dict[str, object] = {"findings": [row.model_dump(mode="json") for row in findings]}
        rows = [
            {
                "finding_id": str(row.finding_id),
                "case_id": str(row.case_id) if row.case_id else "",
                "kind": row.kind,
                "kind_label": row.kind_label,
                "severity": row.severity,
                "subject": row.subject,
                "network": row.network,
                "detail": row.detail,
                "limitations": " | ".join(row.limitations),
                # An unscored detector writes an empty cell, not 0: both read
                # as a score.
                "confidence": "" if row.confidence is None else row.confidence,
                "detected_at": row.detected_at.isoformat(),
                "observed_at": row.observed_at.isoformat(),
                "evidence_id": str(row.evidence_id) if row.evidence_id else "",
            }
            for row in findings
        ]
    elif dataset == "matches":
        matches = list_matches(
            db,
            case_id=case_id,
            subject=subject,
            since=since,
            until=until,
            rule_input=rule_input,
            limit=1000,
        )
        payload = {"matches": [row.model_dump(mode="json") for row in matches]}
        rows = [
            {
                "match_id": str(row.match_id),
                "case_id": str(row.case_id) if row.case_id else "",
                "onion_subject": row.onion_subject,
                "clearnet_subject": row.clearnet_subject,
                "overall": row.overall,
                "strongest_channel": row.strongest_channel or "",
                "decisive_channels": ";".join(row.breakdown.decisive_channels),
                "single_channel": "yes" if row.single_channel else "no",
                "certificate": _csv_number(row.breakdown.certificate),
                "content": _csv_number(row.breakdown.content),
                "technology": _csv_number(row.breakdown.technology),
                "http": _csv_number(row.breakdown.http),
                "tls": _csv_number(row.breakdown.tls),
                "temporal": row.breakdown.temporal,
                "limitations": " | ".join(row.limitations),
                "detected_at": row.detected_at.isoformat(),
            }
            for row in matches
        ]
    else:
        observations = list_observations(
            db,
            subject=subject,
            network=network,
            case_id=case_id,
            since=since,
            until=until,
            limit=1000,
        )
        payload = {"observations": [row.model_dump(mode="json") for row in observations]}
        rows = [_observation_csv_row(row) for row in observations]
        fields = OBSERVATION_CSV_FIELDS

    if format == "json":
        body = {"generated_at": stamp, "filters": applied, "returned": len(rows), **payload}
        return Response(json.dumps(body, indent=2, sort_keys=True), media_type="application/json")

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return Response(buffer.getvalue(), media_type="text/csv")


def _csv_number(value: float | None) -> str:
    """An unavailable channel writes an empty cell, never a 0."""
    return "" if value is None else str(value)


def _csv_text(value: object) -> str:
    """A missing feature field writes an empty cell, never a placeholder value."""
    return "" if value is None else str(value)


def _observation_csv_row(row: InfrastructureObservation) -> dict[str, object]:
    features = _stored_payload(row.features)
    tls = _as_mapping(features.get("tls"))
    http = _as_mapping(features.get("http"))
    certificate = _as_mapping(features.get("certificate"))
    technologies = features.get("technologies")
    return {
        "observation_id": str(row.observation_id),
        "case_id": str(row.case_id) if row.case_id else "",
        "subject": row.subject,
        "network": row.network,
        "source": row.source,
        "observed_at": row.observed_at.isoformat(),
        "observed_until": row.observed_until.isoformat() if row.observed_until else "",
        "evidence_id": str(row.evidence_id) if row.evidence_id else "",
        "finding_count": row.finding_count,
        "match_count": row.match_count,
        "tls_version": _csv_text(tls.get("version")),
        "ja3": _csv_text(tls.get("ja3")),
        "http_server": _csv_text(http.get("server")),
        "http_status": _csv_text(http.get("status_code")),
        "certificate_fingerprint_sha256": _csv_text(certificate.get("fingerprint_sha256")),
        "technologies": ";".join(str(item) for item in technologies if isinstance(item, str))
        if isinstance(technologies, Sequence) and not isinstance(technologies, str | bytes)
        else "",
    }
