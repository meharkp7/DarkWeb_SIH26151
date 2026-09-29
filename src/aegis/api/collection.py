"""Autonomous collection API — the source register, the run log, and a run.

The problem statement's last clause asks for an analytical front end that
"works in an autonomous mode, drawing on available sources of good quality and
reliability". The engine for the second half of that sentence already existed and
was unreachable: :mod:`aegis.collection` ships a tested
:class:`~aegis.collection.orchestrator.CollectorOrchestrator` with per-collector
timeouts, retries and a sliding-window :class:`~aegis.collection.RateLimiter`,
plus the :class:`~aegis.collection.CollectionScope` it executes and the
:class:`~aegis.collection.CollectionReport` it returns. Nothing read
``collection_jobs`` and nothing read the source register.

This module is the adapter between that engine and the console, and it holds to
four rules:

* **The engine is used, not reimplemented.** Every run goes through a real
  :class:`CollectorOrchestrator` over real :class:`Collector` instances, and
  every response is built from the :class:`CollectionReport` it returns. There
  is no private scoring, counting or retry loop here — this module only binds
  the register to the collectors and writes down what happened.
* **A run is asynchronous because the collectors are.** The handler awaits the
  orchestrator; it never blocks the API thread on a collection run. The
  in-process synthetic corpus has no I/O to await, so the adapter yields
  explicitly between candidates rather than monopolising the event loop the way
  a real collector's awaits would not.
* **A synthetic run says so, in the response and on screen.** No network
  collector is registered in this build, so a run against the registered
  sources is a rehearsal of the pipeline over an in-process corpus. The mode is
  reported, and a run that produced nothing says *that* rather than returning
  an empty report that reads as success.
* **Reliability is a property of the source, never of a record.**
  ``sources.reliability`` is a weight recorded against the outlet; it is
  surfaced with that wording attached, and the independence group beside it is
  what stops three feeds copying one press release from reading as three
  sources.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.api.security import RequestRateLimiter
from aegis.collection import (
    Candidate,
    CollectionReport,
    CollectionScope,
    Collector,
    CollectorOrchestrator,
    CollectorRejected,
    JobType,
    NormalizedArtifact,
    SyntheticCorpus,
    build_default_corpus,
)
from aegis.collection.orchestrator import CollectorOutcome
from aegis.collection.synthetic import (
    SyntheticChannelCollector,
    SyntheticForumCollector,
    SyntheticMarketplaceCollector,
    SyntheticSurfaceCollector,
    _SyntheticCollector,
)
from aegis.collection.types import RawArtifact
from aegis.db.audit import AuditService
from aegis.db.models import (
    CaseRecord,
    CollectionJobRecord,
    EvidenceRecord,
    SourceRecord,
)

router = APIRouter(prefix="/api/v1/collection", tags=["collection"])

#: Version of the ``metadata_json`` document this router reads on a job row.
#: The seeder writes the same shape, so a seeded run and a live one are
#: describable by one set of readers.
COLLECTION_SCHEMA_VERSION: Final[str] = "aegis-collection/1"

#: A source not scanned within this many days is *stale*. "Stale" is not
#: "broken" — it is the back of the backlog, and the distinction matters
#: because a source nobody has looked at is otherwise indistinguishable from
#: one with nothing to report.
STALE_AFTER_DAYS: Final[int] = 7

#: The window the status headline counts jobs over.
RECENT_WINDOW_HOURS: Final[int] = 24

#: ``sources`` and ``collection_jobs.status`` values this router writes or
#: filters on. ``created`` is the column default and is listed because a row
#: left at ``created`` is a job that was queued and never started, which is a
#: different fact from one that failed.
JOB_STATUSES: Final[tuple[str, ...]] = (
    "created",
    "running",
    "completed",
    "partial",
    "failed",
)

#: The scheme every in-process corpus collector stamps onto the URLs it
#: produces. A run is called synthetic on the artefacts as well as on the
#: registry, so a deployment that registered a network collector and left the
#: synthetic ones in the set could not report a fixture run as live.
SYNTHETIC_URL_SCHEME: Final[str] = "synthetic://"

#: Network collectors a deployment would register here.
#:
#: Empty in this build, and that emptiness is the whole honesty story of this
#: router: every collector the platform ships reads an in-process deterministic
#: corpus (:mod:`aegis.collection.synthetic`), so every run is a rehearsal of
#: the pipeline rather than live collection, and every response says so. Adding
#: a network collector to this tuple is the single change that would make
#: ``collection_mode`` report ``live``.
NETWORK_COLLECTORS: Final[tuple[Collector, ...]] = ()

#: Fetches per minute each bound collector may make through the orchestrator's
#: own sliding-window limiter. The synthetic collectors declare ``0`` (no
#: external calls), which *disables* their limiter; binding a register row sets
#: this so a run over several sources is paced like a real one instead of
#: running flat out against the corpus.
DEFAULT_RATE_LIMIT_PER_MINUTE: Final[int] = 60

#: Runs one client may start per minute. The orchestrator's limiter bounds
#: fetches *inside* a run; nothing bounds how many runs a client may start, and
#: an unbounded version of this endpoint is a denial-of-service on the API
#: thread even with every fetch awaited.
MAX_RUNS_PER_MINUTE: Final[int] = 20

#: The reliability wording that travels with every figure drawn from
#: ``sources.reliability``.
RELIABILITY_BASIS: Final[str] = (
    "Reliability is recorded against the source when it was registered. It is a weight "
    "on that outlet, not a measurement of any individual record it produced, and it does "
    "not change from one collection to the next."
)

#: Reliability bands, highest floor first, and the floor each one starts at.
#:
#: Declared server-side and returned as the ``band`` name rather than as a
#: cut-off the browser re-applies: a console that banded the register with its
#: own thresholds would report a different corpus from the one the API counted,
#: and the two would disagree on the same page without either being wrong about
#: its own arithmetic.
RELIABILITY_BANDS: Final[tuple[tuple[str, float], ...]] = (
    ("high", 0.7),
    ("medium", 0.4),
    ("low", 0.0),
)

#: Which registered source type each shipped collector can serve.
#:
#: The mapping is deliberately narrow. A source with no entry is not silently
#: scanned by a near-enough collector: it is refused with a reason, the
#: orchestrator records the refusal as that collector's error, and the job row
#: is written as ``failed``. A register that quietly served a threat feed from a
#: forum adapter would be a register nobody could trust.
#: Keyed on the *synthetic* collector base rather than ``Collector``,
#: because every entry takes a corpus in its constructor. Typed as the
#: abstract base, ``cls(corpus)`` reads as a call-arity error — which is
#: exactly the signal that would have caught a mismatched constructor
#: signature at the point it was written.
PLATFORM_FOR_SOURCE_TYPE: Final[dict[str, type[_SyntheticCollector]]] = {
    "forum": SyntheticForumCollector,
    "marketplace": SyntheticMarketplaceCollector,
    # A paste site is a public-web surface; the surface adapter reads both.
    "public_web": SyntheticSurfaceCollector,
    "channel": SyntheticChannelCollector,
}

_INDEPENDENCE_KEY: Final[str] = "independence_group"
_SYNTHETIC_KEY: Final[str] = "synthetic"

_run_limiter = RequestRateLimiter(limit=MAX_RUNS_PER_MINUTE, window_seconds=60.0)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SourceQuality(BaseModel):
    """One registered source, with the basis on which it can be trusted.

    The counts are the quality evidence: a source with a high reliability and
    no records is a claim, and a source with records and a low reliability is
    the reverse. Neither is visible from ``reliability`` alone.
    """

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    source_type: str
    name: str
    reliability: float
    independence_group: str
    #: How many registered sources share this independence group. Above one,
    #: the group is a single voice wearing several hats.
    independence_group_size: int
    record_count: int
    job_count: int
    last_scanned_at: datetime | None
    last_status: str | None
    #: ``healthy``, ``stale`` or ``never``. A source that has never been
    #: scanned is not a clean source, so it is its own label.
    freshness: str
    synthetic: bool
    #: Why this source's weight is what it is, phrased for the row. Present on
    #: every row so the caveat cannot be left off a dense table.
    reliability_basis: str
    independence_note: str | None


class SourceReliabilityBand(BaseModel):
    """One reliability band and what it has actually produced.

    A band name on its own is a label on a weight. ``records`` is what a reader
    actually wants next to it — a "high" band holding every record in the
    corpus and a "high" band holding none are opposite facts about the same
    label, and only one of them should be able to look reliable.
    """

    model_config = ConfigDict(frozen=True)

    #: ``high``, ``medium`` or ``low``. Named by the API, never re-derived.
    band: str
    #: The reliability at and above which a source falls in this band, so the
    #: cut-off travels with the number rather than living in a reader's head.
    min_reliability: float
    #: Registered sources in the band.
    sources: int
    #: Those of them that have produced a record or a completed/partial run.
    contributing_sources: int
    #: Evidence rows stored against the band's sources, all-time.
    records: int


class CollectionJob(BaseModel):
    """One run of one source's collector, as recorded in ``collection_jobs``."""

    model_config = ConfigDict(frozen=True)

    job_id: UUID
    source_id: UUID
    source_name: str
    source_type: str
    collector_name: str
    collector_version: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    #: What the collector's ``discover`` returned for this run.
    candidates: int
    #: What survived ``collect`` and ``normalize``. This is the run's result.
    records: int
    errors: int
    #: The first few error strings, verbatim from the orchestrator's outcome.
    error_samples: list[str]
    independence_group: str
    reliability: float | None
    synthetic: bool


