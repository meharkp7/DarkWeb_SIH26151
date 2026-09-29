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
import base64
import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from aegis.api.infrastructure import features_document
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
    InfrastructureFindingRecord,
    InfrastructureMatchRecord,
    InfrastructureObservationRecord,
    PersonaLinkageRecord,
    RelationshipRecord,
    RoleRecord,
    SourceRecord,
    UserRecord,
)
from aegis.db.session import SessionLocal
from aegis.evidence.search_index import EvidenceSearchIndexer
from aegis.infrastructure.correlate import correlate_all
from aegis.infrastructure.extract import extract_features, extract_observation
from aegis.infrastructure.types import (
    CorrelationThresholds,
    InfrastructureCorrelation,
    InfrastructureFeatures,
)
from aegis.ontology import EntityType
from aegis.search.opensearch import OpenSearchAdapter
from aegis.settings import settings
from aegis.stylometry.transforms import apply_transform

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

    # Persona linkages are seeded by ``seed_persona_linkages``, which scores
    # candidates with the platform's own stylometry and behavioural code and so
    # emits real feature names. Drawing scores and feature labels here as well
    # would put invented vocabulary into the same table the linkage surface
    # reads, which is the one thing a linkage score must not be.

    return {
        "actors": len(actors),
        "actor_identifiers": len(identifiers),
        "actor_marketplaces": len(marketplaces),
        "actor_case_links": linked,
        "persona_linkages": 0,
    }


#: Adversarial rewrite pipelines applied to a candidate's text before it is
#: scored, light to heavy. Each entry is a real
#: :func:`aegis.stylometry.transforms.apply_transform` pipeline over the
#: platform's own synthetic alias documents, so the score stored on a seeded row
#: is one this platform's own scorer produced on genuinely rewritten text —
#: which is what "rebranded or migrated persona" means operationally. Drawing
#: the score from a distribution instead would produce a register whose
#: headline error rate meant nothing.
MIGRATION_STACKS: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = (
    ("untransformed", ()),
    ("register-shift", (("slang_normalization", 1.0),)),
    ("case-shift", (("case_change", 1.0),)),
    ("half-case-shift", (("case_change", 0.5),)),
    ("translated", (("translation", 1.0),)),
    ("punctuation-stripped", (("punctuation_removal", 1.0),)),
    ("punctuation-and-case", (("punctuation_removal", 1.0), ("case_change", 1.0))),
    (
        "heavily-rewritten",
        (("punctuation_removal", 1.0), ("case_change", 1.0), ("noise", 1.0)),
    ),
)

#: Stacks light enough to leave a migrated persona still recognisable, and
#: heavy enough to push one below the reporting threshold. The first group
#: reliably lands above ``SCORE_THRESHOLD``; the second below it.
HIGH_MIGRATION_STACKS: tuple[str, ...] = (
    "untransformed",
    "register-shift",
    "case-shift",
    "half-case-shift",
)
LOW_MIGRATION_STACKS: tuple[str, ...] = (
    "translated",
    "punctuation-stripped",
    "punctuation-and-case",
    "heavily-rewritten",
)

#: ``(method, disposition, score_band)`` for every seeded linkage: 44 rows, a
#: majority still awaiting a ruling, and — the point of the exercise — four
#: confirmations the scorer ranked below the line and four rejections it ranked
#: above it. A linkage surface where the model is never wrong is a surface
#: nobody has used long enough to have been wrong.
LINKAGE_PLAN: tuple[tuple[str, str, str], ...] = (
    *(("stylometry", "proposed", "any"),) * 12,
    *(("stylometry", "confirmed", "high"),) * 5,
    *(("stylometry", "confirmed", "low"),) * 2,
    *(("stylometry", "rejected", "low"),) * 3,
    *(("stylometry", "rejected", "high"),) * 2,
    *(("behavioural", "proposed", "any"),) * 9,
    *(("behavioural", "confirmed", "high"),) * 4,
    *(("behavioural", "confirmed", "low"),) * 2,
    *(("behavioural", "rejected", "low"),) * 3,
    *(("behavioural", "rejected", "high"),) * 2,
)

#: The score the linkage surface treats as "ranked high". Mirrors
#: ``SCORE_THRESHOLD`` in :mod:`aegis.api.personas`; a seeded row is planned
#: against this line so the observed-error pair in the summary is real.
LINKAGE_SCORE_THRESHOLD = 0.75

_RATIONALES: dict[tuple[str, str], tuple[str, ...]] = {
    ("confirmed", "high"): (
        "Style profile and function-word habits hold across both handles with no "
        "adversarial rewrite between the samples. Consistent with one author.",
        "Two independent marketplace threads, same punctuation habits, same "
        "connective usage, no shared template on either venue. Accepted as the "
        "same hand.",
        "Register, capitalisation and lexical diversity agree closely and the "
        "candidate predates no known rebrand. Confirmed on style alone.",
    ),
    ("confirmed", "low"): (
        "Score is low because the candidate writes in a deliberately clipped "
        "register on this venue. The shared vendor list, payment address and PGP "
        "key are not explained by that. Confirmed on those, not on style.",
        "Stylometry is near-useless here — the handle's posts are translated. The "
        "collection window did cover the same vendor pages on both sides, which "
        "is what carries the decision.",
        "Low style agreement, but the candidate's posts and the actor's posts "
        "quote the same fee schedule verbatim in three places. Confirmed.",
    ),
    ("rejected", "high"): (
        "High style agreement, but both samples reproduce the venue's "
        "auto-generated listing header. The agreement is a template artefact "
        "and every handle on that venue scores the same. Rejected.",
        "Rejected: both handles are operated by the same relisting bot rather "
        "than by a person. The rhythm is machine-generated and the person behind "
        "them is not established.",
        "Score is high on style alone. No shared identifier, no shared "
        "infrastructure, and the two handles have never appeared in the same "
        "thread. Rejected as unproven.",
    ),
    ("rejected", "low"): (
        "Clear style divergence, different function-word habits and a different "
        "register. Not the same author.",
        "Rejected: the candidate's writing is a deliberate paraphrase of the "
        "actor's, and the paraphrase is what the features are measuring.",
        "Two different writers sharing a topic list. Punctuation, capitalisation "
        "and sentence length all disagree. Rejected.",
    ),
}


def _migrate(text: str, stack_name: str) -> str:
    """Apply a named :data:`MIGRATION_STACKS` pipeline to *text*."""
    for name, severity in dict(MIGRATION_STACKS)[stack_name]:
        text = apply_transform(text, name, severity=severity, seed=26151)
    return text


