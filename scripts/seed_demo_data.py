"""Seed a coherent, deterministic AEGIS demonstration dataset.

Every record is synthetic and labelled as such in its own metadata. The script
performs no network collection and asserts no real-world attribution.

Why this exists in the shape it does
------------------------------------
Every console surface is only meaningful when its numbers come from one
relationally consistent world. A seeder that scatters independent random rows
produces a dashboard that is full and an investigation that is incoherent:
entities referencing evidence nobody collected, hypotheses with no
assessments, and "live" activity events tied to nothing.

So the dataset is built in strict foreign-key order, and each stage consumes
the identifiers the previous stage produced:

    roles -> users -> sources -> cases -> artifacts -> evidence
          -> entities -> relationships -> hypotheses -> hypothesis_links
          -> assessments -> audit trail

Entities are generated *from* actors, evidence is generated *on* those
entities, relationships and hypotheses reference real entities, and every audit
event names a real case. The console then shows one story rather than one
number per screen.

Stage order is a hard requirement, not a style choice. SQLAlchemy orders a unit
of work by table dependency, but only for rows it has already seen, and a
demonstration seeder that fails halfway leaves a database that is neither the
old dataset nor the new one. Each stage is flushed before the next one needs
its identifiers, so a violation surfaces at the stage that caused it.

Usage
-----
    uv run python scripts/seed_demo_data.py
    uv run python scripts/seed_demo_data.py --reset
    uv run python scripts/seed_demo_data.py --evidence-per-case 800 --index
"""

from __future__ import annotations

import argparse
import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from aegis.api.security import hash_password
from aegis.db.audit import AuditService
from aegis.db.models import (
    ActorIdentifierRecord,
    ActorMarketplaceRecord,
    ActorRecord,
    ArtifactRecord,
    AssessmentRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    HypothesisLinkRecord,
    HypothesisRecord,
    PersonaLinkageRecord,
    RelationshipRecord,
    RoleRecord,
    SourceRecord,
    UserRecord,
)
from aegis.db.session import SessionLocal
from aegis.evidence.search_index import EvidenceSearchIndexer
from aegis.search.opensearch import OpenSearchAdapter
from aegis.settings import settings

NAMESPACE = UUID("4b5a6c7d-8e9f-4012-9345-5a6b7c8d9e01")
SCHEMA_VERSION = "aegis-demo/3"

#: Rows inserted per statement. Bounded so a failure reports the offending
#: batch instead of a 4,000-parameter statement that Postgres will reject on
#: arity alone.
BATCH = 400

#: Tables owned by this seeder, child-first so ``TRUNCATE`` never has to lean
#: on ``CASCADE`` to satisfy a foreign key. The actor registry, the Tor
#: infrastructure tables and persona linkages are truncated here because the
#: registry shares its ``sources`` and ``cases`` foreign keys with the rest of
#: the dataset: leaving them behind would leave actors pointing at sources a
#: reset has already removed.
DEMO_TABLES: tuple[str, ...] = (
    "persona_linkages",
    "infrastructure_matches",
    "infrastructure_findings",
    "infrastructure_observations",
    "actor_marketplaces",
    "actor_identifiers",
    "actors",
    "hypothesis_links",
    "assessments",
    "hypotheses",
    "relationships",
    "entities",
    "evidence_derivations",
    "evidence",
    "case_notes",
    "audit_logs",
    "artifacts",
    "cases",
    "sources",
    "users",
    "roles",
)


@dataclass(frozen=True)
class CaseBlueprint:
    """Everything that distinguishes one investigation from another."""

    slug: str
    name: str
    description: str
    status: str
    priority: str
    severity: str
    tags: tuple[str, ...]
    sla_hours: float
    actor_count: int
    #: Modality weights drive which evidence each actor accumulates, so the
    #: financial case is genuinely wallet-heavy and the stylometry case
    #: genuinely leans on documents.
    modality_weights: dict[str, float]
    owner_role: str


CASE_BLUEPRINTS: tuple[CaseBlueprint, ...] = (
    CaseBlueprint(
        slug="blackbird",
        name="Operation Blackbird",
        description=(
            "Attribution-led investigation correlating a threat actor's reused "
            "infrastructure with a concurrent financial cluster; synthetic."
        ),
        status="active",
        priority="critical",
        severity="critical",
        tags=("attribution", "infrastructure", "financial"),
        sla_hours=5.0,
        actor_count=14,
        modality_weights={
            "infrastructure": 0.34,
            "financial": 0.28,
            "behavioral": 0.18,
            "stylometry": 0.12,
            "temporal": 0.08,
        },
        owner_role="lead_analyst",
    ),
    CaseBlueprint(
        slug="lantern",
        name="Silver Lantern",
        description=(
            "Marketplace listings correlated with forum handles across two "
            "independent source groups; synthetic."
        ),
        status="active",
        priority="high",
        severity="high",
        tags=("infrastructure", "marketplace"),
        sla_hours=26.0,
        actor_count=11,
        modality_weights={
            "infrastructure": 0.30,
            "behavioral": 0.26,
            "financial": 0.18,
            "temporal": 0.16,
            "stylometry": 0.10,
        },
        owner_role="analyst",
    ),
    CaseBlueprint(
        slug="northstar",
        name="Northstar",
        description=(
            "Cryptocurrency laundering chain; wallet convergence and mixer "
            "round-trips under a synthetic cluster model."
        ),
        status="active",
        priority="high",
        severity="high",
        tags=("financial", "behavioral"),
        sla_hours=44.0,
        actor_count=12,
        modality_weights={
            "financial": 0.46,
            "infrastructure": 0.20,
            "behavioral": 0.14,
            "temporal": 0.12,
            "stylometry": 0.08,
        },
        owner_role="analyst",
    ),
    CaseBlueprint(
        slug="nightfall",
        name="Operation Nightfall",
        description=(
            "Multi-platform ransomware ecosystem; affiliate onboarding and "
            "payment negotiation traces. Synthetic training scenario."
        ),
        status="active",
        priority="critical",
        severity="critical",
        tags=("ransomware", "attribution"),
        sla_hours=11.0,
        actor_count=13,
        modality_weights={
            "behavioral": 0.32,
            "infrastructure": 0.26,
            "financial": 0.22,
            "stylometry": 0.10,
            "temporal": 0.10,
        },
        owner_role="reviewer",
    ),
    CaseBlueprint(
        slug="copper-trace",
        name="Copper Trace",
        description=(
            "Deliberately contradictory case: two well-sourced but mutually "
            "exclusive accounts of the same operator. Synthetic."
        ),
        status="open",
        priority="medium",
        severity="medium",
        tags=("contradiction", "stylometry"),
        sla_hours=96.0,
        actor_count=9,
        modality_weights={
            "stylometry": 0.34,
            "behavioral": 0.24,
            "temporal": 0.20,
            "infrastructure": 0.14,
            "financial": 0.08,
        },
        owner_role="analyst",
    ),
    CaseBlueprint(
        slug="harbor",
        name="Glass Harbor",
        description=(
            "Forum identity resolution under a rotating-identifier pattern; "
            "temporal behaviour bounds the candidate set. Synthetic."
        ),
        status="on_hold",
        priority="low",
        severity="medium",
        tags=("temporal", "behavioral"),
        sla_hours=180.0,
        actor_count=8,
        modality_weights={
            "temporal": 0.34,
            "behavioral": 0.28,
            "infrastructure": 0.18,
            "stylometry": 0.12,
            "financial": 0.08,
        },
        owner_role="analyst",
    ),
    CaseBlueprint(
        slug="tidewater",
        name="Tidewater Corridor",
        description=(
            "Credential-stuffing campaign traced through shared residential "
            "proxy infrastructure. Synthetic."
        ),
        status="open",
        priority="medium",
        severity="medium",
        tags=("infrastructure", "temporal"),
        sla_hours=120.0,
        actor_count=10,
        modality_weights={
            "infrastructure": 0.38,
            "temporal": 0.24,
            "behavioral": 0.20,
            "financial": 0.10,
            "stylometry": 0.08,
        },
        owner_role="lead_analyst",
    ),
)