class CollectionJobDetail(CollectionJob):
    """One job with everything the row stored."""

    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionStatus(BaseModel):
    """The headline an operator opens this page for.

    ``dominant_independence_group_size`` is the figure worth reading first. A
    register of forty sources that is really six outlets is not forty sources,
    and a total that cannot see that difference is the number a bad
    corroboration claim is built on.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    sources_total: int
    sources_healthy: int
    sources_stale: int
    sources_never_scanned: int
    stale_after_days: int
    jobs_last_24h: dict[str, int]
    jobs_last_24h_total: int
    records_last_24h: int
    #: Sources that have actually produced a record — a job with ``records > 0``
    #: or at least one evidence row. Excluded here: sources that exist, are
    #: registered and have never yielded anything.
    contributing_sources: int
    #: Mean reliability over the contributing sources only, or ``None`` when
    #: none has contributed. Null rather than 0.0, because a mean over an
    #: empty set is not a low score.
    mean_contributing_reliability: float | None
    #: Mean reliability over *every* registered source, contributors included.
    #: Returned beside the contributing mean because the difference between the
    #: two is the point: a register whose average collapses once the sources
    #: that never produced anything are included is not a register whose
    #: evidence is weak, it is a register with a coverage gap.
    mean_registered_reliability: float | None
    independence_groups: int
    dominant_independence_group: str | None
    dominant_independence_group_size: int
    #: The same register, grouped by reliability band. ``records`` is the count
    #: of evidence rows the band's sources have actually produced, which is the
    #: only version of a reliability band that says how much weight is behind
    #: it — a band of high-reliability sources that have never run is a claim,
    #: not a foundation.
    reliability_bands: list[SourceReliabilityBand]
    reliability_basis: str
    limitations: list[str]


class CollectorOutcomeRow(BaseModel):
    """One :class:`CollectorOutcome`, attributed to the source that produced it.

    The five leading fields are the orchestrator's own dataclass, read straight
    off the report. The rest is the attribution the dataclass does not carry:
    which registered source the collector was bound to, and where the run was
    written.
    """

    model_config = ConfigDict(frozen=True)

    collector_name: str
    collector_version: str
    candidates: int
    observations: int
    errors: list[str]
    source_id: UUID
    source_name: str
    source_type: str
    independence_group: str
    reliability: float
    job_id: UUID
    job_status: str


class CollectionRunRequest(BaseModel):
    """Ask the orchestrator to collect within a scope.

    ``extra="forbid"`` so a body carrying ``candidates``, ``records`` or
    ``status`` is refused rather than ignored: those are the run's output, and
    a caller who supplies them is asking the platform to store their number in
    the column it reads as its own.
    """

    model_config = ConfigDict(extra="forbid")

    job_type: str = "DISCOVER"
    case_id: UUID | None = None
    seed_terms: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    since: datetime | None = None
    until: datetime | None = None
    #: Candidates per collector. Bounded because each candidate is a fetch
    #: inside the run and an unbounded limit is an unbounded request.
    limit: int = Field(default=25, ge=1, le=200)
    max_attempts: int = Field(default=2, ge=1, le=5)
    rate_limit_per_minute: int = Field(default=DEFAULT_RATE_LIMIT_PER_MINUTE, ge=1, le=600)


class CollectionRunResponse(BaseModel):
    """The :class:`CollectionReport` the orchestrator returned, plus where it went."""

    model_config = ConfigDict(frozen=True)

    status: str
    scope: dict[str, Any]
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    total_candidates: int
    total_observations: int
    error_count: int
    outcomes: list[CollectorOutcomeRow]
    job_ids: list[UUID]
    audit_seq: int
    #: ``synthetic`` or ``live``. Never inferred from the fact that the run
    #: succeeded.
    collection_mode: str
    synthetic: bool
    #: The sentence a reader needs before the counts mean anything to them.
    mode_note: str
    #: Collector output is returned, not written to the evidence ledger.
    #: Ingestion is :mod:`aegis.collection.ingest` and is a separate, explicit
    #: step; a run that had ingested would say so here.
    ingested: bool
    notes: list[str]
    limitations: list[str]


class CollectionExport(BaseModel):
    """The export payload: the status headline plus both registers.

    The status travels with the data because a source register exported without
    the dominant independence group invites the reader to treat the row count as
    the number of independent sources.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    dataset: str
    filters: dict[str, Any]
    status: CollectionStatus
    sources: list[SourceQuality]
    jobs: list[CollectionJob]


