"""Behavioural change detection over a case's or an actor's history.

The platform could already answer *what happened when* — the workspace timeline
is a chronological list — and could not answer *when something changed, how
sharply, or whether one persona's pattern matches another's*. Everything needed
for the second answer already existed in :mod:`aegis.timeline` and nothing
reached it, because nothing in the database was a :class:`TimelineEvent`. The
registry stored *windows*; a window is not an observation.
:class:`~aegis.db.models.TemporalObservationRecord` is, and this module is the
only place that turns stored rows into detector input.

Four rules hold across every route:

* **The library is the only detector.**  ``cusum``, ``ks_distance``,
  ``mean_shift_gain``, ``ks_gain``, ``segment``, ``detect_handle_changes``,
  ``detect_marketplace_transitions`` and ``build_activity_series`` are called as
  written.  Nothing here re-measures, re-thresholds or re-ranks a change point:
  the ``sharpness`` on every row is the detector's own ``ChangePoint.score``.
* **A window too short to analyse is refused with a reason, not scored.**  The
  detectors express "not enough data" by returning ``()`` — indistinguishable at
  this boundary from "no change found", which is the failure this surface
  exists to avoid.  Every short window becomes a :class:`TemporalRefusal` naming
  the rule, the count supplied and the count required.
* **Limitations travel with the finding.**  ``limitations`` on a row is
  :data:`DETECTOR_LIMITATIONS` for the detector that produced it — the library's
  own documented statements, not hedges added at the edge.
* **Absence is stated, never implied.**  A report with no shifts carries a
  ``basis`` sentence saying what was analysed and what the empty result means.  A
  case with no stored history at all gets a 422, not an empty list.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.db.models import (
    ActorIdentifierRecord,
    ActorMarketplaceRecord,
    ActorRecord,
    AuditLogRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    TemporalObservationRecord,
)
from aegis.timeline.algorithms import ks_distance, ks_gain, mean_shift_gain, segment
from aegis.timeline.detectors import (
    DEFAULT_MIN_PERSIST,
    _union_evidence,
    build_activity_series,
    detect_activity_shifts,
    detect_handle_changes,
    detect_marketplace_transitions,
)
from aegis.timeline.types import ChangePoint, Direction, TimelineEvent, TimelineEventKind

router = APIRouter(prefix="/api/v1", tags=["temporal"])

#: The channels a stored observation can be on, and the detection channel each
#: maps to.  The library defines five; only these three have stored rows, and a
#: route that accepted the other two would report an empty analysis as though
#: the channel had been looked at.
CHANNEL_KINDS: dict[str, TimelineEventKind] = {
    "handle": TimelineEventKind.HANDLE,
    "marketplace": TimelineEventKind.MARKETPLACE,
    "activity": TimelineEventKind.ACTIVITY,
}

CHANNEL_LABELS: dict[str, str] = {
    "handle": "handle",
    "marketplace": "marketplace",
    "activity": "posting cadence",
}

#: Buckets either side of a boundary carried on a shift row, so the chart can
#: show the regime the break sits in without shipping a whole series per row.
CONTEXT_BUCKETS = 12

SubjectKind = Literal["actor", "entity"]


def activity_min_buckets(min_size: int) -> int:
    """``max(2 * min_size, 4)`` — below this ``detect_activity_shifts`` returns ``()``.

    Reproduced here because "returned nothing" and "found nothing" are the same
    bytes on the wire, and only one of them is a finding.
    """
    return max(2 * min_size, 4)


def state_min_events(min_persist: int) -> int:
    """Fewest events a state channel can hold and still produce a transition.

    A change at index ``i`` is emitted only when ``i + 1 + min_persist`` events
    exist, so anything shorter can never confirm one.
    """
    return min_persist + 2


def segment_min_points(min_size: int) -> int:
    """``2 * min_size`` — below this ``segment`` skips the series entirely."""
    return 2 * min_size


#: Thresholds this surface applies when the caller supplies none.
#:
#: The library's own defaults are unit-scale (``1.0`` for a mean-shift gain, a
#: number whose units are count²·buckets).  On a 50-bucket daily series a gain
#: of 1.0 is reached by ordinary noise — a gain of ``n_l·n_r/(n_l+n_r)·Δ²``
#: needs only ``Δ ≈ 0.3`` events per bucket — so a detector firing at the
#: library default would mark every series in the database as changed.  The
#: value below corresponds to ``Δ ≈ 3`` events per bucket at n=50: a regime
#: change big enough to read as one.  ``ks`` is already 0-1 and needs only that
#: the two halves of a 50-bucket series be distributionally distinct.
SERVICE_MIN_GAIN: dict[str, float] = {"ks": 0.6, "binary_segmentation": 100.0}


# --------------------------------------------------------------------------
# Detector limitations, in the detector's own words
#
# These are the statements the library's docstrings make about what its output
# does and does not establish.  They are quoted rather than paraphrased because
# a paraphrase is where a caveat quietly becomes reassurance.
# --------------------------------------------------------------------------

_STATE_CHANGE_LIMITATIONS: tuple[str, ...] = (
    "A change is only emitted when the new value persists for min_persist following "
    "events; a single-event flap is dropped, and so is a change at the end of the "
    "stream that never gets its confirmation window. A change this detector did not "
    "report is therefore not the same as a change that did not happen.",
    "The score is 1.0 for every confirmed state change. It records that the "
    "persistence rule was satisfied, not how sure the detector is that the move was "
    "real — 1.0 here is not a probability.",
    "A confirmed transition shows the value changed and stayed changed. It does not "
    "show that the previous value is gone, that the two values belong to the same "
    "person, or that the move was a migration rather than two accounts alternating.",
    "Transitions are detected per subject on a single channel, and the library "
    "rejects a stream carrying more than one subject rather than merging them. A "
    "change visible only through a source this platform does not collect is not "
    "merely undetected here; it is unobservable.",
)

_ACTIVITY_LIMITATIONS: tuple[str, ...] = (
    "For CUSUM, changed_at is the start of the bucket where the detector fired — an "
    "upper bound on when the shift began, documented by the library as approximate. "
    "The shift itself happened somewhere in the run leading up to that bucket.",
    "A CUSUM alarm sums the per-bucket excess over reference + drift, so the score "
    "grows with how long a shift persists. It is not comparable between series of "
    "different lengths, and it is not a probability.",
    "CUSUM references the series mean unless an explicit reference is supplied, so a "
    "regime change large enough to move the mean moves the baseline the change is "
    "measured against. Both accumulators reset after each alarm, so one long regime "
    "shift yields one alarm.",
    "Segmentation is greedy: the best split of a segment is taken first and each half "
    "is considered in turn, so a later split can be missed where an exact method would "
    "not. Strict improvement is required and the first cut wins ties, which makes the "
    "result deterministic but not the unique best partition.",
    "The KS statistic lies in [0, 1] and is a distance between two empirical "
    "distributions. It is not the probability that a change occurred, and it is not "
    "comparable against a mean-shift gain from a different series.",
    "Buckets are zero-filled, so silence is a data point: a persona nobody collected "
    "is indistinguishable from one that stopped trading. A detector firing inside a "
    "zero-filled gap bucket cites no evidence at all, because no event backs it.",
)

DETECTOR_LIMITATIONS: dict[str, tuple[str, ...]] = {
    "state_change": _STATE_CHANGE_LIMITATIONS,
    "cusum": _ACTIVITY_LIMITATIONS,
    "ks": _ACTIVITY_LIMITATIONS,
    "binary_segmentation": _ACTIVITY_LIMITATIONS,
}

#: The statements true of every detector on this surface.
COMMON_LIMITATIONS: tuple[str, ...] = (
    "Every change point here is derived from one subject's stored observations at the "
    "moment of the request. Nothing is cached, so two reads a second apart can "
    "legitimately disagree if an observation was written between them, and nothing on "
    "this surface has been reviewed by an analyst.",
)


def limitations_for(detector: str) -> tuple[str, ...]:
    """The detector's documented limitations, plus the ones common to all."""
    return (*DETECTOR_LIMITATIONS.get(detector, ()), *COMMON_LIMITATIONS)