ROLE_BLUEPRINTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "administrator",
        "Full platform administration, including team and audit surfaces.",
        (
            "cases:read",
            "cases:write",
            "evidence:read",
            "evidence:write",
            "reports:read",
            "reports:export",
            "admin:team",
            "admin:audit",
            "admin:system",
            "copilot:query",
        ),
    ),
    (
        "lead_analyst",
        "Senior analyst; owns investigations and signs off assessments.",
        (
            "cases:read",
            "cases:write",
            "evidence:read",
            "evidence:write",
            "reports:read",
            "reports:export",
            "copilot:query",
        ),
    ),
    (
        "analyst",
        "Investigator; works cases and files evidence.",
        ("cases:read", "cases:write", "evidence:read", "evidence:write", "copilot:query"),
    ),
    (
        "reviewer",
        "Read-only reviewer with report export rights.",
        ("cases:read", "evidence:read", "reports:read", "reports:export"),
    ),
)

ANALYST_BLUEPRINTS: tuple[tuple[str, str, str], ...] = (
    ("lead@aegis.intel", "Mehar Kapoor", "lead_analyst"),
    ("r.singh@aegis.intel", "Rhea Singh", "analyst"),
    ("a.kaur@aegis.intel", "Amrit Kaur", "analyst"),
    ("j.oyelaran@aegis.intel", "Jide Oyelaran", "analyst"),
    ("t.novak@aegis.intel", "Tereza Novak", "reviewer"),
    ("ops@aegis.intel", "Platform Operations", "administrator"),
)

SOURCE_BLUEPRINTS: tuple[tuple[str, str, float, str], ...] = (
    ("forum", "Synthetic Forum Archive", 0.86, "group-alpha"),
    ("marketplace", "Synthetic Marketplace Mirror", 0.79, "group-alpha"),
    ("threat_feed", "Synthetic Threat Feed", 0.91, "group-beta"),
    ("public_web", "Synthetic Public Web Corpus", 0.74, "group-gamma"),
    ("analyst_submitted", "Synthetic Analyst Submission", 0.88, "group-delta"),
    ("synthetic", "Synthetic Controlled Corpus", 0.95, "group-epsilon"),
)

#: Entity types in network-view layout order. Actor first, so an attribution
#: reads left to right.
ENTITY_ORDER: tuple[str, ...] = (
    "actor",
    "alias",
    "account",
    "domain",
    "ip",
    "wallet",
    "marketplace",
    "document",
    "infrastructure",
)

#: Relationship vocabulary aligned with the canonical entity/relationship
#: registry rather than invented per screen.
RELATIONSHIP_TYPES: tuple[str, ...] = (
    "controls",
    "uses",
    "authored",
    "transacted",
    "hosted",
    "resolved-to",
    "associated-with",
    "derived-from",
)

MODALITIES: tuple[str, ...] = (
    "behavioral",
    "infrastructure",
    "financial",
    "stylometry",
    "temporal",
)

#: Modality -> the entity type its evidence is normally observed on. Keeps the
#: evidence ledger and the network telling the same story.
MODALITY_ENTITY: dict[str, str] = {
    "behavioral": "account",
    "infrastructure": "domain",
    "financial": "wallet",
    "stylometry": "document",
    "temporal": "actor",
}

HYPOTHESIS_KINDS: tuple[str, ...] = (
    "attribution",
    "infrastructure",
    "financial",
    "coordinated",
)

#: Audit actions the dashboard analytics actually read. Emitting anything else
#: would leave the pressure and alert counters structurally zero.
THREAT_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    ("relationship.updated", "infrastructure", "New infrastructure association detected"),
    ("entity.extracted", "infrastructure", "Entity resolved against the case graph"),
    ("evidence.created", "event", "New evidence ingested"),
    ("assessment.updated", "actor", "Attribution confidence revised"),
    ("alert.critical", "event", "Critical queue escalation"),
    ("threat.infrastructure", "infrastructure", "Infrastructure link surfaced"),
    ("threat.financial", "financial", "Financial movement correlated"),
    ("threat.attribution", "actor", "Hypothesis support shifted"),
    ("evidence.contradicted", "event", "Contradicting evidence recorded"),
    ("case.note_added", "event", "Analyst note filed"),
)

HANDLES = (
    "nightjar",
    "quietpine",
    "redkite",
    "hollowbay",
    "sablefox",
    "ironmoss",
    "duskraven",
    "paleot",
    "glasscoil",
    "thornfield",
    "ashvane",
    "bramble",
)
PLATFORMS = ("forum-a", "forum-b", "market-x", "chat-c", "paste-r")
DOMAINS = ("shadowcdn", "fastnode", "quietrelay", "nordhost", "vpnmesh", "relay7")
WALLET_PREFIXES = ("1Aegis", "1Demo", "3Synthetic", "bc1qdemo")
DOC_KINDS = ("ransom-note", "listing-copy", "chat-transcript", "readme", "invoice")

#: Confidence envelope per hypothesis rank, so the competing-hypotheses view
#: always has a clear leader and a plausible tail.
CONFIDENCE_ENVELOPES: tuple[tuple[float, float], ...] = (
    (0.55, 0.86),
    (0.34, 0.58),
    (0.18, 0.41),
    (0.07, 0.29),
)

#: Audit events written per case. Enough to fill a 45-day window several
#: times over, so the timeline and Threat Watch are not near-empty.
EVENTS_PER_CASE = 72

# --------------------------------------------------------------------------
# Actor registry
#
# The problem statement's central deliverable. The categories are the ones it
# names; the handles, keys, wallets and onion addresses are synthetic values in
# reserved or example namespaces and resolve to nobody.
# --------------------------------------------------------------------------

#: Categories from the problem statement, in the order it lists them.
ACTOR_CATEGORIES: tuple[str, ...] = (
    "drugs",
    "arms",
    "stolen data",
    "hacking services",
    "money laundering",
    "terror financing",
    "extortion",
    "fraud",
)

#: Weighted rather than uniform: an active registry is mostly active actors, and
#: a flat draw would show a third of the world as retired, which is not a
#: plausible shape for a working register.
ACTOR_STATUS_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("active", 0.44),
    ("dormant", 0.20),
    ("rebranded", 0.15),
    ("retired", 0.13),
    ("unknown", 0.08),
)

