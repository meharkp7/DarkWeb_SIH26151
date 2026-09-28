"""Historical change detection over observed infrastructure metadata (Phase 13).

Implementation Plan section 14 lists *historical changes* as one of the
six passive feature families: the change of already-observed metadata
over time (certificate rotation, header or technology change, TLS
configuration change) — never the active re-fetching of anything.

For each subject, consecutive observations (ordered by their window
start, then window end, then observation id) are compared field by
field; every field that both observations recorded *and* that differs
yields one :class:`~aegis.infrastructure.types.HistoricalChange`.  The
change ``window`` is the interval bounded by the previous observation
window's end and the next observation window's start (their overlap
when the windows intersect): the change provably happened somewhere in
there, and the exact moment is disclosed as a limitation instead of
being invented.  Fields absent from either side are skipped — a first
appearance is missing data, not a change — and body content is
deliberately not tracked, because page text changes far more often than
infrastructure and would drown the signal.

Output is a single tuple ordered by (window start, window end, subject,
field), so callers can append it straight to a timeline.  Detection is
pure comparison over stored observations: no network I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256

from aegis.infrastructure.types import (
    ChangeKind,
    HistoricalChange,
    InfrastructureObservation,
    InfrastructureValidationError,
    TimeRange,
)

#: Tracked fields, in output order within one observation pair: payload
#: path -> (change kind, value extractor).
_FIELD_KINDS: dict[str, ChangeKind] = {
    "certificate.fingerprint_sha256": ChangeKind.CERTIFICATE_ROTATION,
    "http.content_type": ChangeKind.HEADER_CHANGE,
    "http.header_names": ChangeKind.HEADER_CHANGE,
    "http.server": ChangeKind.HEADER_CHANGE,
    "technologies": ChangeKind.TECHNOLOGY_CHANGE,
    "tls.version": ChangeKind.TLS_CHANGE,
}

_LIMITATIONS: tuple[str, ...] = (
    "The change is bounded by the two observation windows; its exact time within "
    "that window is unknown from passive observation.",
    "Detected from stored metadata only: no intrusive origin discovery, scanning, "
    "or probing was performed (Implementation Plan section 14).",
    "A change in observed metadata does not by itself establish a change of "
    "operator, ownership, or control.",
)


def _tracked_values(observation: InfrastructureObservation) -> dict[str, str]:
    """Comparable snapshot of the fields this phase tracks over time."""
    values: dict[str, str] = {}
    certificate = observation.certificate
    if certificate is not None:
        values["certificate.fingerprint_sha256"] = certificate.fingerprint_sha256
    http = observation.http
    if http is not None:
        if http.server is not None:
            values["http.server"] = http.server
        if http.content_type is not None:
            values["http.content_type"] = http.content_type
        values["http.header_names"] = ",".join(sorted(http.header_names))
    if observation.technologies:
        values["technologies"] = ",".join(technology.key for technology in observation.technologies)
    tls = observation.tls
    if tls is not None:
        values["tls.version"] = tls.version
    return values


def _transition_window(previous: TimeRange, following: TimeRange) -> TimeRange:
    """Interval bounded by the previous window's end and the next window's start."""
    return TimeRange(
        min(previous.end, following.start),
        max(previous.end, following.start),
    )


def _change_id(
    subject: str,
    field: str,
    window: TimeRange,
    previous_id: str,
    following_id: str,
) -> str:
    """Deterministic identity for one detected change (graph edge-key style)."""
    material = (
        f"{subject}|{field}|{window.start.isoformat()}|{window.end.isoformat()}"
        f"|{previous_id}|{following_id}"
    )
    return sha256(material.encode("utf-8")).hexdigest()[:16]


def detect_changes(
    observations: Sequence[InfrastructureObservation],
) -> tuple[HistoricalChange, ...]:
    """Ordered historical changes across all subjects.

    Accepts observations in any order; the result is deterministic for a
    given set.  Duplicate observation ids fail loudly — they would make
    the ordering (and therefore the change windows) ambiguous.
    """
    ids = [observation.observation_id for observation in observations]
    if len(set(ids)) != len(ids):
        duplicates = sorted({oid for oid in ids if ids.count(oid) > 1})
        raise InfrastructureValidationError(f"duplicate observation ids: {', '.join(duplicates)}")
    by_subject: dict[str, list[InfrastructureObservation]] = {}
    for observation in observations:
        by_subject.setdefault(observation.subject, []).append(observation)

    changes: list[HistoricalChange] = []
    for subject, group in by_subject.items():
        ordered = sorted(
            group,
            key=lambda item: (
                item.observed_range.start,
                item.observed_range.end,
                item.observation_id,
            ),
        )
        for previous, following in zip(ordered[:-1], ordered[1:], strict=True):
            _collect_pair_changes(previous, following, subject, changes)
    changes.sort(
        key=lambda change: (
            change.window.start,
            change.window.end,
            change.subject,
            change.field,
        )
    )
    return tuple(changes)


def _collect_pair_changes(
    previous: InfrastructureObservation,
    following: InfrastructureObservation,
    subject: str,
    changes: list[HistoricalChange],
) -> None:
    old_values = _tracked_values(previous)
    new_values = _tracked_values(following)
    window = _transition_window(previous.observed_range, following.observed_range)
    for field in sorted(old_values.keys() & new_values.keys()):
        old_value = old_values[field]
        new_value = new_values[field]
        if old_value == new_value:
            continue
        evidence_ids = tuple(sorted(set(previous.evidence_ids) | set(following.evidence_ids)))
        sources = tuple(sorted({previous.source, following.source}))
        changes.append(
            HistoricalChange(
                change_id=_change_id(
                    subject, field, window, previous.observation_id, following.observation_id
                ),
                subject=subject,
                field=field,
                kind=_FIELD_KINDS[field],
                old_value=old_value,
                new_value=new_value,
                window=window,
                evidence_ids=evidence_ids,
                sources=sources,
                limitations=_LIMITATIONS,
            )
        )