# --------------------------------------------------------------------------
# Response schemas
# --------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class TemporalRefusal(_Frozen):
    """A window too short to analyse, and why.

    Returned instead of a score.  A ``ks_distance`` over three points is a
    number, not a finding, and serving it as one is the failure mode this
    schema exists to prevent.
    """

    subject_id: str
    subject_kind: str
    subject_label: str | None = None
    channel: str
    rule: str
    reason: str
    observed: int
    required: int
    unit: str = "observations"


class EvidenceWindow(_Frozen):
    """One side of a boundary: what was observed there, and what it cites."""

    label: str
    from_at: datetime | None = None
    to_at: datetime | None = None
    event_count: int = 0
    #: Distinct states observed, first-seen order. Empty on a numeric channel,
    #: which has no states — there ``buckets`` and ``mean_count`` say it.
    values: tuple[str, ...] = ()
    buckets: int = 0
    mean_count: float | None = None
    evidence_ids: tuple[str, ...] = ()


class ContextPoint(_Frozen):
    """One point of the series a change point sits inside."""

    at: datetime
    value: str
    #: The activity count in this bucket.  ``None`` on a categorical channel,
    #: which has no magnitude and is drawn as a value track instead.
    count: float | None = None
    is_boundary: bool = False


class TemporalShift(_Frozen):
    """One detected change, with the evidence on both sides of the boundary."""

    change_id: str
    case_id: UUID | None = None
    subject_id: str
    subject_kind: str
    subject_label: str | None = None
    channel: str
    channel_label: str
    detector: str
    detector_label: str
    changed_at: datetime
    #: The detector's own score, unmodified.  What it means is stated in
    #: ``sharpness_note`` rather than left for the reader to guess.
    sharpness: float
    sharpness_note: str
    direction: str | None = None
    from_value: str | None = None
    to_value: str | None = None
    summary: str
    before: EvidenceWindow
    after: EvidenceWindow
    #: The library's own ``ks_distance`` between the two halves of an activity
    #: split — a supplementary 0-1 comparability figure across detectors, and
    #: ``None`` on a categorical channel, which has no distribution to compare.
    distribution_distance: float | None = None
    context: tuple[ContextPoint, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class TemporalShiftReport(_Frozen):
    """Every change the detectors found for one case, and what they refused."""

    case_id: UUID
    generated_at: datetime
    method: str
    bucket: str
    min_persist: int
    subjects: int
    observations: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    shifts: tuple[TemporalShift, ...] = ()
    refusals: tuple[TemporalRefusal, ...] = ()
    #: Stated on every read, including an empty one.  "No change was detected in
    #: 1,204 observations across 9 subjects" and "this case has too little
    #: history to support a claim" are different findings and must not read alike.
    basis: str
    limitations: tuple[str, ...] = ()


class TemporalBoundary(_Frozen):
    """One cut returned by :func:`aegis.timeline.algorithms.segment`."""

    index: int
    at: datetime
    gain: float
    mean_before: float
    mean_after: float


class TemporalRegime(_Frozen):
    """One segment of a segmented series: an average is not a description.

    ``first_bucket``/``last_bucket`` rather than ``from_at``/``to_at`` because a
    regime is a set of buckets, not an interval: the last bucket *belongs* to
    this regime, so a "to" timestamp at its start would read as a range ending
    before the regime does.
    """

    index: int
    first_bucket: datetime
    last_bucket: datetime
    buckets: int
    mean: float
    peak: float
    total: float


class SubjectSegmentation(_Frozen):
    """One subject's activity series, divided into regimes by ``segment``."""

    subject_id: str
    subject_kind: str
    subject_label: str | None = None
    channel: str
    gain_function: str
    min_size: int
    min_gain: float
    buckets: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    boundaries: tuple[TemporalBoundary, ...] = ()
    regimes: tuple[TemporalRegime, ...] = ()
    limitations: tuple[str, ...] = ()


class TemporalSegmentationReport(_Frozen):
    """Segmented series for every subject in a case, plus what was refused."""

    case_id: UUID
    generated_at: datetime
    gain: str
    min_size: int
    min_gain: float
    bucket: str
    series: tuple[SubjectSegmentation, ...] = ()
    refusals: tuple[TemporalRefusal, ...] = ()
    basis: str
    limitations: tuple[str, ...] = ()


class ActorPresence(_Frozen):
    """A stored ``actor_marketplaces`` window, for reading beside the transitions."""

    marketplace: str
    role: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    listing_count: int | None = None


class ActorTransitionReport(_Frozen):
    """Cross-marketplace movement for one registry actor."""

    actor_id: UUID
    handle: str
    generated_at: datetime
    min_persist: int
    marketplaces: tuple[str, ...] = ()
    presence: tuple[ActorPresence, ...] = ()
    window_start: datetime | None = None
    window_end: datetime | None = None
    transitions: tuple[TemporalShift, ...] = ()
    refusals: tuple[TemporalRefusal, ...] = ()
    basis: str
    limitations: tuple[str, ...] = ()


class BehaviourPoint(_Frozen):
    """One bucket of an actor's activity series."""

    at: datetime
    events: int
    magnitude: float


class AlgorithmBandwidth(_Frozen):
    """What one algorithm family needs before its output means anything."""

    algorithm: str
    min_points: int
    note: str


class Bandwidth(_Frozen):
    """The sample each algorithm family requires, declared rather than implied."""

    cusum: AlgorithmBandwidth
    ks: AlgorithmBandwidth
    binary_segmentation: AlgorithmBandwidth


class ActorBehaviourReport(_Frozen):
    """One actor's activity series, chartable, with the analysis bandwidth."""

    actor_id: UUID
    handle: str
    generated_at: datetime
    channel: str
    bucket: str
    points: tuple[BehaviourPoint, ...] = ()
    buckets: int = 0
    observations: int = 0
    window_start: datetime | None = None
    window_end: datetime | None = None
    mean: float | None = None
    standard_deviation: float | None = None
    peak: float | None = None
    silent_buckets: int = 0
    #: False below the width the algorithms need.  The points are still
    #: returned — they are what the analyst has — and ``refusal`` says what is
    #: missing rather than the absence being reported as a stable series.
    analysable: bool = False
    refusal: TemporalRefusal | None = None
    bandwidth: Bandwidth
    limitations: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# Stored rows -> detector input
# --------------------------------------------------------------------------


def _citation(record: TemporalObservationRecord) -> tuple[str, ...]:
    """What one observation cites.

    The library rejects a ``TimelineEvent`` with no evidence ids, which is the
    right rule.  A sighting read from a ledger record cites that record; one
    with no ledger row cites *itself*, by id — a real stored row an analyst can
    open.  Inventing a citation would be worse, and dropping the observation
    would quietly shrink the series the detector is run over.
    """
    if record.evidence_id is not None:
        return (str(record.evidence_id),)
    return (f"temporal-observation:{record.observation_id}",)


def _aware(stamp: datetime) -> datetime:
    """Timestamps from a naive column are UTC; the library refuses naive ones."""
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def _to_event(record: TemporalObservationRecord) -> TimelineEvent:
    kind = CHANNEL_KINDS.get(record.channel)
    if kind is None:
        raise ValueError(f"unmapped channel {record.channel!r}")
    return TimelineEvent(
        event_id=str(record.observation_id),
        subject_id=record.subject_id,
        kind=kind,
        observed_at=_aware(record.observed_at),
        value=record.value,
        evidence_ids=_citation(record),
    )


def _observations(
    db: Session,
    *,
    case_id: UUID | None = None,
    actor_id: UUID | None = None,
    entity_id: UUID | None = None,
    channel: str | None = None,
) -> list[TemporalObservationRecord]:
    """Stored sightings, oldest first.

    Ordered in the database rather than in Python because the detectors sort on
    ``(observed_at, event_id)`` and a detector's output must not depend on the
    order Postgres happened to return.
    """
    query = select(TemporalObservationRecord)
    if case_id is not None:
        query = query.where(TemporalObservationRecord.case_id == case_id)
    if actor_id is not None:
        query = query.where(TemporalObservationRecord.actor_id == actor_id)
    if entity_id is not None:
        query = query.where(TemporalObservationRecord.entity_id == entity_id)
    if channel is not None:
        query = query.where(TemporalObservationRecord.channel == channel)
    return list(
        db.scalars(
            query.order_by(
                TemporalObservationRecord.observed_at.asc(),
                TemporalObservationRecord.observation_id.asc(),
            )
        ).all()
    )


def _grouped(
    records: Sequence[TemporalObservationRecord],
) -> dict[tuple[str, str], list[TemporalObservationRecord]]:
    """Sightings keyed by ``(subject_id, channel)``.

    The detectors require one subject per stream and raise on a mixed one, so
    this grouping is the input contract rather than a convenience.
    """
    grouped: dict[tuple[str, str], list[TemporalObservationRecord]] = {}
    for record in records:
        grouped.setdefault((record.subject_id, record.channel), []).append(record)
    return grouped


def _subject_id(subject: Any) -> str | None:
    try:
        return str(UUID(subject))
    except (TypeError, ValueError):
        return None


def _labels(
    db: Session, records: Sequence[TemporalObservationRecord]
) -> dict[str, tuple[str, str]]:
    """``subject_id -> (kind, human label)`` from the registry and the entities.

    Resolved in two queries rather than one per subject, because a case can
    carry hundreds of them and the detection run is the expensive part.
    """
    def parsed_ids(kind: str) -> set[str]:
        found: set[str] = set()
        for row in records:
            if row.subject_kind != kind:
                continue
            parsed = _subject_id(row.subject_id)
            if parsed is not None:
                found.add(parsed)
        return found

    actor_ids = parsed_ids("actor")
    entity_ids = parsed_ids("entity")
    labels: dict[str, tuple[str, str]] = {}
    if actor_ids:
        for actor in db.scalars(
            select(ActorRecord).where(ActorRecord.actor_id.in_(actor_ids))
        ).all():
            labels[str(actor.actor_id)] = ("actor", actor.handle)
    if entity_ids:
        for entity in db.scalars(
            select(EntityRecord).where(EntityRecord.entity_id.in_(entity_ids))
        ).all():
            labels[str(entity.entity_id)] = ("entity", entity.surface_form)
    return labels


def _subject_label(
    labels: dict[str, tuple[str, str]], subject_id: str, fallback: str
) -> tuple[str, str | None]:
    kind, label = labels.get(subject_id, (fallback, None))
    return kind, label


class _Stream:
    """One subject on one channel, ready to hand to a detector.

    The library takes a bare ``Sequence[TimelineEvent]`` and rejects a stream
    carrying two subjects, so the grouping and the provenance have to live
    somewhere. This is that somewhere — and it exists because a case's stream is
    not only its stored observations: see :func:`_case_streams`.
    """

    __slots__ = ("subject_id", "subject_kind", "subject_label", "channel", "events")

    def __init__(
        self,
        subject_id: str,
        subject_kind: str,
        subject_label: str | None,
        channel: str,
        events: Sequence[TimelineEvent],
    ) -> None:
        self.subject_id = subject_id
        self.subject_kind = subject_kind
        self.subject_label = subject_label
        self.channel = channel
        self.events = sorted(events, key=lambda event: (event.observed_at, event.event_id))


def _case_streams(
    db: Session, case_id: UUID
) -> dict[tuple[str, str], _Stream]:
    """Every channel a case's behavioural history can be read on.

    Four sources, because a case's history is not one table:

    1. ``temporal_observations`` for this case — the per-entity sighting stream
       and the only source of the handle and marketplace channels.
    2. The tracked personas whose identifiers were observed in this case, whose
       own history is cross-case and therefore carries no ``case_id``.
    3. The case's own **evidence ledger**, one activity event per record. This is
       the platform's collection behaviour for the case: how much was collected,
       and when. A real series with real citations, not a derived one.
    4. The case's **audit timeline**, one activity event per entry, under its own
       subject. A separate subject rather than more events on the evidence
       subject, because the two are different processes and merging them would
       hide a change in one behind volume in the other.
    """
    records = _observations(db, case_id=case_id)
    labels = _labels(db, records)
    streams: dict[tuple[str, str], _Stream] = {}

    def add(
        subject_id: str,
        subject_kind: str,
        subject_label: str | None,
        channel: str,
        events: Sequence[TimelineEvent],
    ) -> None:
        key = (subject_id, channel)
        existing = streams.get(key)
        if existing is None:
            streams[key] = _Stream(subject_id, subject_kind, subject_label, channel, events)
            return
        streams[key] = _Stream(
            subject_id, subject_kind, subject_label, channel, [*existing.events, *events]
        )

    for (subject_id, channel), group in sorted(_grouped(records).items()):
        kind, subject_label = _subject_label(labels, subject_id, group[0].subject_kind)
        add(subject_id, kind, subject_label, channel, [_to_event(row) for row in group])

    # (1b) the tracked personas observed *in* this case. An actor is cross-case,
    # so its observations carry no `case_id` — the honest link from a persona to
    # an investigation is `actor_identifiers.case_id`, which records that a
    # specific identifier was seen here. Without this a case's panel could only
    # ever describe its own extracted entities, and the question an analyst
    # actually asks of a timeline — "did a persona in this case change?" — would
    # have no answer anywhere.
    linked_actors = list(
        db.scalars(
            select(ActorIdentifierRecord.actor_id)
            .where(ActorIdentifierRecord.case_id == case_id)
            .distinct()
        ).all()
    )
    if linked_actors:
        persona_rows = [
            row
            for actor_id in linked_actors
            for row in _observations(db, actor_id=actor_id)
        ]
        persona_labels = _labels(db, persona_rows)
        for (subject_id, channel), group in sorted(_grouped(persona_rows).items()):
            if (subject_id, channel) in streams:
                continue
            kind, subject_label = _subject_label(
                persona_labels, subject_id, group[0].subject_kind
            )
            add(subject_id, kind, subject_label, channel, [_to_event(row) for row in group])

    # (2) the evidence ledger. `collected_at` rather than `observed_at`: when
    # the platform was working is what an activity series measures, and
    # `observed_at` is nullable for records ingested after the fact.
    evidence_rows = list(
        db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.case_id == case_id)
            .order_by(EvidenceRecord.collected_at.asc())
        ).all()
    )
    if evidence_rows:
        subject = f"case:{case_id}"
        add(
            subject,
            "case",
            f"evidence collected for {case_id}",
            "activity",
            [
                TimelineEvent(
                    event_id=f"evidence-{row.evidence_id}",
                    subject_id=subject,
                    kind=TimelineEventKind.ACTIVITY,
                    observed_at=_aware(row.collected_at),
                    value=row.source_type or "unspecified",
                    evidence_ids=(str(row.evidence_id),),
                )
                for row in evidence_rows
            ],
        )

    # (3) the audit timeline. The trail is append-only, so its entries are the
    # most complete record the platform keeps of its own behaviour.
    audit_rows = list(
        db.scalars(
            select(AuditLogRecord)
            .where(AuditLogRecord.case_id == case_id)
            .order_by(AuditLogRecord.seq.asc())
        ).all()
    )
    if audit_rows:
        subject = f"case-audit:{case_id}"
        add(
            subject,
            "case",
            f"audit trail for {case_id}",
            "activity",
            [
                TimelineEvent(
                    event_id=f"audit-{row.seq}",
                    subject_id=subject,
                    kind=TimelineEventKind.ACTIVITY,
                    observed_at=_aware(row.occurred_at),
                    value=row.action,
                    # Not an evidence-ledger row, so it cites its own entry in
                    # the hash-chained trail rather than a ledger id it does not
                    # have. The library requires a non-empty citation; a
                    # fabricated one would be worse than the true one.
                    evidence_ids=(f"audit-log:{row.seq}",),
                )
                for row in audit_rows
            ],
        )

    return streams