def _behaviour_events(
    alias_id: str,
    alias_by_id: dict[str, Any],
    posts_by_alias: dict[str, list[Any]],
    rhythm: dict[str, tuple[int, ...]],
) -> list[Any]:
    """Posting events for one alias, snapped to its actor's posting rhythm.

    The corpus builder draws every post's hour uniformly at random, which would
    give every persona the same rhythm and make the behavioural score
    meaningless. Snapping each post to the owning actor's preferred hours gives
    two aliases of one actor a shared rhythm and two unrelated actors
    different ones — which is the distinction the behavioural method exists to
    draw, and which makes the observed error rate on this surface meaningful.
    """
    hours = rhythm[alias_by_id[alias_id].actor_id]
    return [
        _Event(
            event_id=post.post_id,
            posted_at=post.posted_at.replace(hour=hours[index % len(hours)]),
            platform=post.platform,
            text=f"{post.title} {post.body}",
        )
        for index, post in enumerate(sorted(posts_by_alias[alias_id], key=lambda p: p.posted_at))
    ]


@dataclass(frozen=True)
class _Event:
    """Request-shaped posting event, so the real behaviour code can read it."""

    event_id: str
    posted_at: datetime
    platform: str
    text: str
    parent_author_id: str | None = None
    parent_posted_at: datetime | None = None


