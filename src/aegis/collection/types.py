"""Collector framework types (Implementation Plan Phase 05).

Collectors are deliberately decoupled from storage: they produce
:class:`RawArtifact` and :class:`NormalizedArtifact` value objects; an
ingestion bridge (``aegis.collection.ingest``) is the only component
allowed to reach toward the evidence ledger.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobType(StrEnum):
    """Collection job kinds (spec §11)."""

    DISCOVER = "DISCOVER"
    COLLECT = "COLLECT"
    DIFF = "DIFF"
    REPROCESS = "REPROCESS"
    REASSESS = "REASSESS"
    REVALIDATE = "REVALIDATE"


@dataclass(frozen=True)
class CollectionScope:
    """What a collector is allowed/asked to look at for one job."""

    job_type: JobType = JobType.DISCOVER
    case_id: str | None = None
    seed_terms: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    """A discoverable item the collector has not fetched yet."""

    candidate_id: str
    source_ref: str
    platform: str
    observed_hint: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawArtifact:
    """Bytes fetched from a source plus the provenance needed to ledger them."""

    candidate: Candidate
    body: bytes
    media_type: str
    collected_at: datetime
    collector_name: str
    collector_version: str
    source_url: str
    sha256: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedArtifact:
    """One normalized observation derived from a raw artifact.

    ``independence_group`` is mandatory: it is what later stages use to
    discount copied (non-independent) corroboration.
    """

    raw: RawArtifact
    text: str
    normalized_text: str
    observed_at: datetime | None
    author_hint: str | None
    platform: str
    independence_group: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class CollectorError(RuntimeError):
    """Base class for collector failures (retry classification below)."""


class CollectorTimeout(CollectorError):
    """Collector exceeded its deadline; safe to retry with backoff."""


class CollectorRejected(CollectorError):
    """Collector refused the scope (out of policy); not retryable."""