# --------------------------------------------------------------------------
# Windows either side of a boundary
# --------------------------------------------------------------------------


def _window(
    label: str,
    events: Sequence[TimelineEvent],
    *,
    counts: Sequence[float] | None = None,
) -> EvidenceWindow:
    """Summarise one side of a boundary and cite the events that make it up.

    Citations go through the library's own ``_union_evidence`` so a window's
    ids are deduplicated in the same first-seen order the change point's own
    are — two orderings for one claim would be a quiet inconsistency.  Every id
    here is an id a stored observation actually carries; nothing is minted for a
    bucket.
    """
    if not events:
        return EvidenceWindow(label=label, buckets=len(counts or ()))
    return EvidenceWindow(
        label=label,
        from_at=min(event.observed_at for event in events),
        to_at=max(event.observed_at for event in events),
        event_count=len(events),
        values=tuple(dict.fromkeys(event.value for event in events)) if counts is None else (),
        buckets=len(counts or ()),
        mean_count=round(sum(counts) / len(counts), 6) if counts else None,
        evidence_ids=_union_evidence(events),
    )


def _boundary_index(
    series: Sequence[tuple[datetime, float]], changed_at: datetime
) -> int:
    """Index of the first bucket at or after the change point."""
    return min(
        (index for index, (at, _) in enumerate(series) if at >= changed_at),
        default=len(series),
    )