#: Identifier kinds. Every actor carries a `handle` plus a sample of the rest,
#: so the kind glyphs in the register row are never a single repeated letter.
ACTOR_IDENTIFIER_KINDS: tuple[str, ...] = (
    "handle",
    "pgp",
    "wallet",
    "onion",
    "clearnet",
    "jabber",
)

ACTOR_HANDLE_HEADS: tuple[str, ...] = (
    "nightjar",
    "quietpine",
    "redkite",
    "hollowbay",
    "sablefox",
    "ironmoss",
    "duskraven",
    "paleot",
    "glasscoil",
    "thornfield",
    "ashvane",
    "bramble",
    "cinderwolf",
    "vellumark",
    "saltmarsh",
    "greythistle",
    "coldharbor",
    "amberlight",
    "foxglove",
    "winterknot",
)

ACTOR_HANDLE_TAILS: tuple[str, ...] = (
    "unit",
    "collective",
    "shop",
    "desk",
    "supply",
    "network",
    "guild",
    "exchange",
    "works",
    "cell",
    "depot",
    "service",
)

ACTOR_HANDLE_SEPARATORS: tuple[str, ...] = ("", "", "", "_", "-", ".", "1", "7", "99")

#: Synthetic venues. `.example` is IANA-reserved for documentation, so none of
#: these names can resolve to a real marketplace.
ACTOR_MARKETPLACES: tuple[str, ...] = (
    "silkweave.market.example",
    "nightcart.market.example",
    "greenledger.market.example",
    "coldharbor.market.example",
    "quietbazaar.market.example",
    "ironforge.market.example",
    "vialmarket.market.example",
    "lowtide.market.example",
)

#: Roles a persona holds on a venue, weighted towards vendor.
ACTOR_MARKETPLACE_ROLES: tuple[tuple[str, float], ...] = (
    ("vendor", 0.52),
    ("broker", 0.22),
    ("buyer", 0.14),
    ("operator", 0.08),
    ("escrow", 0.04),
)

#: Alphabets for the synthetic identifier values. Onion addresses are v3 base32
#: (56 characters), the wallets are base58 / hex, and a PGP body is base64 —
#: getting these right is what makes the demo registry look like a registry
#: rather than like random strings in the right column.
_ONION_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_HEX_ALPHABET = "0123456789abcdef"
_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

#: Registries per identifier stage, so a re-seed reproduces the same registry.
ACTOR_MIN = 40
ACTOR_MAX = 60


def _weighted(rng: random.Random, weights: tuple[tuple[str, float], ...]) -> str:
    """Pick one label from a cumulative-weight table."""
    draw = rng.random()
    cumulative = 0.0
    for label, weight in weights:
        cumulative += weight
        if draw <= cumulative:
            return label
    return weights[-1][0]


def _onion(rng: random.Random) -> str:
    return "".join(rng.choice(_ONION_ALPHABET) for _ in range(56))


def _wallet(rng: random.Random) -> str:
    """A base58 UTXO-style address or a hex account, in the shape each uses."""
    if rng.random() < 0.6:
        prefix = rng.choice(("1", "3"))
        return prefix + "".join(rng.choice(_BASE58_ALPHABET) for _ in range(33))
    return "0x" + "".join(rng.choice(_HEX_ALPHABET) for _ in range(40))


def _pgp_body(rng: random.Random) -> str:
    """An ASCII-armoured-looking PGP body: four 64-character base64 lines.

    The real armour carries a CRC and a header; what matters here is the shape
    — long, wrapped, base64 — because a registry that renders a PGP identifier
    as a 20-character token is not demonstrating the thing it claims to.
    """
    return "\n".join("".join(rng.choice(_BASE64_ALPHABET) for _ in range(64)) for _ in range(4))


def _clearnet(rng: random.Random) -> str:
    return f"{rng.choice(DOMAINS)}{rng.randint(10, 99)}.example"


def _jabber(rng: random.Random, handle: str) -> str:
    return f"{handle}@conference.{rng.choice(PLATFORMS)}.example"


def _identifier_value(rng: random.Random, kind: str, handle: str) -> str:
    if kind == "pgp":
        return _pgp_body(rng)
    if kind == "onion":
        return _onion(rng)
    if kind == "wallet":
        return _wallet(rng)
    if kind == "clearnet":
        return _clearnet(rng)
    if kind == "jabber":
        return _jabber(rng, handle)
    return f"{handle}@{rng.choice(PLATFORMS)}"


def _scan_time(rng: random.Random, now: datetime) -> datetime | None:
    """When the actor was last re-scanned — and some that were never scanned.

    Three bands rather than one uniform draw: a registry in which every actor
    was scanned last week hides exactly the operational failure the problem
    statement asks about, which is actors going stale without anybody noticing.
    """
    roll = rng.random()
    if roll < 0.12:
        return None
    if roll < 0.34:
        return now - timedelta(days=rng.randint(45, 200), hours=rng.randint(0, 23))
    return now - timedelta(days=rng.randint(0, 21), hours=rng.randint(0, 23))