# ---------------------------------------------------------------------------
# Source register
# ---------------------------------------------------------------------------


def _independence_group(record: SourceRecord) -> str:
    """The group a source's copies are discounted under.

    Falls back to the source's own id rather than a shared placeholder: two
    sources with no recorded group are two groups of one, and merging them into
    a common "unknown" bucket would invent a dependence between outlets that
    may have nothing to do with each other.
    """
    metadata = record.metadata_json or {}
    group = metadata.get(_INDEPENDENCE_KEY)
    return str(group) if isinstance(group, str) and group != "" else f"ungrouped:{record.source_id}"


def _is_synthetic(record: SourceRecord) -> bool:
    metadata = record.metadata_json or {}
    return metadata.get(_SYNTHETIC_KEY) is True


def _source_records(db: Session) -> list[SourceRecord]:
    return list(db.scalars(select(SourceRecord).order_by(SourceRecord.name)).all())


def _source_register(db: Session, *, now: datetime) -> list[SourceQuality]:
    """The register, with the quality evidence beside each weight.

    Counts come from grouped queries rather than a scan per source: the record
    column grows without bound while the register does not, and a register that
    degrades with the size of its own evidence table is a register nobody waits
    for.
    """
    records = _source_records(db)
    if not records:
        return []

    evidence_counts = {
        source_id: int(count)
        for source_id, count in db.execute(
            select(EvidenceRecord.source_id, func.count(EvidenceRecord.evidence_id)).group_by(
                EvidenceRecord.source_id
            )
        ).all()
    }
    job_counts = {
        source_id: int(count)
        for source_id, count in db.execute(
            select(CollectionJobRecord.source_id, func.count(CollectionJobRecord.job_id)).group_by(
                CollectionJobRecord.source_id
            )
        ).all()
    }
    last_scans = {
        source_id: last_scan
        for source_id, last_scan in db.execute(
            select(
                CollectionJobRecord.source_id, func.max(CollectionJobRecord.started_at)
            ).group_by(CollectionJobRecord.source_id)
        ).all()
    }
    # Newest job per source, resolved in Python over an already-sorted scan: a
    # window function would be tidier and this table is one row per run.
    last_status: dict[UUID, str] = {}
    for source_id, job_status in db.execute(
        select(CollectionJobRecord.source_id, CollectionJobRecord.status).order_by(
            CollectionJobRecord.started_at.desc().nullslast(), CollectionJobRecord.job_id.desc()
        )
    ).all():
        last_status.setdefault(source_id, job_status)

    group_sizes: dict[str, int] = {}
    for record in records:
        group = _independence_group(record)
        group_sizes[group] = group_sizes.get(group, 0) + 1

    cutoff = now - timedelta(days=STALE_AFTER_DAYS)
    rows: list[SourceQuality] = []
    for record in records:
        group = _independence_group(record)
        last_scan = last_scans.get(record.source_id)
        if last_scan is None:
            freshness = "never"
        elif last_scan.tzinfo is None:
            # A naive timestamp cannot be compared against an aware `now`
            # without guessing the host's zone; treat it as stale rather than
            # letting the comparison raise in the middle of a register read.
            freshness = "stale"
        else:
            freshness = "healthy" if last_scan >= cutoff else "stale"
        size = group_sizes[group]
        rows.append(
            SourceQuality(
                source_id=record.source_id,
                source_type=record.source_type,
                name=record.name,
                reliability=record.reliability,
                independence_group=group,
                independence_group_size=size,
                record_count=evidence_counts.get(record.source_id, 0),
                job_count=job_counts.get(record.source_id, 0),
                last_scanned_at=last_scan,
                last_status=last_status.get(record.source_id),
                freshness=freshness,
                synthetic=_is_synthetic(record),
                reliability_basis=RELIABILITY_BASIS,
                independence_note=(
                    None
                    if size <= 1
                    else (
                        f"{size} registered sources share this independence group. Treat them "
                        "as one voice, not as independent corroboration."
                    )
                ),
            )
        )
    return rows