def _categorical_windows(
    events: Sequence[TimelineEvent], change: ChangePoint, min_persist: int
) -> tuple[EvidenceWindow, EvidenceWindow]:
    """Before = the run that ended with the old value; after = the new one.

    Each side is capped at the same runway the persistence rule needed, so the
    two windows are the claim and its confirmation rather than an arbitrary
    amount of surrounding history.
    """
    ordered = sorted(events, key=lambda event: (event.observed_at, event.event_id))
    at = change.changed_at
    before = [
        event
        for event in ordered
        if event.kind is change.kind
        and event.value == change.from_value
        and event.observed_at < at
    ][-min_persist - 1 :]
    after = [
        event
        for event in ordered
        if event.kind is change.kind and event.value == change.to_value
    ][: min_persist + 1]
    return _window("before", before), _window("after", after)


def _activity_windows(
    events: Sequence[TimelineEvent],
    series: Sequence[tuple[datetime, float]],
    change: ChangePoint,
) -> tuple[EvidenceWindow, EvidenceWindow]:
    """Before and after = the two halves of the bucketed series, and their events."""
    index = _boundary_index(series, change.changed_at)
    cut = series[index][0] if index < len(series) else change.changed_at
    before_events = [event for event in events if event.observed_at < cut]
    after_events = [event for event in events if event.observed_at >= cut]
    return (
        _window("before", before_events, counts=[count for _, count in series[:index]]),
        _window("after", after_events, counts=[count for _, count in series[index:]]),
    )


