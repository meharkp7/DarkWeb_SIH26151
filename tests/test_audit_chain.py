"""Audit hash-chain integrity (Phase 03).

The chain is the tamper-evidence guarantee, so these tests pin the exact
canonicalization rules it depends on. The regression that motivated this
file: ``compute_entry_hash`` used ``occurred_at.isoformat()`` directly, and
Postgres returns ``TIMESTAMPTZ`` in the session's timezone. A row written as
``...+00:00`` therefore read back as ``...+05:30`` on a host in IST, the
recomputed hash differed, and ``verify_chain`` reported tampering for every
entry on any non-UTC host.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aegis.db.audit import canonical_json, compute_entry_hash

PAYLOAD = {"count": 3, "marker": "loadtest", "nested": {"b": 1, "a": 2}}


def test_hash_is_stable_across_timezone_representations() -> None:
    """The same instant must hash identically in any zone.

    This is the regression: hashing the raw isoformat made the chain
    unverifiable on any host whose Postgres session is not UTC.
    """
    utc = datetime(2026, 9, 29, 13, 26, 19, 112754, tzinfo=UTC)
    ist = utc.astimezone(ZoneInfo("Asia/Kolkata"))
    other = utc.astimezone(ZoneInfo("America/New_York"))

    # Same instant, three very different strings.
    assert utc.isoformat() != ist.isoformat()
    assert ist.isoformat() != other.isoformat()
    assert utc == ist == other

    hashes = {
        compute_entry_hash(None, moment, "source.created", "source", "id-1", PAYLOAD)
        for moment in (utc, ist, other)
    }
    assert len(hashes) == 1, "same instant hashed differently across timezones"


def test_naive_datetime_is_treated_as_utc() -> None:
    """A naive value is placed at UTC rather than shifted by the host zone."""
    naive = datetime(2026, 9, 29, 13, 26, 19, 112754)
    aware = compute_entry_hash(None, naive, "a", "e", "i", PAYLOAD)
    assert aware == compute_entry_hash(None, naive.replace(tzinfo=UTC), "a", "e", "i", PAYLOAD)


def test_chain_links_each_entry_to_its_predecessor() -> None:
    """A three-link chain verifies when each hash is folded in as prev_hash."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    entries = [("created", "case"), ("updated", "case"), ("closed", "case")]

    prev: str | None = None
    stored: list[tuple[str | None, str]] = []
    for offset, (action, entity) in enumerate(entries):
        digest = compute_entry_hash(
            prev, t0 + timedelta(minutes=offset), action, entity, "case-1", {"i": offset}
        )
        stored.append((prev, digest))
        prev = digest

    # Re-verify the way verify_chain does, reading the timestamp back in a
    # different zone to mimic the database round-trip.
    previous: str | None = None
    for offset, (action, entity) in enumerate(entries):
        reread = (t0 + timedelta(minutes=offset)).astimezone(ZoneInfo("Asia/Kolkata"))
        expected = compute_entry_hash(previous, reread, action, entity, "case-1", {"i": offset})
        assert stored[offset] == (previous, expected)
        previous = expected


def test_tampering_with_a_payload_breaks_the_chain() -> None:
    """The guarantee only means something if modification is detectable."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    first = compute_entry_hash(None, t0, "created", "case", "c1", {"amount": 10})
    honest = compute_entry_hash(first, t0, "closed", "case", "c1", {"reason": "done"})
    tampered = compute_entry_hash(first, t0, "closed", "case", "c1", {"reason": "nope"})

    assert honest != tampered


def test_canonical_json_is_key_order_independent() -> None:
    """Payload hashing must not depend on dict insertion order."""
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})
