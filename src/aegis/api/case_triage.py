"""Shared helpers for the case-triage fields added in migration 0004.

Kept in its own module because both ``live.py`` and ``workspace.py`` need
it, and importing either from the other (or from ``app.py``, which mounts
both routers) would create an import cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aegis.db.models import CaseRecord

#: Statuses that end active work. A case in one of these is never counted as
#: breaching an SLA, even if a stale ``sla_due_at`` is still stored on it.
TERMINAL_STATUSES = frozenset({"closed", "archived"})


def case_is_overdue(record: CaseRecord, *, now: datetime | None = None) -> bool:
    """True when a case with a live SLA deadline has passed it.

    Keyed on ``closed_at`` rather than ``status`` alone so that a case
    closed and later re-opened is judged on its real closure state rather
    than on a stale status string.

    ``now`` is injectable so tests do not depend on wall-clock timing.
    """
    if record.sla_due_at is None:
        return False
    if record.closed_at is not None or record.status in TERMINAL_STATUSES:
        return False
    reference = now if now is not None else datetime.now(UTC)
    return record.sla_due_at < reference