def _activity_context(
    series: Sequence[tuple[datetime, float]],
    change: ChangePoint,
    *,
    window: int = CONTEXT_BUCKETS,
) -> tuple[ContextPoint, ...]:
    """The buckets either side of the boundary, for the chart.

    Counts are the real bucket values ``build_activity_series`` produced; the
    label is a transcription of the count rather than a claim about it.
    """
    if not series:
        return ()
    boundary = _boundary_index(series, change.changed_at)
    start = max(0, boundary - window)
    stop = min(len(series), boundary + window)
    return tuple(
        ContextPoint(
            at=at,
            value=f"{count:.0f} event{'' if count == 1 else 's'}",
            count=count,
            is_boundary=index == boundary,
        )
        for index, (at, count) in enumerate(series[start:stop], start=start)
    )


def _value_context(
    events: Sequence[TimelineEvent], change: ChangePoint, *, window: int = CONTEXT_BUCKETS
) -> tuple[ContextPoint, ...]:
    """The state track either side of a categorical boundary."""
    ordered = sorted(events, key=lambda event: (event.observed_at, event.event_id))
    at = change.changed_at
    before = [event for event in ordered if event.observed_at < at]
    after = [event for event in ordered if event.observed_at >= at]
    seen_boundary = False
    points: list[ContextPoint] = []
    for event in before[-window:] + after[:window]:
        is_boundary = event.observed_at == at and not seen_boundary
        seen_boundary = seen_boundary or is_boundary
        points.append(
            ContextPoint(at=event.observed_at, value=event.value, is_boundary=is_boundary)
        )
    return tuple(points)


# --------------------------------------------------------------------------
# Change points -> response rows
# --------------------------------------------------------------------------

DETECTOR_LABELS: dict[str, str] = {
    "state_change": "confirmed state change (persistence rule)",
    "cusum": "CUSUM over bucketed activity",
    "ks": "binary segmentation by KS distance",
    "binary_segmentation": "binary segmentation by mean-shift gain",
}

SHARPNESS_NOTES: dict[str, str] = {
    "state_change": "1.0 means the new value persisted across the confirmation window. "
    "It is not a probability, and it is not comparable with the numbers below.",
    "cusum": "Cumulative excess of each bucket over reference + drift, in the detector's "
    "own units. It grows with how long the shift persists, so two CUSUM scores from "
    "series of different lengths are not comparable.",
    "ks": "Kolmogorov-Smirnov distance in [0, 1] between the empirical distributions "
    "either side of the cut. It is a distance, not a probability.",
    "binary_segmentation": "Between-segment variance the cut bought, in count²·buckets. "
    "Comparable only against other cuts of the same series.",
}


def _direction(change: ChangePoint) -> str | None:
    return Direction(change.direction).value if change.direction is not None else None


def _summary(change: ChangePoint, channel: str) -> str:
    if change.from_value is not None and change.to_value is not None:
        return f"{CHANNEL_LABELS[channel]} changed: {change.from_value} → {change.to_value}"
    verb = "rose" if change.direction is Direction.INCREASE else "fell"
    if change.detector == "cusum":
        return f"posting cadence {verb} sharply — CUSUM alarmed in this bucket"
    return f"posting cadence split into two regimes at this bucket (activity {verb} across it)"


def _shift(
    change: ChangePoint,
    *,
    case_id: UUID | None,
    subject_kind: str,
    subject_label: str | None,
    channel: str,
    events: Sequence[TimelineEvent],
    series: Sequence[tuple[datetime, float]],
) -> TemporalShift:
    """One :class:`ChangePoint` rendered, with everything the library gave it.

    The windows are computed here rather than read off the change point because
    the library records only the citations for the firing bucket — the regime on
    each side is what an analyst has to check the claim against.
    """
    categorical = change.from_value is not None
    if categorical:
        before, after = _categorical_windows(events, change, DEFAULT_MIN_PERSIST)
        context = _value_context(events, change)
        distance: float | None = None
    else:
        before, after = _activity_windows(events, series, change)
        context = _activity_context(series, change)
        counts = [count for _, count in series]
        index = _boundary_index(series, change.changed_at)
        # The library's own distance between the two halves. Supplementary to
        # the detector's score and on a 0-1 scale, so an activity shift can be
        # compared with another detector's without translating units.
        distance = (
            round(
                ks_distance(counts[:index], counts[index:]),
                6,
            )
            if counts[:index] and counts[index:]
            else None
        )
    return TemporalShift(
        change_id=change.change_id,
        case_id=case_id,
        subject_id=change.subject_id,
        subject_kind=subject_kind,
        subject_label=subject_label,
        channel=channel,
        channel_label=CHANNEL_LABELS[channel],
        detector=change.detector,
        detector_label=DETECTOR_LABELS.get(change.detector, change.detector),
        changed_at=change.changed_at,
        sharpness=round(change.score, 6),
        sharpness_note=SHARPNESS_NOTES.get(change.detector, ""),
        direction=_direction(change),
        from_value=change.from_value,
        to_value=change.to_value,
        summary=_summary(change, channel),
        before=before,
        after=after,
        distribution_distance=distance,
        context=context,
        evidence_ids=change.evidence_ids,
        limitations=limitations_for(change.detector),
    )


# --------------------------------------------------------------------------
# Case routes
# --------------------------------------------------------------------------