def seed_actor_registry(
    db: Session,
    sources: list[SourceRecord],
    users: dict[str, UserRecord],
    rng: random.Random,
    now: datetime,
) -> dict[str, int]:
    """The cross-case actor registry: actors, their identifiers and their venues.

    Inserted in strict foreign-key order — actors, flush, identifiers, flush,
    marketplaces, flush, linkages, flush — because `actor_identifiers.actor_id`
    and `actor_marketplaces.actor_id` are real constraints and a stage that
    fails halfway would leave a database that is neither the old dataset nor
    the new one.

    The registry is deliberately *not* derived from the per-case `entities`
    rows. Those belong to one investigation; an actor here is tracked across all
    of them, and conflating the two would make "this actor appears in four
    cases" a restatement of "this case has four entities". A handful of
    identifiers do carry a `case_id`, which is the honest link between the two:
    this specific identifier was observed in this specific investigation.
    """
    target = rng.randint(ACTOR_MIN, ACTOR_MAX)
    case_ids = list(db.scalars(select(CaseRecord.case_id)).all())
    analysts = [users[role] for role in sorted(users)]

    handles: set[str] = set()
    plans: list[dict[str, object]] = []
    while len(plans) < target:
        handle = (
            f"{rng.choice(ACTOR_HANDLE_HEADS)}"
            f"{rng.choice(ACTOR_HANDLE_SEPARATORS)}"
            f"{rng.choice(ACTOR_HANDLE_TAILS)}"
        )
        if handle in handles:
            continue
        handles.add(handle)
        kind_count = rng.randint(2, len(ACTOR_IDENTIFIER_KINDS))
        others = [kind for kind in ACTOR_IDENTIFIER_KINDS if kind != "handle"]
        rng.shuffle(others)
        first_seen = now - timedelta(days=rng.randint(60, 400), hours=rng.randint(0, 23))
        plans.append(
            {
                "handle": handle,
                "category": rng.choice(ACTOR_CATEGORIES),
                "status": _weighted(rng, ACTOR_STATUS_WEIGHTS),
                # ~18% carry no attribution score at all. "Not assessed" and
                # "assessed at zero" are different facts, and the registry only
                # demonstrates that distinction if some rows genuinely have no
                # score.
                "confidence": None if rng.random() < 0.18 else round(rng.uniform(0.25, 0.97), 3),
                "first_seen": first_seen,
                "last_seen": now - timedelta(days=rng.randint(0, 120), hours=rng.randint(0, 23)),
                "last_scan_at": _scan_time(rng, now),
                "source": sources[rng.randrange(len(sources))],
                "kinds": ["handle", *others[: kind_count - 1]],
                "marketplaces": rng.sample(ACTOR_MARKETPLACES, rng.randint(1, 4)),
            }
        )

    actors: list[ActorRecord] = [
        ActorRecord(
            actor_id=sid(f"actor:{plan['handle']}"),
            handle=str(plan["handle"]),
            category=str(plan["category"]),
            status=str(plan["status"]),
            confidence=plan["confidence"],  # type: ignore[arg-type]
            first_seen=plan["first_seen"],  # type: ignore[arg-type]
            last_seen=plan["last_seen"],  # type: ignore[arg-type]
            last_scan_at=plan["last_scan_at"],  # type: ignore[arg-type]
            source_id=plan["source"].source_id,  # type: ignore[union-attr]
            notes=(
                None
                if rng.random() < 0.55
                else f"Synthetic registry record for {plan['category']}. Not a real-world actor."
            ),
            metadata_json={
                "synthetic": True,
                "schema_version": SCHEMA_VERSION,
                "category": plan["category"],
            },
        )
        for plan in plans
    ]
    _flush_batches(db, actors)

    identifiers: list[ActorIdentifierRecord] = []
    marketplaces: list[ActorMarketplaceRecord] = []
    for actor, plan in zip(actors, plans, strict=True):
        handle = actor.handle
        for offset, kind in enumerate(plan["kinds"]):  # type: ignore[arg-type]
            value = _identifier_value(rng, str(kind), handle)
            # Two identifiers of one kind on one actor are frequently the same
            # observation seen twice. Giving a subset of them an independence
            # group is what lets the registry show that discount rather than
            # just asserting it in a comment.
            grouped = rng.random() < 0.3
            identifiers.append(
                ActorIdentifierRecord(
                    identifier_id=sid(f"actor-identifier:{actor.actor_id}:{kind}:{offset}"),
                    actor_id=actor.actor_id,
                    kind=str(kind),
                    value=value,
                    independence_group=(
                        f"{handle}-{rng.choice(ACTOR_HANDLE_TAILS)}" if grouped else None
                    ),
                    confidence=(None if rng.random() < 0.15 else round(rng.uniform(0.4, 0.99), 3)),
                    first_seen=actor.first_seen,
                    last_seen=actor.last_seen,
                    source_id=plan["source"].source_id,  # type: ignore[union-attr]
                    metadata_json={
                        "synthetic": True,
                        "schema_version": SCHEMA_VERSION,
                        "synthetic_value": True,
                    },
                )
            )

        window_start = actor.first_seen or (now - timedelta(days=200))
        for venue in plan["marketplaces"]:  # type: ignore[arg-type]
            venue_start = window_start + timedelta(days=rng.randint(0, 120))
            venue_end = venue_start + timedelta(days=rng.randint(20, 300))
            marketplaces.append(
                ActorMarketplaceRecord(
                    presence_id=sid(f"actor-marketplace:{actor.actor_id}:{venue}"),
                    actor_id=actor.actor_id,
                    marketplace=str(venue),
                    role=_weighted(rng, ACTOR_MARKETPLACE_ROLES),
                    first_seen=venue_start,
                    # A truncated window, not a clamped one: a venue abandoned
                    # two years ago must not read as one the persona is still on.
                    last_seen=min(venue_end, now - timedelta(days=rng.randint(0, 200))),
                    listing_count=rng.randint(0, 240),
                    source_id=plan["source"].source_id,  # type: ignore[union-attr]
                    metadata_json={
                        "synthetic": True,
                        "schema_version": SCHEMA_VERSION,
                        "synthetic_venue": True,
                    },
                )
            )
    _flush_batches(db, identifiers)
    _flush_batches(db, marketplaces)

    # A few identifiers carry a `case_id`: this specific identifier was observed
    # in this specific investigation. That is the honest bridge between a
    # cross-case actor and a case-scoped evidence graph, and it is what makes
    # the register's LINKS column mean something.
    linked = 0
    if case_ids and identifiers:
        for actor, _plan in list(zip(actors, plans, strict=True))[::7]:
            own = [
                row
                for row in identifiers
                if row.actor_id == actor.actor_id and row.kind in {"onion", "pgp", "wallet"}
            ]
            for row in own[: rng.randint(1, 2)]:
                row.case_id = case_ids[rng.randrange(len(case_ids))]
                row.metadata_json = {**(row.metadata_json or {}), "case_linked": True}
                linked += 1
    db.flush()

    # Persona linkages: a handful of proposals, most still awaiting a ruling.
    # `ck_persona_linkage_adjudicated` requires an adjudicator and a timestamp
    # on any row that is not `proposed`, so the adjudicated ones name a real
    # seeded analyst — which is why this stage takes `users` at all.
    linkages: list[PersonaLinkageRecord] = []
    for actor, _plan in list(zip(actors, plans, strict=True))[::5]:
        method = rng.choice(("stylometry", "behavioural", "infrastructure", "attribution"))
        roll = rng.random()
        status = "proposed" if roll < 0.62 else ("confirmed" if roll < 0.86 else "rejected")
        aligned = rng.sample(
            ("posting_cadence", "pivot vocabulary", "payment cadence", "burst pattern"),
            rng.randint(1, 3),
        )
        apart = rng.sample(("topic shift", "lexical drift", "timezone mismatch"), rng.randint(0, 2))
        contested = (
            rng.sample(("sentence length", "emoji use", "vendor spelling"), 1)
            if rng.random() < 0.4
            else []
        )
        analyst = analysts[rng.randrange(len(analysts))] if status != "proposed" else None
        linkages.append(
            PersonaLinkageRecord(
                linkage_id=sid(f"persona-linkage:{actor.actor_id}:{method}"),
                actor_id=actor.actor_id,
                candidate_handle=f"{rng.choice(ACTOR_HANDLE_HEADS)}{rng.randint(10, 99)}",
                method=method,
                score=round(rng.uniform(0.18, 0.94), 3),
                status=status,
                aligned_features=aligned,
                apart_features=apart,
                contested_features=contested,
                limitations=[
                    "Synthetic record. Stylometric similarity is not identity.",
                    "Single corpus; no independent replication on file.",
                ],
                case_id=case_ids[rng.randrange(len(case_ids))] if case_ids else None,
                adjudicated_by=analyst.user_id if analyst else None,
                adjudicated_at=(now - timedelta(days=rng.randint(1, 60))) if analyst else None,
                rationale=(
                    "Synthetic analyst ruling. Recorded to demonstrate that a decision keeps "
                    "its author and date."
                    if analyst
                    else None
                ),
                metadata_json={"synthetic": True, "schema_version": SCHEMA_VERSION},
            )
        )
    _flush_batches(db, linkages)

    return {
        "actors": len(actors),
        "actor_identifiers": len(identifiers),
        "actor_marketplaces": len(marketplaces),
        "actor_case_links": linked,
        "persona_linkages": len(linkages),
    }