def seed_persona_linkages(
    db: Session,
    actors: Sequence[Any] | None,
    rng: random.Random,
    now: datetime,
) -> dict[str, int]:
    """Persona linkages: proposals, rulings, and the model's observed errors.

    Every score here is computed. The stylometric rows are scored by
    :func:`aegis.stylometry.features.stylometric_similarity` and the behavioural
    rows by :func:`aegis.behavior.similarity.compare_profiles`, over the
    platform's own :mod:`aegis.collection.corpus` — real function calls on real
    (synthetic) samples, not a number drawn from a distribution. The
    aligned / apart / contested lists are whatever those scorers concluded, so
    every name in them is a feature the platform actually measures.

    The adjudicated rows are what make the surface honest. Four confirmations
    carry a score below :data:`LINKAGE_SCORE_THRESHOLD` and four rejections
    carry one above it, and each states in its rationale why a human overruled
    the model in that direction. Those two counts are the model's false-negative
    and false-positive rate as analysts have actually observed it; a register
    where the model is never wrong is a register nobody has tested.

    *actors* is the registry the actor stage produced. When it is empty — or
    when this is called before that stage has run — the ``actors`` table is
    read directly, and if that is empty too the stage is skipped with a printed
    note rather than failing the seeder.
    """
    try:
        from aegis.db.models import ActorRecord as _Actor  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - the model is not optional
        print(f"[aegis] persona linkages skipped: {exc}")
        return {}

    registry = list(actors) if actors else list(db.scalars(select(_Actor)).all())
    if not registry:
        print(
            "[aegis] persona linkages skipped: the actors table is empty. Seed the actor "
            "registry first — persona_linkages.actor_id is a real foreign key."
        )
        return {}

    from aegis.api.persona_scoring import SampleTooShort, score_behaviour, score_stylometry
    from aegis.collection.corpus import SyntheticCorpusBuilder
    from aegis.stylometry.evaluation import build_alias_documents

    corpus = SyntheticCorpusBuilder(seed=26151, actor_count=40, post_count=4000).build()
    documents = build_alias_documents(corpus)
    alias_by_id = corpus.alias_by_id
    posts_by_alias: dict[str, list[Any]] = {}
    for post in corpus.posts:
        posts_by_alias.setdefault(post.alias_id, []).append(post)

    rhythm_rng = random.Random(26151)
    rhythm = {
        actor.actor_id: tuple(sorted(rhythm_rng.sample(range(24), rhythm_rng.randint(2, 5))))
        for actor in corpus.actors
    }
    aliases_by_actor: dict[str, list[str]] = {}
    for alias in sorted(corpus.aliases, key=lambda item: item.alias_id):
        aliases_by_actor.setdefault(alias.actor_id, []).append(alias.alias_id)
    corpus_actor_ids = sorted(aliases_by_actor)

    analysts = list(db.scalars(select(UserRecord)).all())
    case_ids = list(db.scalars(select(CaseRecord.case_id)).all())

    def candidate_handle(actor_id: UUID) -> str:
        return (
            f"{rng.choice(ACTOR_HANDLE_HEADS)}"
            f"{rng.choice(ACTOR_HANDLE_SEPARATORS)}"
            f"{rng.choice(ACTOR_HANDLE_TAILS)}"
        )

    def same_actor_options(corpus_actor: str) -> list[tuple[str, str, str]]:
        """Another alias of the same corpus actor, under a light rewrite."""
        options: list[tuple[str, str, str]] = []
        for other in aliases_by_actor[corpus_actor]:
            for stack in HIGH_MIGRATION_STACKS:
                options.append((corpus_actor, other, stack))
        return options

    def other_actor_options(corpus_actor: str) -> list[tuple[str, str, str]]:
        """An unrelated persona's alias, under a rewrite heavy enough to matter."""
        options: list[tuple[str, str, str]] = []
        for other_actor in corpus_actor_ids:
            if other_actor == corpus_actor:
                continue
            for alias in aliases_by_actor[other_actor][:2]:
                for stack in LOW_MIGRATION_STACKS:
                    options.append((other_actor, alias, stack))
        return options

    rows: list[PersonaLinkageRecord] = []
    counts = {"proposed": 0, "confirmed": 0, "rejected": 0, "unplanned": 0}
    seen: set[tuple[str, str, str]] = set()
    cursor = 0

    for method, disposition, band in LINKAGE_PLAN:
        actor = registry[cursor % len(registry)]
        corpus_actor = corpus_actor_ids[cursor % len(corpus_actor_ids)]
        cursor += 1
        known_alias = aliases_by_actor[corpus_actor][0]
        handle = candidate_handle(actor.actor_id)
        # The unique constraint is (actor_id, candidate_handle, method); a
        # retried handle is walked forward rather than aborting the seeder.
        while (str(actor.actor_id), handle, method) in seen:
            handle = f"{handle}{rng.randint(2, 9)}"
        seen.add((str(actor.actor_id), handle, method))

        # "any" alternates so a proposal is as likely to be a lightly-migrated
        # persona as a heavily rewritten one.
        want_other = band == "low" or (band == "any" and cursor % 2 == 0)
        options = (
            other_actor_options(corpus_actor)
            if want_other
            else same_actor_options(corpus_actor)
        )
        options = options[cursor % 3 :] + options[: cursor % 3]

        chosen: tuple[str, str, str] | None = None
        for _corpus_id, alias_id, stack in options:
            try:
                result = (
                    score_stylometry(
                        documents[known_alias], _migrate(documents[alias_id], stack)
                    )
                    if method == "stylometry"
                    else score_behaviour(
                        _behaviour_events(known_alias, alias_by_id, posts_by_alias, rhythm),
                        _behaviour_events(alias_id, alias_by_id, posts_by_alias, rhythm),
                    )
                )
            except SampleTooShort:
                continue
            if band == "any" or (
                band == "high" and result.score >= LINKAGE_SCORE_THRESHOLD
            ) or (band == "low" and result.score < LINKAGE_SCORE_THRESHOLD):
                chosen = (alias_id, stack, result)
                break
            # Remember the best effort so a band the samples cannot reach still
            # produces a row, recorded honestly below rather than dropped.
            if chosen is None or abs(result.score - LINKAGE_SCORE_THRESHOLD) < abs(
                chosen[2].score - LINKAGE_SCORE_THRESHOLD
            ):
                chosen = (alias_id, stack, result)
        if chosen is None:
            counts["unplanned"] += 1
            continue

        alias_id, stack, result = chosen
        counts[disposition] += 1
        adjudicated = disposition != "proposed"
        analyst = analysts[rng.randrange(len(analysts))] if adjudicated else None
        high = result.score >= LINKAGE_SCORE_THRESHOLD
        rationale = (
            rng.choice(_RATIONALES[(disposition, "high" if high else "low")])
            if adjudicated
            else None
        )
        metadata = {
            "synthetic": True,
            "schema_version": SCHEMA_VERSION,
            "planned_band": band,
            "scored_high": high,
            "migration_stack": stack,
            "corpus_actor": corpus_actor,
            "corpus_candidate_alias": alias_id,
            **result.metadata,
        }
        rows.append(
            PersonaLinkageRecord(
                linkage_id=sid(
                    f"persona-linkage-seed:{actor.actor_id}:{handle}:{method}:{cursor}"
                ),
                actor_id=actor.actor_id,
                candidate_handle=handle,
                method=method,
                score=result.score,
                status=disposition,
                aligned_features=list(result.aligned),
                apart_features=list(result.apart),
                contested_features=list(result.contested),
                limitations=[
                    *result.limitations,
                    "Synthetic demonstration record: the score was computed by "
                    f"{result.scorer} over the platform's own synthetic corpus, not over "
                    "collected evidence from a real investigation.",
                ],
                case_id=case_ids[rng.randrange(len(case_ids))] if case_ids else None,
                # `ck_persona_linkage_adjudicated` refuses a confirmed/rejected
                # row without both, which is the constraint working.
                adjudicated_by=analyst.user_id if analyst else None,
                adjudicated_at=(
                    now - timedelta(days=rng.randint(1, 75), hours=rng.randint(0, 23))
                    if analyst
                    else None
                ),
                rationale=rationale,
                created_at=now - timedelta(days=rng.randint(0, 120), hours=rng.randint(0, 23)),
                metadata_json=metadata,
            )
        )
        if analyst is not None:
            AuditService(db).record(
                "persona.linkage_adjudicated",
                entity_type="persona_linkage",
                entity_id=str(rows[-1].linkage_id),
                case_id=rows[-1].case_id,
                actor_id=analyst.user_id,
                payload={
                    "synthetic": True,
                    "schema_version": SCHEMA_VERSION,
                    "from_status": "proposed",
                    "to_status": disposition,
                    "analyst": analyst.display_name,
                    "rationale": rationale,
                    "method": method,
                    "score_at_decision": result.score,
                    "candidate_handle": handle,
                    "actor_id": str(actor.actor_id),
                },
                occurred_at=rows[-1].adjudicated_at,
            )
    _flush_batches(db, rows)

    return {
        "persona_linkages": len(rows),
        "persona_linkages_proposed": counts["proposed"],
        "persona_linkages_confirmed": counts["confirmed"],
        "persona_linkages_rejected": counts["rejected"],
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


# ---------------------------------------------------------------------------
# Tor hidden-service infrastructure
#
# The problem statement's first capability: find misconfigurations in Tor
# hidden services and point at the clearnet infrastructure behind them.
#
# The correlations here are **derived, not authored**. Every observation is
# built as a real feature payload, reconstructed through
# ``aegis.infrastructure.extract``, and scored by
# ``aegis.infrastructure.correlate.correlate_all`` — the same code the API
# runs. Only the candidates the library actually returns are persisted, and
# each is stored with the per-channel breakdown it produced. A hand-written
# ``overall: 0.9`` here would be a number the platform could not reproduce
# from the features beside it, which is the one thing this dataset must not
# contain.
# ---------------------------------------------------------------------------

#: The decision rule these correlations are run under.
#:
#: ``min_similarity`` is 0.42 rather than the library's 0.60 default, and that
#: is deliberate: at 0.60 a certificate-only match cannot clear the bar,
#: because a shared certificate with nothing else in common scores 0.30 of a
#: possible 1.00. The weakest correlation an analyst would still want to see
#: is exactly that one, and it is also the one most likely to be shared
#: hosting — so it belongs in the register, labelled as the single-channel
#: finding it is, rather than being hidden above an arbitrary line.
#:
#: 0.42 sits in a measured gap. Over this corpus the four linked pairs score
#: 0.46, 0.64, 0.83 and 0.83, and the highest-scoring *unrelated* pair
#: reaches 0.40. The cut is placed between those, not tuned to make a
#: particular number appear.
INFRA_CORRELATION_THRESHOLDS = CorrelationThresholds(
    min_similarity=0.42,
    min_certificate=0.9,
    min_content=0.8,
    min_http=0.9,
    min_temporal_overlap=0.0,
    require_temporal_overlap=True,
)

INFRA_CA_POOL: tuple[str, ...] = (
    "C=Synthetic Root CA X1, O=Synthetic Trust Services",
    "C=Synthetic Tier Two CA B, O=Synthetic Registrar",
    "C=Synthetic CA Gamma, O=Synthetic Hosting Authority",
    "C=Synthetic Edge CA, O=Synthetic CDN Operations",
    "C=Synthetic Development CA, O=Synthetic Lab",
    "C=Synthetic Private CA, O=Synthetic Hosting Authority",
)

#: Unmodified product banners. A hidden service still advertising one of these
#: has told us its software and nothing else — which is a real (if minor)
#: exposure, and is served identically by thousands of unrelated hosts.
INFRA_DEFAULT_BANNERS: tuple[str, ...] = (
    "Apache/2.4.41 (Ubuntu)",
    "Apache/2.4.54 (Debian)",
    "nginx/1.18.0 (Ubuntu)",
    "nginx/1.24.0",
    "lighttpd/1.4.69",
)

#: Deliberately non-default tokens: an operator who has at least changed the
#: banner. The detector must be able to tell the two apart, or "default
#: banner" would fire on every observation in the table.
INFRA_CUSTOM_BANNERS: tuple[str, ...] = (
    "nginx/1.24.0 (edge-mirror)",
    "cloudflare",
    "Caddy",
    "nginx (no version)",
    "openresty/1.21.4.1",
)

INFRA_CONTENT_TYPES: tuple[str, ...] = (
    "text/html; charset=utf-8",
    "text/html",
    "application/xhtml+xml",
    "text/plain; charset=utf-8",
    "application/json",
    "text/html; charset=iso-8859-1",
)

INFRA_HEADER_POOL: tuple[str, ...] = (
    "server",
    "date",
    "content-type",
    "content-length",
    "x-powered-by",
    "x-frame-options",
    "strict-transport-security",
    "set-cookie",
    "x-request-id",
    "cf-ray",
    "x-cache",
    "accept-ranges",
    "etag",
    "last-modified",
)

INFRA_TECH_POOL: tuple[str, ...] = (
    "nginx:1.24.0",
    "apache:2.4.41",
    "php:8.1",
    "python:3.11",
    "openssl:3.0.11",
    "debian:11",
    "ubuntu:22.04",
    "cloudflare",
    "jquery:3.6.0",
    "bootstrap:5.2",
    "wordpress:6.4",
    "react:18.2",
    "let\'s-encrypt",
    "docker:24.0",
    "haproxy:2.8",
    "envoy:1.27",
)

INFRA_TLS_VERSIONS: tuple[str, ...] = ("TLSv1.2", "TLSv1.3", "TLSv1.3", "TLSv1.2")

INFRA_CIPHER_POOL: tuple[str, ...] = (
    "TLS_AES_256_GCM_SHA384",
    "TLS_AES_128_GCM_SHA256",
    "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
    "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
    "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305",
    "TLS_DHE_RSA_WITH_AES_256_GCM_SHA384",
)

#: Subjects per network. The problem statement's register is a small set of
#: hidden services and a larger set of clearnet hosts, not the other way round.
INFRA_ONION_SUBJECTS = 27
INFRA_CLEARNET_SUBJECTS = 20

#: Observations kept deliberately old so the timeline filters have something to
#: exclude. These windows are disjoint from the recent ones, so the library's
#: temporal gate correctly refuses to correlate them with anything current —
#: which is the honest outcome and not a gap in the data.
INFRA_STALE_OBSERVATIONS = 5

#: A second observation of the same subject, with different TLS metadata. A
#: v3 onion address resolves to one key and should not change its client
#: fingerprint between two observations days apart.
INFRA_DRIFT_SUBJECTS = 2

#: Body markers of a reachable server-status endpoint. The finding fires on the
#: body that was actually stored, not on a guess about the product.
INFRA_STATUS_MARKERS: tuple[tuple[str, str], ...] = (
    ("Apache Server Status for", "/server-status"),
    ("nginx stub_status", "/nginx_status"),
    ("Server-status page", "/status"),
)


def _infra_onion_address(label: str) -> str:
    """A syntactically shaped v3 onion address derived from ``label``.

    56 lowercase base32 characters, which is what a v3 address looks like.
    It is *not* a reachable service: the seeder performs no key generation and
    makes no network claim, and the corpus is synthetic throughout.
    """
    raw = hashlib.sha256(f"aegis-onion:{label}".encode()).digest()
    return base64.b32encode(raw).decode().casefold().rstrip("=")[:56]


def _infra_clearnet_host(label: str) -> str:
    token = digest("host", label)[:8]
    return f"{label}{token}.example"


#: Consonant pairs used to synthesise per-subject vocabulary. Real words are
#: deliberately *not* reused across pages: SimHash weights a word token
#: above a character 3-gram, so a shared word like "rotation" pulls two
#: unrelated services towards each other on the content channel, and the
#: absence of a correlation then stops meaning anything.
_INFRA_SYLLABLES: tuple[str, ...] = (
    "ka", "ro", "mi", "ta", "ne", "su", "lo", "vi", "da", "pu",
    "ze", "na", "gi", "ho", "we", "fu", "qa", "be", "cy", "mo",
)


def _infra_word(label: str, index: int) -> str:
    """A vocabulary item that belongs to exactly one subject."""
    raw = digest("word", f"{label}:{index}")
    return "".join(
        _INFRA_SYLLABLES[int(raw[position * 2 : position * 2 + 2], 16) % 20]
        for position in range(4)
    )


def _infra_page(label: str) -> str:
    """A body of page text, lexically its own.

    Every token is derived from ``label``, so two subjects share no words and
    the content channel reports what it should: that they do not correlate.
    The words look like words because they are assembled from syllables, and
    that is what makes the near-duplicate case below distinguishable from
    this one.
    """
    words = [_infra_word(label, index) for index in range(96)]
    lines: list[str] = []
    for start in range(0, 96, 6):
        line = " ".join(words[start : start + 6])
        # The address appears three times in the page. A mirror substitutes
        # exactly these, and the length of everything around them is what
        # makes the remainder of the page survive as shared shingles.
        if start in (0, 36, 72):
            line = f"{line} {label}"
        lines.append(line)
    return " ".join(lines)


def _infra_mirror_page(subject: str, mirrored_from: str) -> str:
    """The same page with the subject substituted throughout — a real mirror.

    A mirror changes the address it is served at and very little else, which
    is exactly the shape the near-duplicate content channel is meant to catch.
    Building it by substitution rather than by copying a template keeps the
    simhash honest: every remaining difference is a real one.
    """
    return _infra_page(mirrored_from).replace(mirrored_from, subject)


def _infra_partial_page(label: str, other: str) -> str:
    """Half of ``other``'s wording, so a pair scores partly similar.

    This is the profile of a service that publishes a *copy* of another
    operator's page: recognisably the same material, with its own data. It
    lands well below the near-duplicate cutoff and well above the noise floor,
    which is the region where a certificate match has to be read carefully
    rather than acted on.
    """
    right = _infra_page(other).split()
    left = _infra_page(label).split()
    return " ".join(right[: max(1, len(right) // 2)] + left)


@dataclass
class PlannedInfraObservation:
    """One hidden service or clearnet host, with its observed metadata."""

    #: The database observation id, as a string. ``correlate_all`` returns
    #: these verbatim as the endpoints of every candidate, so it has to be the
    #: primary key the record is written under and not a separate label.
    key: str
    subject: str
    network: str
    case: CaseRecord
    source: SourceRecord
    observed: datetime
    window_end: datetime
    tls: dict[str, Any]
    http: dict[str, Any]
    certificate: dict[str, Any]
    technologies: list[str]
    body: str
    evidence_id: UUID
    #: True when this observation repeats an earlier one of the same subject.
    repeat_of: str | None = None

    def payload(self) -> dict[str, Any]:
        """The extraction payload, in the library's own shape."""
        return {
            "observation_id": self.key,
            "evidence_ids": [str(self.evidence_id)],
            "subject": self.subject,
            "subject_type": (
                str(EntityType.ONION_SERVICE)
                if self.network == "onion"
                else str(EntityType.DOMAIN)
            ),
            "source": self.source.name,
            "observed_range": {
                "start": self.observed.isoformat(),
                "end": self.window_end.isoformat(),
            },
            "tls": dict(self.tls),
            "http": dict(self.http),
            "certificate": dict(self.certificate),
            "technologies": list(self.technologies),
            "body": self.body,
        }

    def features(self) -> InfrastructureFeatures:
        """Round-trip the payload through the library, not around it."""
        return extract_features(extract_observation(self.payload()))


def _infra_subject_plan(
    rng: random.Random,
    now: datetime,
    cases: list[CaseRecord],
    sources: list[SourceRecord],
    index: int,
    network: str,
    label: str,
) -> PlannedInfraObservation:
    """One observation, with every channel differentiated from its neighbours.

    Unrelated services are kept apart *structurally* — different certificate
    issuer, different server token, disjoint header sets, different cipher,
    different technology pair — so that the absence of a correlation is a
    property of the data rather than a lucky threshold. A seeder that let
    random chance separate its services would produce a register whose
    negatives mean nothing.
    """
    subject = _infra_onion_address(label) if network == "onion" else _infra_clearnet_host(label)
    stale = index >= (INFRA_ONION_SUBJECTS + INFRA_CLEARNET_SUBJECTS) - INFRA_STALE_OBSERVATIONS
    if stale:
        observed = now - timedelta(days=rng.randint(150, 260), hours=rng.randint(0, 23))
        window_end = observed + timedelta(days=rng.randint(4, 12))
    else:
        observed = now - timedelta(days=rng.randint(1, 34), hours=rng.randint(0, 23))
        window_end = observed + timedelta(days=rng.randint(8, 30))

    fingerprint = digest("cert", label)
    spki = digest("spki", label)
    serial = f"{int(digest('serial', label)[:12], 16):012X}"
    issuer = INFRA_CA_POOL[index % len(INFRA_CA_POOL)]
    # A minority of hidden services present a certificate naming a *clearnet*
    # domain rather than their own onion address. That is the ordinary shape
    # of a mirror or a cloned front end, and it is the observation the
    # ``clearnet_certificate`` detector is about.
    clearnet_named = network == "onion" and index % 8 == 3
    if network == "clearnet":
        sans = [subject]
    elif clearnet_named:
        sans = [f"www.{_infra_clearnet_host(label)}"]
    else:
        sans = [f"{digest('san', label)[:16]}.onion"]
    cert_subject = f"CN={sans[0]}"
    # A few certificates are already expired at the moment of observation —
    # a genuine, checkable descriptor inconsistency rather than an opinion.
    # The validity window is built outwards from `not_after` in both cases so
    # `not_before` can never land after it.
    expired = index % 11 == 4
    not_after = (
        observed - timedelta(days=rng.randint(1, 40))
        if expired
        else observed + timedelta(days=rng.randint(40, 400))
    )
    not_before = not_after - timedelta(days=rng.randint(30, 400))

    status_body = index % 7 == 2
    body = _infra_page(label)
    if status_body:
        marker, path = INFRA_STATUS_MARKERS[index % len(INFRA_STATUS_MARKERS)]
        body = f"{body} {marker} {label} path={path} active connections"

    default_banner = index % 3 == 0
    server = (
        INFRA_DEFAULT_BANNERS[index % len(INFRA_DEFAULT_BANNERS)]
        if default_banner
        else INFRA_CUSTOM_BANNERS[index % len(INFRA_CUSTOM_BANNERS)]
    )

    return PlannedInfraObservation(
        key=str(sid(f"infra-observation:{label}")),
        subject=subject,
        network=network,
        case=cases[index % len(cases)],
        source=sources[index % len(sources)],
        observed=observed,
        window_end=window_end,
        tls={
            "version": INFRA_TLS_VERSIONS[index % len(INFRA_TLS_VERSIONS)],
            "cipher_suite": INFRA_CIPHER_POOL[index % len(INFRA_CIPHER_POOL)],
            "alpn": ["h2", "http/1.1"] if index % 3 == 0 else ["http/1.1"],
            # Unique per subject, so a JA3 is shared only where the seeder
            # deliberately copies one.
            "ja3": digest("ja3", label)[:32],
        },
        http={
            "status_code": 200,
            "server": server,
            "content_type": INFRA_CONTENT_TYPES[index % len(INFRA_CONTENT_TYPES)],
            # A rotating window over the header pool, so two unrelated hosts
            # share almost no header names.
            "headers": {
                name: "synthetic"
                for name in INFRA_HEADER_POOL[index % 7 : (index % 7) + 6]
            },
        },
        certificate={
            "fingerprint_sha256": fingerprint,
            "subject": cert_subject,
            "issuer": issuer,
            "serial_number": serial,
            "not_before": not_before.isoformat(),
            "not_after": not_after.isoformat(),
            "sans": sans,
            "spki_sha256": spki,
        },
        technologies=[
            INFRA_TECH_POOL[index % len(INFRA_TECH_POOL)],
            INFRA_TECH_POOL[(index * 7 + 3) % len(INFRA_TECH_POOL)],
        ],
        body=body,
        evidence_id=sid(f"infra-evidence:{label}"),
    )


def _infra_link(
    onion: PlannedInfraObservation,
    clearnet: PlannedInfraObservation,
    mode: str,
) -> None:
    """Make one hidden service genuinely resemble one clearnet host.

    The point of each mode is a *different* kind of corroboration, so the
    register shows a range rather than one number repeated:

    ``mirror``
        the operator is serving the same certificate, the same software and
        the same page from both addresses. Corroborated on every channel.
    ``certificate``
        the same certificate and nothing else — the shape shared hosting,
        a migration and a copied key all produce. One decisive channel.
    ``template``
        the same header profile, the same client fingerprint and the same
        software, on a different certificate. Corroborated on the commodity
        channels, which cannot on their own start a correlation.
    """
    if mode in {"mirror", "certificate"}:
        onion.certificate = dict(clearnet.certificate)
    if mode == "mirror":
        onion.http = dict(clearnet.http)
        onion.tls = dict(clearnet.tls)
        onion.technologies = list(clearnet.technologies)
        onion.body = _infra_mirror_page(onion.subject, clearnet.subject)
    elif mode == "template":
        onion.http = dict(clearnet.http)
        onion.tls = dict(clearnet.tls)
        onion.technologies = list(clearnet.technologies)
    else:  # "certificate"
        onion.body = _infra_partial_page(onion.subject, clearnet.subject)


def _infra_findings(
    observations: list[PlannedInfraObservation],
    matches: tuple[InfrastructureCorrelation, ...],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Every finding, each one read off the features it is about.

    Nothing here is decided by a coin flip and then described: a finding is
    filed because a stored field says so, and the ``detail`` names that field.
    """
    findings: list[dict[str, Any]] = []
    by_subject = {item.subject: item for item in observations}

    for plan in observations:
        subject = plan.subject
        sans = [str(name) for name in (plan.certificate.get("sans") or [])]
        clearnet_sans = [name for name in sans if not name.endswith(".onion")]
        cert_subject = str(plan.certificate.get("subject") or "")
        if not cert_subject.endswith(".onion"):
            clearnet_sans.append(cert_subject)
        if plan.network == "onion" and clearnet_sans:
            findings.append(
                {
                    "key": f"infra-finding:{plan.key}:clearnet-cert",
                    "plan": plan,
                    "kind": "clearnet_certificate",
                    "severity": "high",
                    "confidence": 0.85,
                    "detected_at": plan.window_end,
                    "detail": (
                        f"The certificate served by {subject[:16]}… carries the SAN "
                        f"{', '.join(clearnet_sans)}, a clearnet name rather than an "
                        "onion address. The operator of the hidden service therefore "
                        "holds a certificate for a public domain."
                    ),
                    "limitations": [
                        "A hidden service serving a clearnet certificate is ordinary "
                        "practice for a mirror or a phishing front: it shows the "
                        "operator controls that domain, not that the onion address "
                        "and the domain are the same host.",
                        "A wildcard or shared-hosting certificate produces the same "
                        "SAN list on thousands of unrelated hosts.",
                        "The certificate was read from stored traffic; no live "
                        "connection was made to the service.",
                    ],
                }
            )

        server = str(plan.http.get("server") or "")
        if server in INFRA_DEFAULT_BANNERS:
            findings.append(
                {
                    "key": f"infra-finding:{plan.key}:default-banner",
                    "plan": plan,
                    "kind": "default_banner",
                    "severity": "low",
                    "confidence": 0.7,
                    "detected_at": plan.window_end,
                    "detail": (
                        f"{subject[:16]}… still advertises the unmodified product banner "
                        f"'{server}'. The software and its exact version are being "
                        "published to anyone who requests the page."
                    ),
                    "limitations": [
                        "The same default banner is served by a very large number of "
                        "unrelated hosts, so this identifies almost nothing on its own.",
                        "A version string is trivial to change or forge; a non-default "
                        "banner is not evidence of a customised deployment.",
                    ],
                }
            )

        for marker, path in INFRA_STATUS_MARKERS:
            if marker in plan.body:
                findings.append(
                    {
                        "key": f"infra-finding:{plan.key}:status-page",
                        "plan": plan,
                        "kind": "exposed_status_page",
                        "severity": "medium",
                        "confidence": 0.95,
                        "detected_at": plan.window_end,
                        "detail": (
                            f"The stored response for {subject[:16]}… contains the body of "
                            f"a server-status page ('{marker}', served at {path}) with an "
                            "HTTP 200. Connection counts, request rates and the worker "
                            "process table were readable without authentication."
                        ),
                        "limitations": [
                            "Many web products expose a status endpoint deliberately and "
                            "on purpose; reachability is a configuration choice, not "
                            "evidence of negligence or of who operates the service.",
                            "On a shared host the page may belong to the host operator "
                            "rather than to the hidden service that sits in front of it.",
                            "This is one observation at one moment. Whether the endpoint "
                            "was still open when the analyst read this record is not "
                            "established here.",
                        ],
                    }
                )
                break

        not_after = str(plan.certificate.get("not_after") or "")
        if not_after and not_after < plan.observed.isoformat():
            findings.append(
                {
                    "key": f"infra-finding:{plan.key}:expired-cert",
                    "plan": plan,
                    "kind": "descriptor_inconsistency",
                    "severity": "medium",
                    "confidence": 0.8,
                    "detected_at": plan.window_end,
                    "detail": (
                        f"The certificate observed on {subject[:16]}… expired at {not_after}, "
                        f"before the observation window that begins {plan.observed.isoformat()} "
                        "opened. The service is presenting a certificate outside its own "
                        "validity period."
                    ),
                    "limitations": [
                        "An expired certificate proves the presented chain is out of date; "
                        "it does not identify who operates the service or on whose behalf.",
                        "A client that ignores validity dates will still complete the "
                        "connection, so an expired certificate is not necessarily observed "
                        "by a visitor.",
                    ],
                }
            )

    # A second observation of the same subject carrying different TLS metadata
    # is a descriptor inconsistency: a v3 onion address resolves to one key.
    repeats: dict[str, list[PlannedInfraObservation]] = {}
    for plan in observations:
        repeats.setdefault(plan.subject, []).append(plan)
    for subject, plans in repeats.items():
        if len(plans) < 2:
            continue
        first, second = plans[0], plans[1]
        changed = [
            key
            for key in ("version", "cipher_suite", "ja3")
            if first.tls.get(key) != second.tls.get(key)
        ]
        if not changed:
            continue
        findings.append(
            {
                "key": f"infra-finding:{subject}:drift",
                "plan": second,
                "kind": "descriptor_inconsistency",
                "severity": "medium",
                "confidence": 0.5,
                "detected_at": second.window_end,
                "detail": (
                    f"{subject[:16]}… was observed twice inside overlapping windows with "
                    f"different TLS metadata ({', '.join(changed)}). A v3 onion address "
                    "resolves to a fixed key, so the client fingerprint for the same "
                    "service should be stable between observations."
                ),
                "limitations": [
                    "Two different collectors, proxies or vantage points can present "
                    "different client metadata for one unchanged service, so this may be "
                    "an observation artefact rather than a change in the service.",
                    "The observation does not establish which description is the correct "
                    "one, or whether the service changed at all.",
                ],
            }
        )

    # Shared fingerprints, straight from the correlations the library returned.
    for candidate in matches:
        if candidate.strong_channel != "certificate":
            continue
        findings.append(
            {
                "key": f"infra-finding:{candidate.left_observation_id}:shared-cert",
                "plan": by_subject.get(candidate.left_subject),
                "kind": "shared_fingerprint",
                "severity": "high",
                # Deliberately unscored. The platform will not put a number on
                # "these two certificates are the same certificate", because the
                # number would be read as a probability of common control and it
                # is not one.
                "confidence": None,
                "detected_at": candidate.time_range.end,
                "detail": (
                    f"The certificate fingerprint presented by {candidate.left_subject[:16]}… "
                    f"is byte-identical to the one presented by "
                    f"{candidate.right_subject[:16]}…, scoring "
                    f"{candidate.breakdown.certificate:.2f} on the certificate channel and "
                    f"{candidate.similarity:.2f} overall."
                ),
                "limitations": [
                    "An identical certificate is what shared hosting, a CDN terminating "
                    "TLS, a migration between hosts, and a single operator serving both "
                    "addresses all look like. It does not establish common control.",
                    "A hosting provider that reuses one certificate across every tenant "
                    "will produce this signal for unrelated services.",
                    "Passive comparison of stored observations only; no connection was "
                    "made to either subject and no origin discovery was performed.",
                ],
            }
        )

    # A handful of findings are backdated well beyond the recent window so the
    # timeline control has stale records to exclude. The underlying detection
    # is real; only the detection timestamp is moved, and it is moved to the
    # observation it was actually derived from.
    for index, finding in enumerate(findings):
        if index % 7 == 3:
            finding["detected_at"] = finding["detected_at"] - timedelta(days=190)
    rng.shuffle(findings)
    return findings


def seed_infrastructure(
    db: Session,
    sources: list[SourceRecord],
    cases: list[CaseRecord],
    rng: random.Random,
    now: datetime,
) -> dict[str, int]:
    """Observations, misconfigurations and derived onion-to-clearnet matches.

    Foreign-key order is the same rule as the rest of this seeder: evidence
    (every observation cites one, and an observation without evidence is not
    scoreable), then observations, then findings and matches, which reference
    the observations.
    """
    plans: list[PlannedInfraObservation] = []
    for index in range(INFRA_ONION_SUBJECTS):
        plans.append(
            _infra_subject_plan(rng, now, cases, sources, index, "onion", f"onion-{index:02d}")
        )
    for index in range(INFRA_CLEARNET_SUBJECTS):
        plans.append(
            _infra_subject_plan(
                rng,
                now,
                cases,
                sources,
                INFRA_ONION_SUBJECTS + index,
                "clearnet",
                f"host-{index:02d}",
            )
        )

    # Recent subjects only: the library's temporal gate refuses to correlate
    # two windows that share no instant, and a deliberately stale pair would
    # be refused for the right reason and teach nothing.
    cutoff = now - timedelta(days=60)
    recent_onion = [p for p in plans if p.network == "onion" and p.observed > cutoff]
    recent_clear = [p for p in plans if p.network == "clearnet" and p.observed > cutoff]
    link_modes = ("mirror", "certificate", "template", "mirror")
    for position, mode in enumerate(link_modes):
        onion = recent_onion[position * 3 + 1]
        clearnet = recent_clear[position * 4 + 2]
        # A mirror is served while the origin is up, so the two observation
        # windows are set to the same interval. Left to chance they would
        # barely overlap, and the library's temporal gate would be the thing
        # deciding whether these pairs correlate — which is a statement about
        # the seeder's dice rather than about the infrastructure.
        onion.observed = clearnet.observed
        onion.window_end = clearnet.window_end
        _infra_link(onion, clearnet, mode)

    # Repeat observations of two subjects, with different TLS metadata.
    for position in range(INFRA_DRIFT_SUBJECTS):
        original = recent_clear[position * 5 + 4]
        repeat = PlannedInfraObservation(
            key=str(sid(f"{original.key}:repeat")),
            subject=original.subject,
            network=original.network,
            case=original.case,
            source=sources[(len(sources) - 1 - position) % len(sources)],
            observed=original.observed + timedelta(days=2, hours=3),
            window_end=original.window_end + timedelta(hours=6),
            tls={**original.tls, "ja3": digest("ja3-drift", original.key)[:32]},
            http=dict(original.http),
            certificate=dict(original.certificate),
            technologies=list(original.technologies),
            body=original.body,
            evidence_id=sid(f"infra-evidence:{original.key}:repeat"),
            repeat_of=original.key,
        )
        plans.append(repeat)

    # Evidence first: `infrastructure_observations.evidence_id` is a real
    # foreign key, and the correlation adapter refuses to score an
    # observation that cites nothing.
    evidence: list[EvidenceRecord] = []
    for plan in plans:
        evidence.append(
            EvidenceRecord(
                evidence_id=plan.evidence_id,
                case_id=plan.case.case_id,
                source_id=plan.source.source_id,
                source_type=plan.source.source_type,
                observed_at=plan.observed,
                collected_at=plan.window_end,
                entity_type="infrastructure",
                entity_value_hash=digest("infra-entity", plan.subject)[:64],
                context_hash=digest("infra-context", plan.key)[:64],
                raw_artifact_uri=f"synthetic://aegis/{plan.case.case_id}/infrastructure/{plan.key}",
                artifact_id=None,
                sha256=digest("infra-body", plan.body),
                collector_name=f"synthetic-infrastructure-{plan.network}",
                collector_version="1.0.0",
                normalizer_version="1.3.0",
                extraction_version="2.2.0",
                source_reliability=plan.source.reliability,
                independence_group=str(
                    (plan.source.metadata_json or {}).get("independence_group", "demo")
                ),
                metadata_json={
                    "synthetic": True,
                    "schema_version": SCHEMA_VERSION,
                    "title": f"Infrastructure observation · {plan.subject[:24]}",
                    "summary": (
                        f"Passive {plan.network} observation of {plan.subject[:24]} from "
                        f"{plan.source.name}."
                    ),
                    "modality": "infrastructure",
                    "surface_form": plan.subject,
                },
            )
        )
    _flush_batches(db, evidence)

    records: list[InfrastructureObservationRecord] = []
    for plan in plans:
        record = InfrastructureObservationRecord(
            observation_id=UUID(plan.key),
            subject=plan.subject,
            network=plan.network,
            source=plan.source.name,
            observed_at=plan.observed,
            features_json=features_document(
                observation_id=plan.key,
                evidence_ids=[str(plan.evidence_id)],
                subject=plan.subject,
                subject_type=str(
                    EntityType.ONION_SERVICE if plan.network == "onion" else EntityType.DOMAIN
                ),
                source=plan.source.name,
                observed_range={
                    "start": plan.observed.isoformat(),
                    "end": plan.window_end.isoformat(),
                },
                tls=plan.tls,
                http=plan.http,
                certificate=plan.certificate,
                technologies=plan.technologies,
                body=plan.body,
            ),
            evidence_id=plan.evidence_id,
            case_id=plan.case.case_id,
            metadata_json={
                "synthetic": True,
                "schema_version": SCHEMA_VERSION,
                "repeat_of": plan.repeat_of,
                "source_id": str(plan.source.source_id),
            },
        )
        records.append(record)
    _flush_batches(db, records)

    # Score every pair with the library. The candidates it returns are the
    # matches; nothing is asserted here that the library did not produce.
    feature_views = [plan.features() for plan in plans]
    candidates = correlate_all(feature_views, thresholds=INFRA_CORRELATION_THRESHOLDS)

    network_by_id = {plan.key: plan.network for plan in plans}
    plan_by_id = {plan.key: plan for plan in plans}
    match_rows: list[InfrastructureMatchRecord] = []
    for candidate in candidates:
        left = candidate.left_observation_id
        right = candidate.right_observation_id
        if network_by_id[left] == network_by_id[right]:
            continue
        onion, clearnet = (
            (left, right) if network_by_id[left] == "onion" else (right, left)
        )
        detected = max(
            plan_by_id[onion].window_end,
            plan_by_id[clearnet].window_end,
        )
        match_rows.append(
            InfrastructureMatchRecord(
                match_id=sid(f"infra-match:{left}:{right}"),
                onion_observation_id=onion,
                clearnet_observation_id=clearnet,
                case_id=plan_by_id[onion].case.case_id,
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
                detected_at=detected,
                metadata_json={
                    "synthetic": True,
                    "schema_version": SCHEMA_VERSION,
                    "relationship_type": str(candidate.relationship_type),
                    "sources": list(candidate.sources),
                    "evidence_ids": list(candidate.evidence_ids),
                    "time_range": {
                        "start": candidate.time_range.start.isoformat(),
                        "end": candidate.time_range.end.isoformat(),
                    },
                    "thresholds": {
                        "min_similarity": INFRA_CORRELATION_THRESHOLDS.min_similarity,
                        "min_certificate": INFRA_CORRELATION_THRESHOLDS.min_certificate,
                        "min_content": INFRA_CORRELATION_THRESHOLDS.min_content,
                        "min_http": INFRA_CORRELATION_THRESHOLDS.min_http,
                        "min_temporal_overlap": INFRA_CORRELATION_THRESHOLDS.min_temporal_overlap,
                        "require_temporal_overlap": (
                            INFRA_CORRELATION_THRESHOLDS.require_temporal_overlap
                        ),
                    },
                },
            )
        )
    _flush_batches(db, match_rows)

    cross_network = tuple(
        candidate
        for candidate in candidates
        if network_by_id[candidate.left_observation_id]
        != network_by_id[candidate.right_observation_id]
    )
    findings = _infra_findings(plans, cross_network, rng)
    finding_rows: list[InfrastructureFindingRecord] = []
    for finding in findings:
        plan = finding["plan"]
        if plan is None:
            continue
        finding_rows.append(
            InfrastructureFindingRecord(
                finding_id=sid(finding["key"]),
                observation_id=UUID(plan.key),
                case_id=plan.case.case_id,
                kind=finding["kind"],
                severity=finding["severity"],
                detail=finding["detail"],
                limitations=list(finding["limitations"]),
                # `None` is stored, not 0: an unscored detector has to be
                # readable as unscored, and 0 would read as "certainly not".
                confidence=finding["confidence"],
                detected_at=finding["detected_at"],
                evidence_id=plan.evidence_id,
                metadata_json={
                    "synthetic": True,
                    "schema_version": SCHEMA_VERSION,
                    "network": plan.network,
                    "surface_form": plan.subject,
                },
            )
        )
    _flush_batches(db, finding_rows)

    db.flush()
    return {
        "infrastructure_observations": len(records),
        "infrastructure_onion_subjects": len({p.subject for p in plans if p.network == "onion"}),
        "infrastructure_clearnet_subjects": len(
            {p.subject for p in plans if p.network == "clearnet"}
        ),
        "infrastructure_findings": len(finding_rows),
        "infrastructure_matches": len(match_rows),
        "infrastructure_candidates": len(candidates),
    }


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

    # After the registry: `persona_linkages.actor_id` is a foreign key onto it.
    # The counts add rather than replace, so the total covers every row in the
    # table regardless of which stage produced it.
    linkage_totals = seed_persona_linkages(db, None, rng, now)
    totals["persona_linkages"] = int(totals["persona_linkages"]) + int(
        linkage_totals.get("persona_linkages", 0)
    )
    # How many of those were *scored* by the stylometry and behaviour functions
    # rather than inserted by another stage.
    totals["persona_linkages_scored"] = linkage_totals.get("persona_linkages", 0)
    totals["persona_linkages_confirmed"] = linkage_totals.get("persona_linkages_confirmed", 0)
    totals["persona_linkages_rejected"] = linkage_totals.get("persona_linkages_rejected", 0)

    # After the cases and sources for the same reason: observations cite real
    # evidence rows, which cite a real source and belong to a real case.
    totals.update(seed_infrastructure(db, sources, cases, rng, now))

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