def _case_or_404(db: Session, case_id: UUID) -> CaseRecord:
    case = db.get(CaseRecord, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


def _actor_or_404(db: Session, actor_id: UUID) -> ActorRecord:
    actor = db.get(ActorRecord, actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Actor not found")
    return actor


def _span(bucket: str) -> timedelta:
    return timedelta(seconds=float(bucket))


def _state_refusal(
    subject_id: str,
    subject_kind: str,
    subject_label: str | None,
    channel: str,
    observed: int,
    required: int,
    min_persist: int,
    noun: str,
) -> TemporalRefusal:
    return TemporalRefusal(
        subject_id=subject_id,
        subject_kind=subject_kind,
        subject_label=subject_label,
        channel=channel,
        rule="a confirmed state change needs 1 + 1 + min_persist observations",
        reason=(
            f"{observed} {noun} sighting(s) are stored and {required} are needed. The "
            f"detector only emits a transition once the new value has persisted across "
            f"{min_persist} following sightings, and it deliberately drops a change at the "
            "end of the stream that never gets that window. This subject has not been shown "
            "not to have changed."
        ),
        observed=observed,
        required=required,
    )


def _activity_refusal(
    subject_id: str,
    subject_kind: str,
    subject_label: str | None,
    observed: int,
    required: int,
    min_size: int,
) -> TemporalRefusal:
    return TemporalRefusal(
        subject_id=subject_id,
        subject_kind=subject_kind,
        subject_label=subject_label,
        channel="activity",
        rule="max(2 * min_size, 4) buckets",
        reason=(
            f"{observed} bucket(s) of activity are stored and the detector needs "
            f"max(2 × {min_size}, 4) = {required}. A distribution distance or a split gain "
            "over that many points is a number rather than a change, so no score was "
            "computed and this subject is reported as unanalysed rather than unchanged."
        ),
        observed=observed,
        required=required,
        unit="buckets",
    )


@router.get("/cases/{case_id}/temporal/shifts", response_model=TemporalShiftReport)
def case_temporal_shifts(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    method: Annotated[str, Query(pattern="^(cusum|ks|binary_segmentation)$")] = (
        "binary_segmentation"
    ),
    bucket: Annotated[str, Query(pattern="^[0-9]+$")] = "86400",
    min_persist: Annotated[int, Query(ge=0, le=20)] = DEFAULT_MIN_PERSIST,
    min_gain: Annotated[float | None, Query(ge=0.0)] = None,
    min_size: Annotated[int, Query(ge=1, le=60)] = 3,
    drift: Annotated[float | None, Query(gt=0.0)] = None,
    threshold: Annotated[float | None, Query(gt=0.0)] = None,
) -> TemporalShiftReport:
    """Behavioural state changes in a case, found by the real detectors.

    Run over three streams — the case's stored observations, its evidence ledger
    and its audit trail (see :func:`_case_streams`) — because "what changed
    about this persona" and "when did collection on this case change" are
    different questions that happen to share a detector.

    Handle changes and marketplace transitions come from the library's
    persistence-confirmed state detection; the activity channels are segmented by
    the requested numeric method.  The score on every row is that detector's own.

    ``min_gain`` defaults to :data:`SERVICE_MIN_GAIN` rather than the library's
    unit-scale default, for the reason given there: on a daily count series the
    library default is cleared by ordinary noise.  Whichever value is applied is
    returned in the response rather than left implicit.
    """
    case = _case_or_404(db, case_id)
    span = _span(bucket)
    streams = _case_streams(db, case_id)
    if not streams:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Case {case_id} has no stored timeline, no evidence records and no audit "
                "entries, so no behavioural claim can be supported. This is not the same as "
                "no change having occurred: every channel is empty because nothing has been "
                "collected for this case, so the absence is a collection gap rather than a "
                "finding."
            ),
        )

    floor = SERVICE_MIN_GAIN[method] if min_gain is None else min_gain
    required_state = state_min_events(min_persist)
    required_activity = activity_min_buckets(min_size)
    observations = sum(len(stream.events) for stream in streams.values())

    shifts: list[TemporalShift] = []
    refusals: list[TemporalRefusal] = []

    for key in sorted(streams):
        stream = streams[key]
        events = stream.events

        if stream.channel in {"handle", "marketplace"}:
            noun = stream.channel
            if len(events) < required_state:
                refusals.append(
                    _state_refusal(
                        stream.subject_id,
                        stream.subject_kind,
                        stream.subject_label,
                        stream.channel,
                        len(events),
                        required_state,
                        min_persist,
                        noun,
                    )
                )
                continue
            detect = (
                detect_handle_changes
                if stream.channel == "handle"
                else detect_marketplace_transitions
            )
            for change in detect(events, min_persist=min_persist):
                shifts.append(
                    _shift(
                        change,
                        case_id=case_id,
                        subject_kind=stream.subject_kind,
                        subject_label=stream.subject_label,
                        channel=stream.channel,
                        events=events,
                        series=(),
                    )
                )
            continue

        series = build_activity_series(events, bucket=span)
        if len(series) < required_activity:
            refusals.append(
                _activity_refusal(
                    stream.subject_id,
                    stream.subject_kind,
                    stream.subject_label,
                    len(series),
                    required_activity,
                    min_size,
                )
            )
            continue
        tuner: dict[str, Any] = {}
        if drift is not None:
            tuner["drift"] = drift
        if threshold is not None:
            tuner["threshold"] = threshold
        for change in detect_activity_shifts(
            events,
            bucket=span,
            method=method,
            min_gain=floor,
            min_size=min_size,
            **tuner,
        ):
            shifts.append(
                _shift(
                    change,
                    case_id=case_id,
                    subject_kind=stream.subject_kind,
                    subject_label=stream.subject_label,
                    channel=stream.channel,
                    events=events,
                    series=series,
                )
            )

    shifts.sort(key=lambda row: (row.changed_at, row.change_id))
    stamps = [
        event.observed_at for stream in streams.values() for event in stream.events
    ]
    return TemporalShiftReport(
        case_id=case.case_id,
        generated_at=datetime.now(UTC),
        method=method,
        bucket=bucket,
        min_persist=min_persist,
        subjects=len(streams),
        observations=observations,
        window_start=min(stamps),
        window_end=max(stamps),
        shifts=tuple(shifts),
        refusals=tuple(refusals),
        basis=_basis(len(shifts), observations, len(streams), len(refusals)),
        limitations=limitations_for(method),
    )


def _basis(shifts: int, observations: int, streams: int, refusals: int) -> str:
    """Say what the result means, in words, on every read — including none."""
    if refusals and not shifts:
        return (
            f"No change could be assessed. All {streams} subject series were too short to "
            f"analyse ({refusals} refusal(s) below, each naming the count required), so this "
            "is an absence of data rather than an absence of change."
        )
    if not shifts:
        return (
            f"No change point was detected in {observations} stored observations across "
            f"{streams} subject series. The detectors ran over the full stored history at the "
            "thresholds this response reports; this is a negative result, not an unanalysed case."
        )
    if refusals:
        return (
            f"{shifts} change point(s) detected in {observations} stored observations across "
            f"{streams} subject series. {refusals} series were too short to analyse and are "
            "listed as refusals below rather than counted as unchanged."
        )
    return (
        f"{shifts} change point(s) detected in {observations} stored observations across "
        f"{streams} subject series, every one of them long enough to analyse."
    )