def sid(label: str) -> UUID:
    """Deterministic identifier, so a re-seed reproduces the same world."""
    return uuid5(NAMESPACE, label)


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def _modality_for(entity_type: str) -> str:
    for modality, kind in MODALITY_ENTITY.items():
        if kind == entity_type:
            return modality
    return "infrastructure"


@dataclass
class PlannedEntity:
    """An entity decided before the evidence that will justify it exists."""

    entity_type: str
    surface_form: str
    normalized_form: str
    actor_slot: int
    weight: float


@dataclass
class CaseWorld:
    """The identifiers one case produced, threaded through later stages."""

    blueprint: CaseBlueprint
    case: CaseRecord
    owner: UserRecord | None
    evidence: list[EvidenceRecord] = field(default_factory=list)
    entities: list[EntityRecord] = field(default_factory=list)
    actors: list[EntityRecord] = field(default_factory=list)
    hypotheses: list[HypothesisRecord] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)

    def by_type(self, entity_type: str) -> list[EntityRecord]:
        return [entity for entity in self.entities if entity.entity_type == entity_type]


def _flush(db: Session, rows: list[Any]) -> None:
    """Add and flush a batch."""
    if not rows:
        return
    db.add_all(rows)
    db.flush()


def _flush_batches(db: Session, rows: list[Any]) -> None:
    """Flush ``rows`` in bounded batches, leaving the caller's list intact."""
    for start in range(0, len(rows), BATCH):
        db.add_all(rows[start : start + BATCH])
        db.flush()


def reset(db: Session) -> None:
    """Remove every row this seeder owns.

    ``TRUNCATE`` rather than ``DELETE``: ``audit_logs`` carries a
    ``BEFORE UPDATE OR DELETE`` trigger, and truncating satisfies the foreign
    keys in one statement instead of a round trip per level.
    """
    db.execute(text(f"TRUNCATE TABLE {', '.join(DEMO_TABLES)} RESTART IDENTITY CASCADE"))
    db.commit()


def dataset_present(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(CaseRecord)) > 0


def seed_roles_and_users(db: Session, *, demo_password: str) -> dict[str, UserRecord]:
    """RBAC roles and the analyst team.

    Passwords are hashed with the same routine the API verifies against, so
    the seeded team signs in through the real credential path instead of a
    demo-only shortcut.
    """
    roles: dict[str, RoleRecord] = {}
    for name, description, permissions in ROLE_BLUEPRINTS:
        record = RoleRecord(
            role_id=sid(f"role:{name}"),
            name=name,
            description=description,
            permissions=list(permissions),
        )
        roles[name] = record
    db.add_all(list(roles.values()))
    db.flush()

    # Hash once, not once per analyst: six PBKDF2 runs at 600k iterations is
    # ~1.5 s of pure CPU for no additional security.
    password_hash = hash_password(demo_password)
    users: dict[str, UserRecord] = {}
    for email, display_name, role_name in ANALYST_BLUEPRINTS:
        record = UserRecord(
            user_id=sid(f"user:{email}"),
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role_id=roles[role_name].role_id,
            is_active=True,
        )
        users[role_name] = record
    db.add_all(list(users.values()))
    db.flush()
    return users


def seed_sources(db: Session) -> list[SourceRecord]:
    sources = [
        SourceRecord(
            source_id=sid(f"source:{index}"),
            source_type=kind,
            name=name,
            reliability=reliability,
            metadata_json={
                "synthetic": True,
                "schema_version": SCHEMA_VERSION,
                # Independence is what later stages use to discount three
                # "sources" that are really one outlet.
                "independence_group": group,
            },
        )
        for index, (kind, name, reliability, group) in enumerate(SOURCE_BLUEPRINTS)
    ]
    db.add_all(sources)
    db.flush()
    return sources


def seed_cases(
    db: Session, blueprints: tuple[CaseBlueprint, ...], users: dict[str, UserRecord], now: datetime
) -> list[CaseRecord]:
    cases = [
        CaseRecord(
            case_id=sid(f"case:{blueprint.slug}"),
            name=blueprint.name,
            description=blueprint.description,
            status=blueprint.status,
            priority=blueprint.priority,
            severity=blueprint.severity,
            tags=list(blueprint.tags),
            assigned_to=users[blueprint.owner_role].user_id,
            sla_due_at=now + timedelta(hours=blueprint.sla_hours),
        )
        for blueprint in blueprints
    ]
    db.add_all(cases)
    db.flush()
    return cases


