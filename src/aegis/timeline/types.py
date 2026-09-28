"""Timeline and change-detection objects (Phase 15).

The plan's three objects:

* :class:`TimelineEvent` — one timestamped state/observation for a
  subject (its current handle, marketplace, identifier set entry,
  infrastructure, or an activity tick), carrying an event kind that
  doubles as the detection channel.
* :class:`ChangePoint` — a detected change: when it happened, which
  channel, which detector found it, its score, direction for numeric
  series, and ``from_value``/``to_value`` for categorical state
  changes.
* :class:`MigrationCandidate` — a subject's move from an origin value
  to a destination value (marketplace transition, infrastructure
  change, handle move, identifier rotation) with the supporting
  change point, a data-derived confidence, and the basis that
  produced it.

Evidence traceability
---------------------
Every runtime timeline output must be traceable back to immutable
evidence through ``evidence_ids`` (ids of records in the evidence
ledger — never the content itself):

* :class:`TimelineEvent` **requires** a non-empty ``evidence_ids``
  tuple: an observation that cannot cite its evidence is not admitted.
  Every id must be a non-empty, stripped string.
* :class:`ChangePoint` and :class:`MigrationCandidate` have
  ``evidence_ids`` default to ``()`` — these are *derived* fields the
  detectors fill in with the union of the evidence behind the claim
  (the change event plus its persistence confirmations for state
  changes, the events in the fired bucket for activity shifts, the
  supporting change point's evidence for migration candidates).
  Detector propagation deduplicates **preserving first-seen order**
  (chronological event order, then id order within an event) so the
  citation sequence is deterministic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from aegis.graph import ensure_aware


class TimelineEventKind(StrEnum):
    """The five detection channels the plan requires."""

    HANDLE = "handle"
    ACTIVITY = "activity"
    MARKETPLACE = "marketplace"
    IDENTIFIER = "identifier"
    INFRASTRUCTURE = "infrastructure"


#: Categorical channels (state can be compared for equality) — activity
#: is the numeric channel (event counts per time bucket).
CATEGORICAL_KINDS: frozenset[TimelineEventKind] = frozenset(
    {
        TimelineEventKind.HANDLE,
        TimelineEventKind.MARKETPLACE,
        TimelineEventKind.IDENTIFIER,
        TimelineEventKind.INFRASTRUCTURE,
    }
)


class Direction(StrEnum):
    """Numeric change direction."""

    INCREASE = "increase"
    DECREASE = "decrease"


def _validate_evidence_ids(evidence_ids: tuple[str, ...], *, field: str) -> None:
    """Every cited evidence id must be a non-empty, stripped string."""
    for evidence_id in evidence_ids:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError(f"{field} entries must be non-empty strings, got {evidence_id!r}")


@dataclass(frozen=True)
class TimelineEvent:
    """One observation of a subject on one channel at one time.

    ``evidence_ids`` is required and non-empty: an event that cannot
    cite the immutable evidence it derives from is rejected in
    ``__post_init__`` — traceability is the invariant, not a nicety.
    """

    event_id: str
    subject_id: str
    kind: TimelineEventKind
    observed_at: datetime
    value: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must be non-empty")
        if not self.subject_id.strip():
            raise ValueError("subject_id must be non-empty")
        if not self.value.strip():
            raise ValueError("value must be non-empty")
        if not self.evidence_ids:
            raise ValueError("evidence_ids must be non-empty")
        _validate_evidence_ids(self.evidence_ids, field="evidence_ids")
        ensure_aware(self.observed_at, field_name="observed_at")


@dataclass(frozen=True)
class ChangePoint:
    """A detected change on one channel of one subject.

    ``detector`` records how it was found (``state_change`` for
    categorical persistence, ``cusum`` / ``ks`` / ``binary_segmentation``
    for numeric activity series); ``score`` is the detector's native
    evidence (alarm magnitude, KS statistic, split improvement — 1.0
    for confirmed state changes).
    """

    change_id: str
    subject_id: str
    kind: TimelineEventKind
    detector: str
    changed_at: datetime
    score: float
    direction: Direction | None = None
    from_value: str | None = None
    to_value: str | None = None
    #: Derived: the union of the evidence ids justifying this claim —
    #: change + confirmation events for state changes, events in the
    #: fired bucket for activity shifts.  Defaults to ``()``; detectors
    #: propagate it (first-seen dedupe order).
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.change_id.strip():
            raise ValueError("change_id must be non-empty")
        if not self.subject_id.strip():
            raise ValueError("subject_id must be non-empty")
        if not self.detector.strip():
            raise ValueError("detector must be non-empty")
        if not math.isfinite(self.score) or self.score < 0.0:
            raise ValueError("score must be finite and >= 0")
        _validate_evidence_ids(self.evidence_ids, field="evidence_ids")
        ensure_aware(self.changed_at, field_name="changed_at")

        categorical = self.from_value is not None or self.to_value is not None
        if categorical:
            if not self.from_value or not self.to_value:
                raise ValueError("from_value and to_value must be provided together")
            if self.from_value == self.to_value:
                raise ValueError("from_value and to_value must differ")
            if self.direction is not None:
                raise ValueError("categorical change points carry no direction")
        elif self.direction is None and self.kind is TimelineEventKind.ACTIVITY:
            raise ValueError("numeric activity change points require a direction")


@dataclass(frozen=True)
class MigrationCandidate:
    """A subject's move from an origin value to a destination value.

    ``confidence`` is data-derived (not asserted): the fraction of the
    subject's later events on the same channel that still show the
    destination value.  ``basis`` states the detector and persistence
    rule that produced it — provenance for downstream fusion.
    """

    candidate_id: str
    subject_id: str
    kind: TimelineEventKind
    origin: str
    destination: str
    changed_at: datetime
    confidence: float
    supporting_change_points: tuple[str, ...]
    basis: str
    #: Derived: the supporting change point's evidence ids — a
    #: migration's citation trail is exactly the change evidence that
    #: justified it.  Defaults to ``()``.
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        if not self.subject_id.strip():
            raise ValueError("subject_id must be non-empty")
        if not self.origin.strip() or not self.destination.strip():
            raise ValueError("origin and destination must be non-empty")
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        if not self.supporting_change_points:
            raise ValueError("a migration candidate needs supporting change points")
        if any(not cp.strip() for cp in self.supporting_change_points):
            raise ValueError("supporting change point ids must be non-empty")
        if not self.basis.strip():
            raise ValueError("basis must be non-empty")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        _validate_evidence_ids(self.evidence_ids, field="evidence_ids")
        ensure_aware(self.changed_at, field_name="changed_at")