GAIN_FUNCTIONS: dict[str, Callable[[Sequence[float], Sequence[float]], float]] = {
    "mean_shift_gain": mean_shift_gain,
    "ks_gain": ks_gain,
}


@router.get("/cases/{case_id}/temporal/segments", response_model=TemporalSegmentationReport)
def case_temporal_segments(
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    subject: str | None = None,
    gain: Annotated[str, Query(pattern="^(mean_shift_gain|ks_gain)$")] = "mean_shift_gain",
    bucket: Annotated[str, Query(pattern="^[0-9]+$")] = "86400",
    min_size: Annotated[int, Query(ge=1, le=60)] = 3,
    min_gain: Annotated[float | None, Query(ge=0.0)] = None,
) -> TemporalSegmentationReport:
    """Divide a subject's activity series into regimes instead of averaging it.

    One mean over seventy days describes a persona who was quiet for a month and
    busy for the next as "average", which is the one reading true of neither
    regime.  ``segment`` is the library's ``ruptures``-style binary segmentation,
    called with the requested gain function; no cut logic is reimplemented here.

    A series shorter than ``2 * min_size`` is refused with the count.  ``segment``
    would skip it, and a silent skip reads as "one regime, no change".
    """
    case = _case_or_404(db, case_id)
    span = _span(bucket)
    activity = _observations(db, case_id=case_id, channel="activity")
    if subject is not None:
        rows = [row for row in activity if row.subject_id == subject]
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No stored activity observations for subject {subject} in case {case_id}. "
                    "A subject with no rows is not a subject with no change."
                ),
            )
    else:
        rows = activity

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Case {case_id} has no stored per-subject activity series, so there is nothing "
                "to segment. This endpoint divides one actor's or one entity's activity into "
                "regimes; the case's own evidence and audit volumes are read by "
                "/cases/{case_id}/temporal/shifts instead. An absence here means no per-subject "
                "observations were collected, not that a persona was steady."
            ),
        )

    gain_function = GAIN_FUNCTIONS[gain]
    detector = "ks" if gain == "ks_gain" else "binary_segmentation"
    floor = SERVICE_MIN_GAIN[detector] if min_gain is None else min_gain
    required = segment_min_points(min_size)
    labels = _labels(db, rows)

    segmented: list[SubjectSegmentation] = []
    refusals: list[TemporalRefusal] = []
    for (subject_id, _channel), group in sorted(_grouped(rows).items()):
        kind, subject_label = _subject_label(labels, subject_id, group[0].subject_kind)
        events = [_to_event(row) for row in group]
        points = build_activity_series(events, bucket=span)
        if len(points) < required:
            refusal = _activity_refusal(
                subject_id, kind, subject_label, len(points), required, min_size
            )
            refusals.append(
                refusal.model_copy(
                    update={
                        "rule": f"segment skips any series shorter than 2 × min_size = {required}",
                        "reason": (
                            f"{len(points)} bucket(s) of activity are stored and binary "
                            f"segmentation needs 2 × {min_size} = {required} points before it "
                            "considers a cut at all. Below that the only honest answer is a "
                            "single regime, and presenting it as segmented would assert a "
                            "division nobody could check."
                        ),
                    }
                )
            )
            continue
        values = [count for _, count in points]
        cuts = segment(values, gain=gain_function, min_size=min_size, min_gain=floor)
        boundaries: list[TemporalBoundary] = []
        for index, cut_gain in cuts:
            before, after = values[:index], values[index:]
            boundaries.append(
                TemporalBoundary(
                    index=index,
                    at=points[index][0],
                    gain=round(cut_gain, 6),
                    mean_before=round(sum(before) / len(before), 6),
                    mean_after=round(sum(after) / len(after), 6),
                )
            )
        edges = [0, *(index for index, _ in cuts), len(values)]
        regimes: list[TemporalRegime] = []
        # Not `strict`: the edge list is one longer than the list of spans by
        # construction, and that is what makes the spans cover every bucket.
        for order, (start, stop) in enumerate(zip(edges, edges[1:], strict=False)):
            regime = values[start:stop]
            regimes.append(
                TemporalRegime(
                    index=order,
                    first_bucket=points[start][0],
                    last_bucket=points[stop - 1][0],
                    buckets=len(regime),
                    mean=round(sum(regime) / len(regime), 6),
                    peak=max(regime),
                    total=round(sum(regime), 6),
                )
            )
        segmented.append(
            SubjectSegmentation(
                subject_id=subject_id,
                subject_kind=kind,
                subject_label=subject_label,
                channel="activity",
                gain_function=gain,
                min_size=min_size,
                min_gain=floor,
                buckets=len(points),
                window_start=points[0][0],
                window_end=points[-1][0],
                boundaries=tuple(boundaries),
                regimes=tuple(regimes),
                limitations=limitations_for(detector),
            )
        )

    return TemporalSegmentationReport(
        case_id=case.case_id,
        generated_at=datetime.now(UTC),
        gain=gain,
        min_size=min_size,
        min_gain=floor,
        bucket=bucket,
        series=tuple(segmented),
        refusals=tuple(refusals),
        basis=(
            f"{len(segmented)} series segmented by {gain} at min_gain {floor} over {len(rows)} "
            f"stored activity observation(s)"
            + (
                f"; {len(refusals)} series were too short to segment and are listed as "
                "refusals rather than as a single regime."
                if refusals
                else "."
            )
        ),
        limitations=limitations_for(detector),
    )


# --------------------------------------------------------------------------
# Actor routes
# --------------------------------------------------------------------------