def plan_entities(world: CaseWorld, rng: random.Random) -> list[PlannedEntity]:
    """Decide the entity graph for a case before any of it is persisted."""
    weights = world.blueprint.modality_weights
    planned: list[PlannedEntity] = []

    for actor_index in range(world.blueprint.actor_count):
        handle = HANDLES[(actor_index * 5) % len(HANDLES)]
        platform = PLATFORMS[actor_index % len(PLATFORMS)]
        planned.append(
            PlannedEntity(
                "actor", f"Operator {handle.title()}", handle, actor_index, weights["temporal"]
            )
        )
        for _ in range(rng.randint(2, 4)):
            alias = f"{handle}-{rng.choice(HANDLES)}"
            planned.append(
                PlannedEntity(
                    "alias", f"{alias}@{platform}", alias, actor_index, weights["behavioral"]
                )
            )
        for account_index in range(rng.randint(1, 2)):
            planned.append(
                PlannedEntity(
                    "account",
                    f"{platform}/acct/{handle}{account_index}",
                    f"{platform}:{handle}",
                    actor_index,
                    weights["behavioral"],
                )
            )
        for domain_index in range(rng.randint(1, 3)):
            label = f"{rng.choice(DOMAINS)}{domain_index}{rng.randint(10, 99)}"
            planned.append(
                PlannedEntity(
                    "domain", f"{label}.example", label, actor_index, weights["infrastructure"]
                )
            )
        planned.append(
            PlannedEntity(
                "ip",
                f"198.51.100.{rng.randint(2, 250)}",
                f"198.51.100.{actor_index}",
                actor_index,
                weights["infrastructure"],
            )
        )
        for wallet_index in range(rng.randint(1, 2)):
            body = (
                f"{rng.choice(WALLET_PREFIXES)}"
                f"{digest(world.blueprint.slug, handle, wallet_index)[:34]}"
            )
            planned.append(
                PlannedEntity("wallet", body[:42], body.lower(), actor_index, weights["financial"])
            )
        for doc_index in range(rng.randint(1, 2)):
            planned.append(
                PlannedEntity(
                    "document",
                    f"{rng.choice(DOC_KINDS)}-{handle}-{doc_index}",
                    f"{handle}{doc_index}",
                    actor_index,
                    weights["stylometry"],
                )
            )

    # Shared infrastructure: a few nodes deliberately reused across actors, so
    # the network has real hubs instead of a field of isolated stars.
    shared = max(2, world.blueprint.actor_count // 4)
    for index in range(shared):
        label = f"shared-{rng.choice(DOMAINS)}{index}.example"
        slot = index % world.blueprint.actor_count
        planned.append(
            PlannedEntity(
                "infrastructure", label, label.split(".")[0], slot, weights["infrastructure"]
            )
        )
        planned.append(
            PlannedEntity(
                "marketplace",
                f"market-{rng.choice(PLATFORMS)}-{index}",
                f"market{index}",
                slot,
                weights["financial"],
            )
        )

    planned.sort(
        key=lambda item: (ENTITY_ORDER.index(item.entity_type), item.actor_slot, item.surface_form)
    )
    return planned


def seed_evidence(
    db: Session,
    world: CaseWorld,
    sources: list[SourceRecord],
    planned: list[PlannedEntity],
    rng: random.Random,
    now: datetime,
    count: int,
) -> list[EvidenceRecord]:
    """The evidence ledger, observed on the planned entities.

    Artifacts are written in the same pass because ``evidence.artifact_id``
    references them, and both precede ``entities`` which reference the
    evidence.
    """
    case_id = world.case.case_id
    label = world.blueprint.name
    artifacts: list[ArtifactRecord] = []
    evidence: list[EvidenceRecord] = []
    # Artifacts and evidence are two tables, but the evidence rows carry a
    # foreign key into artifacts, so each pair is flushed together. The
    # watermark keeps the flush incremental: re-adding already-persisted rows
    # would make the seeder quadratic in the evidence count.
    flushed = 0
    for index in range(count):
        target = planned[index % len(planned)]
        source = sources[index % len(sources)]
        # Collection ramps up towards the present, but a pure half-normal
        # distribution produces a monotonic staircase (4, 34, 121, 366 …) that
        # reads as a data-loading artefact rather than as operational history.
        # Blending it with a uniform draw keeps the upward trend and restores
        # month-to-month variation, so the velocity chart is legible.
        if index % 2 == 0:
            age_days = int(abs(rng.gauss(0, 58))) % 205
        else:
            age_days = rng.randint(0, 204)
        observed = now - timedelta(days=age_days, hours=rng.randint(0, 23))
        collected = observed + timedelta(minutes=rng.randint(2, 360))
        content_hash = digest(case_id, index, target.surface_form)
        artifacts.append(
            ArtifactRecord(
                artifact_id=sid(f"artifact:{case_id}:{index}"),
                sha256=content_hash,
                storage_uri=f"synthetic://aegis/{case_id}/artifacts/{index}",
                media_type="application/json",
                size_bytes=512 + (index % 31) * 97,
            )
        )
        evidence.append(
            EvidenceRecord(
                evidence_id=sid(f"evidence:{case_id}:{index}"),
                case_id=case_id,
                source_id=source.source_id,
                source_type=source.source_type,
                observed_at=observed,
                collected_at=collected,
                entity_type=target.entity_type,
                entity_value_hash=digest("entity", target.normalized_form)[:64],
                context_hash=digest("context", case_id, index)[:64],
                raw_artifact_uri=f"synthetic://aegis/{case_id}/evidence/{index}",
                artifact_id=sid(f"artifact:{case_id}:{index}"),
                sha256=content_hash,
                collector_name=f"synthetic-{source.source_type}",
                collector_version="1.4.0",
                normalizer_version="1.3.0",
                extraction_version="2.2.0",
                source_reliability=source.reliability,
                independence_group=str(
                    (source.metadata_json or {}).get("independence_group", "demo")
                ),
                metadata_json={
                    "synthetic": True,
                    "schema_version": SCHEMA_VERSION,
                    "title": f"{label} · {target.surface_form}",
                    "summary": (
                        f"Synthetic observation of {target.surface_form} "
                        f"collected from {source.name}."
                    ),
                    "language": "en",
                    "surface_form": target.surface_form,
                    "modality": _modality_for(target.entity_type),
                    "severity": ["low", "medium", "high", "critical"][index % 4],
                },
            )
        )
        if len(evidence) - flushed >= BATCH:
            _flush(db, artifacts[flushed:])
            _flush(db, evidence[flushed:])
            flushed = len(evidence)
    _flush(db, artifacts[flushed:])
    _flush(db, evidence[flushed:])
    return evidence


def seed_entities(
    db: Session,
    world: CaseWorld,
    planned: list[PlannedEntity],
    evidence: list[EvidenceRecord],
    rng: random.Random,
    now: datetime,
) -> list[EntityRecord]:
    """Bind each planned entity to the evidence that actually surfaced it.

    ``entities.evidence_id`` is NOT NULL, so this stage cannot run before the
    ledger is flushed. Binding by surface form rather than by position means
    the entity cites the observation it came from, not an arbitrary row.
    """
    by_surface: dict[str, list[EvidenceRecord]] = {}
    for row in evidence:
        surface = str((row.metadata_json or {}).get("surface_form") or "")
        if surface:
            by_surface.setdefault(surface, []).append(row)

    entities: list[EntityRecord] = []
    for index, target in enumerate(planned):
        supporting = by_surface.get(target.surface_form)
        bound = (
            supporting[index % len(supporting)] if supporting else evidence[index % len(evidence)]
        )
        entities.append(
            EntityRecord(
                entity_id=sid(f"entity:{world.case.case_id}:{index}"),
                case_id=world.case.case_id,
                evidence_id=bound.evidence_id,
                entity_type=target.entity_type,
                surface_form=target.surface_form,
                normalized_form=target.normalized_form,
                confidence=round(0.58 + rng.random() * 0.41, 3),
                first_seen=bound.observed_at or (now - timedelta(days=180)),
                last_seen=bound.collected_at,
                metadata_json={
                    "synthetic": True,
                    "schema_version": SCHEMA_VERSION,
                    "actor_slot": target.actor_slot,
                    "modality": _modality_for(target.entity_type),
                },
            )
        )
    _flush_batches(db, entities)
    return entities


def seed_relationships(
    db: Session,
    world: CaseWorld,
    entities: list[EntityRecord],
    evidence: list[EvidenceRecord],
    rng: random.Random,
    now: datetime,
) -> int:
    """Typed, evidence-backed edges between the entities just written."""
    by_type: dict[str, list[EntityRecord]] = {
        entity_type: [e for e in entities if e.entity_type == entity_type]
        for entity_type in ENTITY_ORDER
    }
    actors = by_type["actor"]
    edges: list[tuple[str, UUID, UUID]] = []

    def edge(kind: str, subject: EntityRecord, obj: EntityRecord) -> None:
        if subject.entity_id != obj.entity_id:
            edges.append((kind, subject.entity_id, obj.entity_id))

    for actor in actors:
        slot = (actor.metadata_json or {}).get("actor_slot")
        for entity_type, kind in (
            ("alias", "uses"),
            ("account", "uses"),
            ("domain", "controls"),
            ("ip", "controls"),
            ("wallet", "controls"),
            ("document", "authored"),
        ):
            for candidate in by_type[entity_type]:
                if (candidate.metadata_json or {}).get("actor_slot") == slot:
                    edge(kind, actor, candidate)

    for domain in by_type["domain"]:
        for ip in by_type["ip"]:
            if rng.random() < 0.34:
                edge("resolved-to", domain, ip)
        for infra in by_type["infrastructure"]:
            if rng.random() < 0.3:
                edge("hosted", domain, infra)
    wallets = by_type["wallet"]
    for index, wallet in enumerate(wallets):
        for other in wallets[index + 1 : index + 4]:
            if rng.random() < 0.4:
                edge("transacted", wallet, other)
    for marketplace in by_type["marketplace"]:
        for document in by_type["document"]:
            if rng.random() < 0.28:
                edge("associated-with", marketplace, document)
    for alias in by_type["alias"]:
        for account in by_type["account"]:
            if rng.random() < 0.22:
                edge("associated-with", alias, account)

    # Actor-to-actor edges include both real collaborations and coincidences
    # the resolver has not eliminated. Without the second group the network
    # would look far more resolved than the assessments justify.
    for index, actor in enumerate(actors):
        for offset in (1, 2, 3):
            kind = "communicates_with" if rng.random() < 0.6 else "associated-with"
            edge(kind, actor, actors[(index + offset) % len(actors)])
    for shared in by_type["infrastructure"][:8]:
        for actor in actors[: max(2, len(actors) // 2)]:
            edge("associated-with", shared, actor)

    seen: set[tuple[str, UUID, UUID]] = set()
    rows: list[RelationshipRecord] = []
    flushed = 0
    for index, (kind, subject_id, object_id) in enumerate(edges):
        key = (kind, subject_id, object_id)
        if key in seen:
            continue
        seen.add(key)
        # The window must not invert: `last_seen` is drawn first and
        # `first_seen` is placed before it, rather than the two being drawn
        # independently. Drawing them independently produced a relationship
        # last seen before it was first seen in about 8% of rows, which the
        # canonical `Relationship` schema correctly rejects — so the whole
        # graph build died on one bad row.
        age_hours = rng.randint(1, 24 * 200)
        last_seen = now - timedelta(hours=age_hours)
        span_hours = rng.randint(1, max(1, age_hours))
        first_seen = last_seen - timedelta(hours=span_hours)
        support = evidence[(index * 5) % len(evidence)]
        rows.append(
            RelationshipRecord(
                relationship_id=sid(f"relationship:{world.case.case_id}:{len(seen)}"),
                case_id=world.case.case_id,
                subject_entity_id=subject_id,
                object_entity_id=object_id,
                relationship_type=kind,
                first_seen=first_seen,
                last_seen=last_seen,
                valid_from=first_seen,
                valid_until=last_seen,
                confidence=round(0.51 + rng.random() * 0.48, 3),
                evidence_ids=[support.evidence_id],
                metadata_json={"synthetic": True, "schema_version": SCHEMA_VERSION},
            )
        )
        if len(rows) - flushed >= BATCH:
            _flush(db, rows[flushed:])
            flushed = len(rows)
    _flush(db, rows[flushed:])
    return len(seen)


def seed_hypotheses_and_assessments(
    db: Session, world: CaseWorld, evidence: list[EvidenceRecord], rng: random.Random
) -> int:
    """Competing hypotheses with evidence-linked, per-modality assessments.

    Confidence is drawn once per hypothesis and reused for both the hypothesis
    and its assessment, so the two can never disagree. A minority carry
    explicit contradictions, so the console's contradiction counters and the
    "outstanding contradictions" block have real referents.
    """
    actors = [e for e in world.entities if e.entity_type == "actor"]
    if len(actors) < 2 or not evidence:
        return 0
    case_id = world.case.case_id
    by_modality: dict[str, list[EvidenceRecord]] = {}
    for row in evidence:
        by_modality.setdefault(
            str((row.metadata_json or {}).get("modality") or "temporal"), []
        ).append(row)

    pairs: list[tuple[HypothesisRecord, float, bool]] = []
    for index in range(len(CONFIDENCE_ENVELOPES)):
        subject = actors[index % len(actors)]
        target = actors[(index * 3 + 2) % len(actors)]
        if subject.entity_id == target.entity_id:
            target = actors[(index * 3 + 3) % len(actors)]
        low, high = CONFIDENCE_ENVELOPES[index]
        confidence = round(low + rng.random() * (high - low), 4)
        contradicted = index % 2 == 1
        record = HypothesisRecord(
            hypothesis_id=sid(f"hypothesis:{case_id}:{index}"),
            case_id=case_id,
            subject_entity_id=subject.entity_id,
            object_entity_id=target.entity_id,
            kind=HYPOTHESIS_KINDS[index % len(HYPOTHESIS_KINDS)],
            status="supported"
            if confidence >= 0.7
            else "candidate"
            if confidence >= 0.4
            else "rejected",
            missing_evidence=(
                []
                if confidence >= 0.7
                else ["independent corroboration", "second-source financial trace"]
            ),
            analyst_disposition=(
                "Synthetic benchmark hypothesis. Not a real-world attribution and "
                "not a finding about any real person or organisation."
            ),
            metadata_json={
                "synthetic": True,
                "schema_version": SCHEMA_VERSION,
                "label": f"H-{index + 1:02d} · {subject.surface_form} → {target.surface_form}",
            },
        )
        db.add(record)
        pairs.append((record, confidence, contradicted))
    db.flush()

    links: list[HypothesisLinkRecord] = []
    assessments: list[AssessmentRecord] = []
    for index, (hypothesis, confidence, contradicted) in enumerate(pairs):
        supporting: list[EvidenceRecord] = []
        for offset, modality in enumerate(MODALITIES):
            pool = by_modality.get(modality) or evidence
            start = (index * 11 + offset * 3) % len(pool)
            supporting.extend(pool[start : start + 2])
        supporting = supporting[:9] or evidence[:3]
        contradictory = (
            evidence[(index * 17 + 5) % len(evidence) : (index * 17 + 5) % len(evidence) + 2]
            if contradicted
            else []
        )

        for role, rows in (("supporting", supporting), ("contradicting", contradictory)):
            for offset, row in enumerate(rows):
                links.append(
                    HypothesisLinkRecord(
                        link_id=sid(f"hlink:{hypothesis.hypothesis_id}:{role}:{offset}"),
                        hypothesis_id=hypothesis.hypothesis_id,
                        evidence_id=row.evidence_id,
                        role=role,
                        modality=str((row.metadata_json or {}).get("modality") or "temporal"),
                        independence_group=str(row.independence_group),
                        weight=round(0.55 + rng.random() * 0.45, 3),
                    )
                )

        signals = {
            modality: round(max(0.05, min(0.98, confidence + rng.uniform(-0.28, 0.18))), 3)
            for modality in MODALITIES
        }
        assessments.append(
            AssessmentRecord(
                assessment_id=sid(f"assessment:{hypothesis.hypothesis_id}"),
                hypothesis_id=hypothesis.hypothesis_id,
                case_id=case_id,
                model_id="temporal-hgt-fusion",
                model_version="phase-19.2",
                raw_score=round(min(1.0, confidence + 0.04), 4),
                calibrated_confidence=confidence,
                calibration_version="synthetic-demo-v2",
                signals_json=signals,
                supporting_evidence_ids=[row.evidence_id for row in supporting],
                contradictory_evidence_ids=[row.evidence_id for row in contradictory],
                explanations=[
                    f"Synthetic {modality} signal {signals[modality]:.2f} across "
                    f"{len({row.independence_group for row in supporting})} "
                    "independent source groups."
                    for modality in MODALITIES[:3]
                ],
                limitations=[
                    "Synthetic dataset; no real-world identity inference is supported.",
                    "Attribution confidence is model output, not an analyst finding.",
                ],
            )
        )
        world.hypotheses.append(hypothesis)
        world.confidences.append(confidence)
    _flush(db, links)
    _flush(db, assessments)
    return len(pairs)


def seed_audit_trail(db: Session, world: CaseWorld, rng: random.Random, now: datetime) -> int:
    """Append the operational history the console's live surfaces replay.

    These entries are what Threat Watch streams, what the timeline's event
    layer shows, and what the pressure and alert counters are computed from.
    They go through ``AuditService`` so the hash chain stays intact rather
    than being inserted behind its back.
    """
    audit = AuditService(db)
    actor_ids = [
        str(actor.entity_id) for actor in world.entities if actor.entity_type == "actor"
    ] or ["unknown"]
    targets = [
        str(entity.entity_id)
        for entity in world.entities
        if entity.entity_type in {"domain", "ip", "infrastructure", "wallet"}
    ] or ["unknown"]
    evidence_titles = [
        str((row.metadata_json or {}).get("title") or "Evidence record")
        for row in world.evidence[:40]
    ] or ["Evidence record"]

    for index in range(EVENTS_PER_CASE):
        action, layer, template = THREAT_TEMPLATES[index % len(THREAT_TEMPLATES)]
        source = actor_ids[index % len(actor_ids)]
        target = targets[(index * 7 + 3) % len(targets)]
        if action.startswith("alert."):
            severity = "critical"
        elif action.startswith("threat."):
            severity = "high"
        else:
            severity = ("info", "warning")[index % 2]
        detail = (
            evidence_titles[index % len(evidence_titles)]
            if action.startswith("evidence.")
            else target
        )
        audit.record(
            action,
            entity_type="case",
            entity_id=str(world.case.case_id),
            case_id=world.case.case_id,
            payload={
                "synthetic": True,
                "schema_version": SCHEMA_VERSION,
                "message": f"{template} — {source} → {detail} ({world.case.name})",
                "layer": layer,
                "severity": severity,
                "actor_entity_id": source,
                "target_entity_id": target,
            },
            # Walk backwards across a ~45-day window so the timeline, the
            # velocity chart and Threat Watch share one chronology.
            occurred_at=now - timedelta(minutes=index * 890 + rng.randint(0, 240)),
        )
    return EVENTS_PER_CASE


def seed(
    db: Session, evidence_per_case: int, *, reset_first: bool, demo_password: str
) -> dict[str, object]:
    if reset_first:
        reset(db)
    elif dataset_present(db):
        return {"status": 0, "message": "demo dataset already present; pass --reset to rebuild"}

    rng = random.Random(26151)
    now = datetime.now(UTC)

    users = seed_roles_and_users(db, demo_password=demo_password)
    sources = seed_sources(db)
    cases = seed_cases(db, CASE_BLUEPRINTS, users, now)

    totals: dict[str, object] = {
        "status": 1,
        "cases": len(cases),
        "sources": len(sources),
        # `users` is keyed by role for case ownership, so it holds one entry
        # per distinct role rather than one per analyst.
        "users": len(ANALYST_BLUEPRINTS),
        "evidence": 0,
        "entities": 0,
        "relationships": 0,
        "hypotheses": 0,
        "assessments": 0,
        "audit_events": 0,
        "actors": 0,
        "actor_identifiers": 0,
        "actor_marketplaces": 0,
        "actor_case_links": 0,
        "persona_linkages": 0,
    }

    for blueprint, case in zip(CASE_BLUEPRINTS, cases, strict=True):
        world = CaseWorld(blueprint=blueprint, case=case, owner=users[blueprint.owner_role])
        planned = plan_entities(world, rng)
        world.evidence = seed_evidence(db, world, sources, planned, rng, now, evidence_per_case)
        world.entities = seed_entities(db, world, planned, world.evidence, rng, now)
        world.actors = [e for e in world.entities if e.entity_type == "actor"]
        relationship_count = seed_relationships(db, world, world.entities, world.evidence, rng, now)
        hypothesis_count = seed_hypotheses_and_assessments(db, world, world.evidence, rng)
        totals["audit_events"] = int(totals["audit_events"]) + seed_audit_trail(db, world, rng, now)
        totals["evidence"] = int(totals["evidence"]) + len(world.evidence)
        totals["entities"] = int(totals["entities"]) + len(world.entities)
        totals["relationships"] = int(totals["relationships"]) + relationship_count
        totals["hypotheses"] = int(totals["hypotheses"]) + hypothesis_count
        totals["assessments"] = int(totals["assessments"]) + hypothesis_count

    # After the cases, because the actor registry links identifiers to them.
    registry = seed_actor_registry(db, sources, users, rng, now)
    totals.update(registry)

    AuditService(db).record(
        "demo.seeded",
        entity_type="platform",
        entity_id="aegis-demo",
        payload={
            "synthetic": True,
            "schema_version": SCHEMA_VERSION,
            "cases": totals["cases"],
            "evidence": totals["evidence"],
            "actors": totals["actors"],
        },
        occurred_at=now,
    )
    totals["audit_events"] = int(totals["audit_events"]) + 1
    db.commit()
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AEGIS synthetic demonstration dataset.")
    parser.add_argument(
        "--evidence-per-case", type=int, default=620, help="evidence rows per case (>= 50)"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="truncate every table this seeder owns before rebuilding",
    )
    parser.add_argument(
        "--index", action="store_true", help="also bulk-index synthetic evidence in OpenSearch"
    )
    parser.add_argument(
        "--demo-password",
        default=settings.auth_password,
        help="password for the seeded analyst accounts",
    )
    args = parser.parse_args()
    if args.evidence_per_case < 50:
        raise SystemExit("--evidence-per-case must be >= 50")

    with SessionLocal() as db:
        result = seed(
            db, args.evidence_per_case, reset_first=args.reset, demo_password=args.demo_password
        )
        print(result)
        if args.index and result.get("evidence"):
            rows = db.scalars(
                select(EvidenceRecord).order_by(EvidenceRecord.collected_at.asc())
            ).all()
            search = OpenSearchAdapter(
                settings.opensearch_url,
                index_prefix=settings.opensearch_index_prefix,
                http_auth=(
                    (settings.opensearch_username, settings.opensearch_password)
                    if settings.opensearch_username and settings.opensearch_password
                    else None
                ),
            )
            print({"indexed": EvidenceSearchIndexer(search).index_many(rows)})


if __name__ == "__main__":
    main()