@router.get("/sources", response_model=list[SourceQuality])
def list_sources(db: Annotated[Session, Depends(get_db)]) -> list[SourceQuality]:
    """The source register, with what each weight is a weight on.

    Not a bare list of names: the reliability is a property of the source, the
    record count is the evidence it has actually produced, and the independence
    group is what makes three feeds copying one outlet legible as one outlet.
    """
    return _source_register(db, now=datetime.now(UTC))


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------


def _meta_int(metadata: dict[str, Any], key: str) -> int:
    """Read a count out of a job's metadata, treating anything unreadable as 0.

    A malformed count is reported as nothing counted rather than raising, and
    the row still renders: a run log that refuses to display because one row's
    metadata is off is a run log that hides the rest of the history.
    """
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _meta_strs(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _job_schema(record: CollectionJobRecord, source: SourceRecord | None) -> CollectionJob:
    metadata = record.metadata_json or {}
    duration: float | None = None
    if record.started_at is not None and record.finished_at is not None:
        started = (
            record.started_at
            if record.started_at.tzinfo is not None
            else record.started_at.replace(tzinfo=UTC)
        )
        finished = (
            record.finished_at
            if record.finished_at.tzinfo is not None
            else record.finished_at.replace(tzinfo=UTC)
        )
        duration = (finished - started).total_seconds()
    return CollectionJob(
        job_id=record.job_id,
        source_id=record.source_id,
        source_name=source.name if source is not None else "unknown source",
        source_type=source.source_type if source is not None else "unknown",
        collector_name=record.collector_name,
        collector_version=record.collector_version,
        status=record.status,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_seconds=duration,
        candidates=_meta_int(metadata, "candidates"),
        records=_meta_int(metadata, "records"),
        errors=_meta_int(metadata, "errors"),
        error_samples=_meta_strs(metadata, "error_samples"),
        independence_group=(
            _independence_group(source)
            if source is not None
            else str(metadata.get("independence_group", "unknown"))
        ),
        reliability=source.reliability if source is not None else None,
        synthetic=metadata.get(_SYNTHETIC_KEY) is True,
    )


def _sources_by_id(db: Session, ids: Sequence[UUID]) -> dict[UUID, SourceRecord]:
    if not ids:
        return {}
    return {
        record.source_id: record
        for record in db.scalars(select(SourceRecord).where(SourceRecord.source_id.in_(ids))).all()
    }


class _JobFilters:
    """The job filter set, resolved once and reused by the list and the export."""

    def __init__(
        self,
        status_filter: str | None,
        source_id: UUID | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> None:
        self.status = status_filter
        self.source_id = source_id
        self.since = since
        self.until = until
        self.limit = limit
        self.offset = offset

    def described(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_id": str(self.source_id) if self.source_id else None,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "limit": self.limit,
            "offset": self.offset,
        }

    def query(self, db: Session) -> list[CollectionJobRecord]:
        statement = select(CollectionJobRecord)
        if self.status is not None:
            statement = statement.where(CollectionJobRecord.status == self.status)
        if self.source_id is not None:
            statement = statement.where(CollectionJobRecord.source_id == self.source_id)
        if self.since is not None:
            statement = statement.where(CollectionJobRecord.started_at >= self.since)
        if self.until is not None:
            statement = statement.where(CollectionJobRecord.started_at <= self.until)
        return list(
            db.scalars(
                statement.order_by(
                    CollectionJobRecord.started_at.desc().nullslast(),
                    CollectionJobRecord.job_id.desc(),
                )
                .limit(self.limit)
                .offset(self.offset)
            ).all()
        )

    def schema_many(self, db: Session) -> list[CollectionJob]:
        records = self.query(db)
        sources = _sources_by_id(db, [record.source_id for record in records])
        return [_job_schema(record, sources.get(record.source_id)) for record in records]


def _job_filters(
    # `status` is the column name; the parameter is `status_filter` so it does
    # not shadow the imported `fastapi.status` module the handlers need.
    status_filter: Annotated[
        str | None, Query(alias="status", pattern="^(created|running|completed|partial|failed)$")
    ] = None,
    source_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> _JobFilters:
    return _JobFilters(status_filter, source_id, since, until, limit, offset)


@router.get("/jobs", response_model=list[CollectionJob])
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    filters: Annotated[_JobFilters, Depends(_job_filters)],
) -> list[CollectionJob]:
    """The run log, newest first, with every status shown.

    A failed or partial job is a row like any other and is filtered out only
    when an analyst asks for it. A run log that shows only successes is a
    marketing page, and the failures are the part that says whether the
    autonomous mode is actually working.
    """
    return filters.schema_many(db)


@router.get("/jobs/{job_id}", response_model=CollectionJobDetail)
def job_detail(job_id: UUID, db: Annotated[Session, Depends(get_db)]) -> CollectionJobDetail:
    """One job, with the metadata the row stored."""
    record = db.get(CollectionJobRecord, job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection job not found"
        )
    source = db.get(SourceRecord, record.source_id)
    base = _job_schema(record, source)
    return CollectionJobDetail(**base.model_dump(), metadata=dict(record.metadata_json or {}))


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _status_limitations(
    healthy: int, total: int, dominant: str | None, dominant_size: int
) -> list[str]:
    """What this headline does not establish, in the terms of the figures above."""
    notes = [
        "Stale counts sources whose last run started more than "
        f"{STALE_AFTER_DAYS} days ago; never-scanned counts the sources that have not run at "
        "all. A source nobody has looked at is the back of the backlog, not a clean source.",
        "A source that appears in the register has been registered. Reliability is the weight "
        "recorded against it at that point, not a measurement this run made.",
    ]
    if total > 0 and healthy == 0:
        notes.append(
            "No source in this register is currently healthy. Every count below describes "
            "what the last recorded runs produced, not what the sources look like now."
        )
    if dominant is not None and dominant_size > 1:
        notes.append(
            f"{dominant_size} of the {total} registered sources share independence group "
            f"{dominant!r}. Corroboration drawn across them is one outlet restated, not "
            f"{dominant_size} confirmations."
        )
    return notes


def _collection_status(db: Session, *, now: datetime) -> CollectionStatus:
    sources = _source_register(db, now=now)
    window_start = now - timedelta(hours=RECENT_WINDOW_HOURS)

    jobs_last_24h: dict[str, int] = {name: 0 for name in JOB_STATUSES}
    records_last_24h = 0
    for record in db.scalars(
        select(CollectionJobRecord).where(
            CollectionJobRecord.started_at.isnot(None),
            CollectionJobRecord.started_at >= window_start,
        )
    ).all():
        if record.status not in jobs_last_24h:
            # A status the column accepts but this router does not know would
            # otherwise vanish from the headline. Counted, and named below.
            jobs_last_24h[record.status] = 0
        jobs_last_24h[record.status] += 1
        records_last_24h += _meta_int(record.metadata_json or {}, "records")

    contributing: list[SourceQuality] = []
    for source in sources:
        produced_records = source.record_count > 0
        produced_run = db.scalar(
            select(func.count(CollectionJobRecord.job_id)).where(
                CollectionJobRecord.source_id == source.source_id,
                CollectionJobRecord.status.in_(("completed", "partial")),
            )
        )
        if produced_records or (produced_run or 0) > 0:
            contributing.append(source)

    group_sizes: dict[str, int] = {}
    for source in sources:
        group_sizes[source.independence_group] = group_sizes.get(source.independence_group, 0) + 1
    dominant_group, dominant_size = "", 0
    for group, size in sorted(group_sizes.items(), key=lambda item: (-item[1], item[0])):
        if size > dominant_size:
            dominant_group, dominant_size = group, size

    healthy = sum(1 for source in sources if source.freshness == "healthy")
    never = sum(1 for source in sources if source.freshness == "never")

    contributing_ids = {source.source_id for source in contributing}
    bands: list[SourceReliabilityBand] = []
    # First match wins: the bands are declared as floors, so a 0.85 source
    # clears all three and must be counted once. Assigning it to each band it
    # clears would make the band's source counts sum past the register total
    # and quietly invent sources nobody registered.
    assigned: set[UUID] = set()
    for band, floor in RELIABILITY_BANDS:
        members = [
            source
            for source in sources
            if source.source_id not in assigned and source.reliability >= floor
        ]
        assigned.update(source.source_id for source in members)
        bands.append(
            SourceReliabilityBand(
                band=band,
                min_reliability=floor,
                sources=len(members),
                contributing_sources=sum(
                    1 for source in members if source.source_id in contributing_ids
                ),
                records=sum(source.record_count for source in members),
            )
        )

    return CollectionStatus(
        generated_at=now,
        sources_total=len(sources),
        sources_healthy=healthy,
        sources_stale=len(sources) - healthy - never,
        sources_never_scanned=never,
        stale_after_days=STALE_AFTER_DAYS,
        jobs_last_24h=jobs_last_24h,
        jobs_last_24h_total=sum(jobs_last_24h.values()),
        records_last_24h=records_last_24h,
        contributing_sources=len(contributing),
        mean_contributing_reliability=(
            round(sum(source.reliability for source in contributing) / len(contributing), 4)
            if contributing
            else None
        ),
        mean_registered_reliability=(
            round(sum(source.reliability for source in sources) / len(sources), 4)
            if sources
            else None
        ),
        independence_groups=len(group_sizes),
        dominant_independence_group=dominant_group or None,
        dominant_independence_group_size=dominant_size,
        reliability_bands=bands,
        reliability_basis=RELIABILITY_BASIS,
        limitations=[
            *_status_limitations(healthy, len(sources), dominant_group or None, dominant_size),
            "Band record counts are all-time totals for the sources in the band, not "
            "counts from a window, and a band with no records has produced nothing to "
            "weigh. Band edges are "
            + ", ".join(f"{name} at {floor:g} and above" for name, floor in RELIABILITY_BANDS)
            + ".",
        ],
    )


@router.get("/status", response_model=CollectionStatus)
def collection_status(db: Annotated[Session, Depends(get_db)]) -> CollectionStatus:
    """The headline: register health, the last day's runs, and the honesty figure.

    The number worth reading first is
    ``dominant_independence_group_size``. A register of forty sources that is
    really six outlets is not forty sources, and no other figure on this page
    can tell the difference.
    """
    return _collection_status(db, now=datetime.now(UTC))


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Binding:
    """A registered source and the collector it is bound to for one run."""

    source: SourceRecord
    collector: SourceScanCollector


class SourceScanCollector(Collector):
    """One registered source, bound to a platform collector.

    The register decides *whether* a source can be scanned; the platform's own
    collector does the discovering, fetching and normalizing. Nothing here
    re-implements any part of that contract — all three phases are delegated —
    and a source with no bound collector refuses the scope with a reason, which
    the orchestrator records as that collector's error rather than letting the
    refusal vanish.

    Two things are set here that the delegate does not set for itself:

    * ``rate_limit_per_minute``, because the synthetic collectors declare ``0``
      — which *disables* the orchestrator's sliding-window limiter — and a run
      over a register should be paced like one over a network rather than run
      flat out against an in-memory corpus.
    * an explicit ``await asyncio.sleep(0)`` between candidates. A real
      collector awaits socket reads there; the synthetic corpus has nothing to
      await, so without this a run would execute without ever handing the event
      loop back and would block every other request on the API thread.
    """

    def __init__(
        self,
        *,
        source_type: str,
        independence_group: str,
        delegate: Collector | None,
        unbound_reason: str,
        rate_limit_per_minute: int,
    ) -> None:
        self.source_type = source_type
        self.name = f"{source_type}_scan"
        self.version = delegate.version if delegate is not None else "0.0.0"
        self.independence_group = independence_group
        self.rate_limit_per_minute = rate_limit_per_minute
        self._delegate = delegate
        self._unbound_reason = unbound_reason

    @property
    def delegate_name(self) -> str:
        """The platform collector underneath, for the row's metadata."""
        return self._delegate.name if self._delegate is not None else "none"

    def _bound(self) -> Collector:
        if self._delegate is None:
            raise CollectorRejected(self._unbound_reason)
        return self._delegate

    async def discover(self, scope: CollectionScope) -> Sequence[Candidate]:
        return await self._bound().discover(scope)

    async def collect(self, candidate: Candidate) -> RawArtifact:
        delegate = self._bound()
        await asyncio.sleep(0)
        return await delegate.collect(candidate)

    async def normalize(self, artifact: Any) -> Sequence[NormalizedArtifact]:
        delegate = self._bound()
        return await delegate.normalize(artifact)


# The declared signatures above are narrowed here so the adapter keeps the
# contract's types (``RawArtifact`` in, ``NormalizedArtifact`` out) rather than
# the `Any` an untyped delegation would infer.
async def _collect_artifact(self: SourceScanCollector, candidate: Candidate) -> RawArtifact:
    delegate = self._bound()
    await asyncio.sleep(0)
    return await delegate.collect(candidate)


def _bind_sources(sources: Sequence[SourceRecord], *, rate_limit_per_minute: int) -> list[_Binding]:
    """One bound collector per registered source, in register order.

    The corpus is built once and shared: each shipped collector builds its own
    copy otherwise, and six copies of a thousand-post fixture is memory the
    first version of this would have spent for nothing.
    """
    corpus: SyntheticCorpus = build_default_corpus()
    delegates = {kind: cls(corpus) for kind, cls in PLATFORM_FOR_SOURCE_TYPE.items()}
    bindings: list[_Binding] = []
    for source in sources:
        delegate = delegates.get(source.source_type)
        if delegate is None:
            reason = (
                f"no collector is registered for source type {source.source_type!r}. This "
                f"deployment has the in-process synthetic collectors "
                f"({', '.join(sorted(PLATFORM_FOR_SOURCE_TYPE))}) and no network collector."
            )
        else:
            reason = ""
        collector = SourceScanCollector(
            source_type=source.source_type,
            independence_group=_independence_group(source),
            delegate=delegate,
            unbound_reason=reason,
            rate_limit_per_minute=rate_limit_per_minute,
        )
        bindings.append(_Binding(source=source, collector=collector))
    return bindings


def _job_status(outcome: CollectorOutcome) -> str:
    """A job's status, from what the orchestrator actually did.

    ``partial`` is the honest middle: the run produced records *and* something
    went wrong. Anything with no records is ``failed``, including a scope the
    collector refused — a refusal is a failure to collect, not a neutral
    outcome.
    """
    if outcome.observations == 0:
        return "failed"
    return "partial" if outcome.errors else "completed"


def _report_is_synthetic(report: CollectionReport) -> bool:
    """Whether this run touched a network, checked on both sides.

    The registry says no network collector is configured; the artefacts say
    every URL came from the in-process corpus. Both have to agree, so neither a
    fixture run nor a real one can be mislabelled by the other.
    """
    if NETWORK_COLLECTORS:
        return False
    return all(
        observation.raw.source_url.startswith(SYNTHETIC_URL_SCHEME)
        for observation in report.observations
    )


def _run_limitations(report: CollectionReport, bindings: Sequence[_Binding]) -> list[str]:
    notes = [
        "Collector output is returned by this endpoint, not written to the evidence ledger. "
        "Ingestion is aegis.collection.ingest and is a separate step, so nothing here has "
        "changed the evidence in a case.",
        "Counts are per bound collector, and a candidate that failed, timed out or was refused "
        "appears as an error string rather than as a missing row. A run that found nothing and "
        "a run that never looked are both reported as a job — with different reasons.",
    ]
    unbound = sum(1 for binding in bindings if binding.collector.delegate_name == "none")
    if unbound:
        notes.append(
            f"{unbound} of the {len(bindings)} registered sources had no collector bound to them "
            "and are recorded as failed jobs with the reason attached. They are not excluded "
            "from the run log, and their absence of records is not evidence about them."
        )
    if not report.observations:
        notes.append(
            "This run produced no observations at all. That is a statement about the run, not "
            "about the sources."
        )
    return notes


def _rate_guard(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    if not _run_limiter.allow(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"collection run rate limit exceeded: at most {MAX_RUNS_PER_MINUTE} runs per "
                "minute per client. The orchestrator paces fetches inside a run; this bounds "
                "how many runs may be started."
            ),
        )


@router.post("/run", response_model=CollectionRunResponse)
async def run_collection(
    payload: CollectionRunRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(_rate_guard)],
) -> CollectionRunResponse:
    """Execute a :class:`CollectionScope` through the real orchestrator.

    Asynchronous on purpose. The handler awaits
    :meth:`CollectorOrchestrator.run`, and the per-candidate pacing is the
    orchestrator's own sliding-window :class:`~aegis.collection.RateLimiter` —
    a blocking call here would hold the API thread for the length of the whole
    batch, which is the shape of a denial-of-service rather than a slow
    endpoint.

    One ``collection_jobs`` row is written per registered source, because
    ``collection_jobs.source_id`` is a foreign key and a run covers the whole
    register. A source that could not be collected is written as ``failed``
    with the orchestrator's own refusal text: the run log is a record of what
    the platform did, and a batch that hid its unreachable sources would claim
    a coverage it does not have.

    The response states whether the run was synthetic. It always does, and it
    is not derived from the run having succeeded.
    """
    if payload.case_id is not None and db.get(CaseRecord, payload.case_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    try:
        job_type = JobType(payload.job_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"job_type must be one of {', '.join(item.value for item in JobType)}",
        ) from exc

    sources = _source_records(db)
    if not sources:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "No sources are registered. A collection run has nothing to draw on, and "
                "returning an empty report here would read as a successful sweep of nothing."
            ),
        )

    scope = CollectionScope(
        job_type=job_type,
        case_id=str(payload.case_id) if payload.case_id is not None else None,
        seed_terms=tuple(payload.seed_terms),
        platforms=tuple(payload.platforms),
        since=payload.since,
        until=payload.until,
        limit=payload.limit,
        parameters={
            "max_attempts": payload.max_attempts,
            "rate_limit_per_minute": payload.rate_limit_per_minute,
        },
    )
    bindings = _bind_sources(sources, rate_limit_per_minute=payload.rate_limit_per_minute)
    orchestrator = CollectorOrchestrator(
        [binding.collector for binding in bindings], max_attempts=payload.max_attempts
    )
    report = await orchestrator.run(scope)

    # `CollectorOrchestrator` appends exactly one outcome per collector, in
    # collector order, so the two sequences align. The name check is there so a
    # change to that contract surfaces as a loud failure rather than as rows
    # attributed to the wrong source.
    if len(report.outcomes) != len(bindings):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The orchestrator returned a different number of outcomes than collectors.",
        )

    synthetic = _report_is_synthetic(report)
    rows: list[CollectionJobRecord] = []
    outcomes: list[CollectorOutcomeRow] = []
    for binding, outcome in zip(bindings, report.outcomes, strict=True):
        if outcome.collector_name != binding.collector.name:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Outcome {outcome.collector_name!r} does not match collector "
                    f"{binding.collector.name!r}; refusing to attribute it to a source."
                ),
            )
        job_status = _job_status(outcome)
        record = CollectionJobRecord(
            job_id=uuid4(),
            source_id=binding.source.source_id,
            collector_name=outcome.collector_name,
            collector_version=outcome.collector_version,
            status=job_status,
            started_at=report.started_at,
            finished_at=report.finished_at,
            metadata_json={
                "schema_version": COLLECTION_SCHEMA_VERSION,
                _SYNTHETIC_KEY: synthetic,
                "candidates": outcome.candidates,
                "records": outcome.observations,
                "errors": len(outcome.errors),
                "error_samples": list(outcome.errors[:5]),
                "independence_group": binding.collector.independence_group,
                "reliability": binding.source.reliability,
                "collector": binding.collector.delegate_name,
                "rate_limit_per_minute": payload.rate_limit_per_minute,
                "max_attempts": payload.max_attempts,
                "ingested": False,
                "scope": {
                    "job_type": str(job_type),
                    "case_id": str(payload.case_id) if payload.case_id else None,
                    "limit": payload.limit,
                    "platforms": list(payload.platforms),
                    "since": payload.since.isoformat() if payload.since else None,
                    "until": payload.until.isoformat() if payload.until else None,
                },
            },
        )
        db.add(record)
        rows.append(record)
        outcomes.append(
            CollectorOutcomeRow(
                collector_name=outcome.collector_name,
                collector_version=outcome.collector_version,
                candidates=outcome.candidates,
                observations=outcome.observations,
                errors=list(outcome.errors),
                source_id=binding.source.source_id,
                source_name=binding.source.name,
                source_type=binding.source.source_type,
                independence_group=binding.collector.independence_group,
                reliability=binding.source.reliability,
                job_id=record.job_id,
                job_status=job_status,
            )
        )
    db.flush()

    entry = AuditService(db).record(
        "collection.run",
        case_id=payload.case_id,
        entity_type="collection_run",
        entity_id=str(rows[0].job_id) if rows else None,
        payload={
            "schema_version": COLLECTION_SCHEMA_VERSION,
            "synthetic": synthetic,
            "collection_mode": "synthetic" if synthetic else "live",
            "status": _overall_status([row.status for row in rows]),
            "scope": {
                "job_type": str(job_type),
                "limit": payload.limit,
                "platforms": list(payload.platforms),
                "since": payload.since.isoformat() if payload.since else None,
                "until": payload.until.isoformat() if payload.until else None,
            },
            "sources": len(rows),
            "candidates": report.total_candidates,
            "records": report.total_observations,
            "errors": report.error_count,
            "job_ids": [str(row.job_id) for row in rows],
        },
        occurred_at=report.finished_at,
    )
    db.commit()

    overall = _overall_status([row.status for row in rows])
    mode_note = (
        "No network collector is registered in this deployment. This run executed the platform's "
        "own orchestrator over the in-process synthetic corpus: it is a rehearsal of the "
        "collection pipeline, not live collection, and nothing it returned was observed on a "
        "real venue."
        if synthetic
        else "This run executed the platform's orchestrator over the registered collectors."
    )
    return CollectionRunResponse(
        status=overall,
        scope={
            "job_type": str(job_type),
            "case_id": str(payload.case_id) if payload.case_id else None,
            "limit": payload.limit,
            "platforms": list(payload.platforms),
            "since": payload.since.isoformat() if payload.since else None,
            "until": payload.until.isoformat() if payload.until else None,
            "max_attempts": payload.max_attempts,
            "rate_limit_per_minute": payload.rate_limit_per_minute,
        },
        started_at=report.started_at,
        finished_at=report.finished_at,
        duration_seconds=report.duration_seconds,
        total_candidates=report.total_candidates,
        total_observations=report.total_observations,
        error_count=report.error_count,
        outcomes=outcomes,
        job_ids=[row.job_id for row in rows],
        audit_seq=entry.seq,
        collection_mode="synthetic" if synthetic else "live",
        synthetic=synthetic,
        mode_note=mode_note,
        ingested=False,
        notes=[
            f"One collection_jobs row was written per registered source ({len(rows)} rows), and "
            "one audit entry for the run.",
            f"{report.error_count} candidate-level error(s) were recorded and kept on the rows "
            "that produced them.",
        ],
        limitations=_run_limitations(report, bindings),
    )