@router.get("/actors/{actor_id}/temporal/transitions", response_model=ActorTransitionReport)
def actor_marketplace_transitions(
    actor_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    min_persist: Annotated[int, Query(ge=0, le=20)] = DEFAULT_MIN_PERSIST,
) -> ActorTransitionReport:
    """Confirmed cross-marketplace moves for one registry actor.

    The second half of the marketplace capability: not "this persona was seen on
    four venues" but "this persona moved off one of them on a date, and here is
    the evidence on each side of the move".

    Detection runs on the stored sighting stream, not on the presence windows in
    ``actor_marketplaces`` — a window is two timestamps and cannot show that the
    new venue *persisted*.  The windows are returned alongside so the registry
    and the detection can be read against each other, and a disagreement between
    them is itself a finding about the data.
    """
    actor = _actor_or_404(db, actor_id)
    records = _observations(db, actor_id=actor_id, channel="marketplace")
    windows = list(
        db.scalars(
            select(ActorMarketplaceRecord)
            .where(ActorMarketplaceRecord.actor_id == actor_id)
            .order_by(ActorMarketplaceRecord.first_seen.asc().nulls_last())
        ).all()
    )
    # A marketplace sighting's venue is its `value`: the channel already says
    # which question the row answers, and a second column holding the same
    # string is a second thing that can disagree with the first.
    venues = tuple(sorted({row.value for row in records}))
    presence = tuple(
        ActorPresence(
            marketplace=row.marketplace,
            role=row.role,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            listing_count=row.listing_count,
        )
        for row in windows
    )
    required = state_min_events(min_persist)

    if len(records) < required:
        return ActorTransitionReport(
            actor_id=actor.actor_id,
            handle=actor.handle,
            generated_at=datetime.now(UTC),
            min_persist=min_persist,
            marketplaces=venues,
            presence=presence,
            refusals=(
                _state_refusal(
                    str(actor_id),
                    "actor",
                    actor.handle,
                    "marketplace",
                    len(records),
                    required,
                    min_persist,
                    "marketplace",
                ),
            ),
            basis=(
                "No transition was assessed: this actor's marketplace sighting stream is too "
                "short to confirm a move. The venues above come from the stored presence "
                "windows, which record that a venue was seen at all — not that the persona "
                "moved to it, and not that it stopped using the previous one."
            ),
            limitations=limitations_for("state_change"),
        )

    events = [_to_event(row) for row in records]
    transitions = [
        _shift(
            change,
            case_id=None,
            subject_kind="actor",
            subject_label=actor.handle,
            channel="marketplace",
            events=events,
            series=(),
        )
        for change in detect_marketplace_transitions(events, min_persist=min_persist)
    ]
    return ActorTransitionReport(
        actor_id=actor.actor_id,
        handle=actor.handle,
        generated_at=datetime.now(UTC),
        min_persist=min_persist,
        marketplaces=venues,
        presence=presence,
        window_start=min(row.observed_at for row in records),
        window_end=max(row.observed_at for row in records),
        transitions=tuple(transitions),
        basis=(
            f"{len(transitions)} confirmed transition(s) across {len(venues)} venue(s) in "
            f"{len(records)} stored sighting(s)."
            if transitions
            else (
                f"No transition confirmed across {len(venues)} venue(s) in {len(records)} "
                "stored sighting(s). The persistence rule ran over the whole stream, so a "
                "venue the actor returned to would not be reported as a move, and a move at "
                "the very end of the stream is dropped for want of a confirmation window."
            )
        ),
        limitations=limitations_for("state_change"),
    )


@router.get("/actors/{actor_id}/temporal/behaviour", response_model=ActorBehaviourReport)
def actor_behaviour_series(
    actor_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    bucket: Annotated[str, Query(pattern="^[0-9]+$")] = "86400",
    min_size: Annotated[int, Query(ge=1, le=60)] = 3,
) -> ActorBehaviourReport:
    """One actor's activity series, chartable, with the analysis bandwidth stated.

    This series is the substrate ``cusum`` and ``ks`` are run over, so the
    response declares the width each of them needs rather than leaving a caller
    to discover it by getting a silently empty result.  Below that width
    ``analysable`` is false, the points are still returned — they are what the
    analyst has — and ``refusal`` states exactly what is missing.
    """
    actor = _actor_or_404(db, actor_id)
    span = _span(bucket)
    records = _observations(db, actor_id=actor_id, channel="activity")
    points = (
        build_activity_series([_to_event(row) for row in records], bucket=span) if records else ()
    )
    values = [count for _, count in points]
    required = activity_min_buckets(min_size)
    mean = (sum(values) / len(values)) if values else None
    variance = (
        sum((value - mean) ** 2 for value in values) / len(values)
        if mean is not None
        else None
    )

    refusal: TemporalRefusal | None = None
    if len(points) < required:
        refusal = _activity_refusal(
            str(actor_id), "actor", actor.handle, len(points), required, min_size
        )

    return ActorBehaviourReport(
        actor_id=actor.actor_id,
        handle=actor.handle,
        generated_at=datetime.now(UTC),
        channel="activity",
        bucket=bucket,
        points=tuple(
            BehaviourPoint(at=at, events=int(count), magnitude=count) for at, count in points
        ),
        buckets=len(points),
        observations=len(records),
        window_start=points[0][0] if points else None,
        window_end=points[-1][0] if points else None,
        mean=round(mean, 6) if mean is not None else None,
        standard_deviation=round(math.sqrt(variance), 6) if variance is not None else None,
        peak=max(values) if values else None,
        silent_buckets=sum(1 for value in values if value == 0.0),
        analysable=refusal is None,
        refusal=refusal,
        bandwidth=Bandwidth(
            cusum=AlgorithmBandwidth(
                algorithm="cusum",
                min_points=activity_min_buckets(3),
                note=(
                    "cusum() itself accepts 2 values, but the detector around it claims "
                    "nothing below 6 buckets, and it references the series mean — so a "
                    "baseline that already contains the change moves with it."
                ),
            ),
            ks=AlgorithmBandwidth(
                algorithm="ks",
                min_points=max(required, 2 * min_size),
                note=(
                    "ks_distance() needs one point per sample to return a number, and "
                    f"segment() will not cut a series below 2 × min_size = {2 * min_size}. A "
                    "KS statistic over three points is a number, not a distribution "
                    "difference, which is why this surface refuses rather than reports it."
                ),
            ),
            binary_segmentation=AlgorithmBandwidth(
                algorithm="binary_segmentation",
                min_points=segment_min_points(min_size),
                note=(
                    "Greedy two-pass segmentation. Deterministic, and not guaranteed to be "
                    "the best partition: strict improvement is required and the first cut "
                    "wins ties."
                ),
            ),
        ),
        limitations=limitations_for("binary_segmentation"),
    )


__all__ = [
    "CHANNEL_KINDS",
    "COMMON_LIMITATIONS",
    "DETECTOR_LIMITATIONS",
    "SERVICE_MIN_GAIN",
    "activity_min_buckets",
    "limitations_for",
    "router",
    "segment_min_points",
    "state_min_events",
]