def _overall_status(statuses: Sequence[str]) -> str:
    """A run's status from its per-source job statuses.

    A run is ``completed`` only when every source it touched completed. One
    refused source makes the batch ``partial``, because a run that quietly
    dropped a third of the register has not collected what it was asked for.
    """
    if not statuses:
        return "failed"
    if all(status == "completed" for status in statuses):
        return "completed"
    if any(status in ("completed", "partial") for status in statuses):
        return "partial"
    return "failed"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

_SOURCE_CSV_FIELDS: Final[tuple[str, ...]] = (
    "source_id",
    "name",
    "source_type",
    "reliability",
    "reliability_basis",
    "independence_group",
    "independence_group_size",
    "independence_note",
    "record_count",
    "job_count",
    "last_scanned_at",
    "last_status",
    "freshness",
    "synthetic",
)

_JOB_CSV_FIELDS: Final[tuple[str, ...]] = (
    "job_id",
    "source_id",
    "source_name",
    "collector_name",
    "collector_version",
    "status",
    "started_at",
    "finished_at",
    "duration_seconds",
    "candidates",
    "records",
    "errors",
    "error_samples",
    "independence_group",
    "reliability",
    "synthetic",
)


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    return str(value)


@router.get("/export")
def collection_export(
    db: Annotated[Session, Depends(get_db)],
    filters: Annotated[_JobFilters, Depends(_job_filters)],
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "csv",
    dataset: Annotated[str, Query(pattern="^(sources|jobs)$")] = "jobs",
) -> Response:
    """The registers as a file, through the same filters the list routes use.

    The CSV carries ``reliability_basis`` and ``independence_group_size``
    because a source register exported without them becomes a spreadsheet that
    invites the reader to count rows as independent sources. The JSON payload
    carries the status headline alongside both registers, whatever ``dataset``
    was asked for — a partial export that looks like the whole picture is the
    failure mode worth designing against.
    """
    now = datetime.now(UTC)
    sources = _source_register(db, now=now)
    jobs = filters.schema_many(db)
    summary = _collection_status(db, now=now)

    if format == "json":
        payload = CollectionExport(
            generated_at=now,
            dataset=dataset,
            filters=filters.described(),
            status=summary,
            sources=sources,
            jobs=jobs,
        )
        return Response(
            json.dumps(payload.model_dump(mode="json"), indent=2),
            media_type="application/json",
        )

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if dataset == "sources":
        writer.writerow(_SOURCE_CSV_FIELDS)
        for source_row in sources:
            writer.writerow([_csv_cell(getattr(source_row, field)) for field in _SOURCE_CSV_FIELDS])
    else:
        writer.writerow(_JOB_CSV_FIELDS)
        for job_row in jobs:
            writer.writerow([_csv_cell(getattr(job_row, field)) for field in _JOB_CSV_FIELDS])
    return Response(buffer.getvalue(), media_type="text/csv")


__all__ = [
    "COLLECTION_SCHEMA_VERSION",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "JOB_STATUSES",
    "MAX_RUNS_PER_MINUTE",
    "PLATFORM_FOR_SOURCE_TYPE",
    "RELIABILITY_BASIS",
    "RECENT_WINDOW_HOURS",
    "STALE_AFTER_DAYS",
    "CollectionExport",
    "CollectionJob",
    "CollectionJobDetail",
    "CollectionRunRequest",
    "CollectionRunResponse",
    "CollectionStatus",
    "CollectorOutcomeRow",
    "SourceQuality",
    "SourceScanCollector",
    "router",
]
