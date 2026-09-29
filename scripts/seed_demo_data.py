"""Seed a rich, deterministic AEGIS demonstration dataset.

All records are synthetic and clearly labelled. This script is for local/demo
use and never performs network collection or real-world attribution.
"""

from __future__ import annotations

import argparse
import hashlib
import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from aegis.db.audit import AuditService
from aegis.db.models import (
    ArtifactRecord,
    AssessmentRecord,
    CaseRecord,
    EntityRecord,
    EvidenceRecord,
    HypothesisLinkRecord,
    HypothesisRecord,
    RelationshipRecord,
    SourceRecord,
)
from aegis.db.session import SessionLocal
from aegis.evidence.search_index import EvidenceSearchIndexer
from aegis.search.opensearch import OpenSearchAdapter
from aegis.settings import settings

NAMESPACE = UUID("4b5a6c7d-8e9f-4012-9345-5a6b7c8d9e01")
CASE_BLUEPRINTS: list[tuple[str, str, str, str, str, list[str], int]] = [
    (
        "Operation Blackbird",
        "Attribution-led investigation across infrastructure and financial overlap; synthetic.",
        "active",
        "critical",
        "critical",
        ["attribution", "infrastructure", "financial"],
        6,
    ),
    (
        "Silver Lantern",
        "Marketplace and hosting correlation with actor handles; synthetic.",
        "active",
        "high",
        "high",
        ["infrastructure", "marketplace"],
        18,
    ),
    (
        "Northstar",
        "Cryptocurrency laundering chain and wallet convergence; synthetic.",
        "active",
        "high",
        "high",
        ["financial", "behavioral"],
        24,
    ),
    (
        "Operation Nightfall",
        "Multi-platform ransomware ecosystem; synthetic training scenario.",
        "active",
        "critical",
        "critical",
        ["ransomware", "attribution"],
        8,
    ),
    (
        "Copper Trace",
        "Cross-source evidence consistency and contradiction scenario; synthetic.",
        "open",
        "medium",
        "medium",
        ["contradiction", "stylometry"],
        72,
    ),
    (
        "Glass Harbor",
        "Forum identity resolution and temporal behavior scenario; synthetic.",
        "on_hold",
        "low",
        "medium",
        ["temporal", "behavioral"],
        120,
    ),
]
SOURCE_BLUEPRINTS = [
    ("forum", "Synthetic Forum Archive", 0.86),
    ("marketplace", "Synthetic Marketplace Mirror", 0.79),
    ("threat_feed", "Synthetic Threat Feed", 0.91),
    ("public_web", "Synthetic Public Web Corpus", 0.74),
    ("analyst_submitted", "Synthetic Analyst Submission", 0.88),
]
ENTITY_KINDS = ["actor", "handle", "domain", "wallet", "infrastructure", "campaign", "forum"]
RELATIONSHIPS = [
    "uses",
    "mentions",
    "controls",
    "communicates_with",
    "funds",
    "resolves_to",
    "overlaps",
]
SIGNALS = ["behavioral", "infrastructure", "financial", "stylometry", "temporal"]
HYPOTHESES_PER_CASE = 5


def sid(label: str) -> UUID:
    return uuid5(NAMESPACE, label)


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def seed(db: Session, evidence_per_case: int) -> dict[str, object]:
    marker = db.scalar(select(CaseRecord).where(CaseRecord.name == "Operation Blackbird"))
    if marker is not None:
        return {"status": 0, "message": "demo dataset already present"}  # type: ignore[return-value]

    rng = random.Random(26151)
    now = datetime.now(UTC)
    sources: list[SourceRecord] = []
    for index, (kind, name, reliability) in enumerate(SOURCE_BLUEPRINTS):
        source = SourceRecord(
            source_id=sid(f"source:{index}"),
            source_type=kind,
            name=name,
            reliability=reliability,
            metadata_json={"synthetic": True, "independence_group": f"demo-{index}"},
        )
        sources.append(source)
    db.add_all(sources)

    cases: list[CaseRecord] = []
    for index, (name, description, status, priority, severity, tags, sla_hours) in enumerate(
        CASE_BLUEPRINTS
    ):
        case = CaseRecord(
            case_id=sid(f"case:{index}"),
            name=name,
            description=description,
            status=status,
            priority=priority,
            severity=severity,
            tags=list(tags),
            sla_due_at=now + timedelta(hours=sla_hours),
        )
        cases.append(case)
    db.add_all(cases)
    db.flush()

    total_entities = total_evidence = total_relationships = total_assessments = 0
    all_evidence_by_case: dict[UUID, list[EvidenceRecord]] = {}
    all_entities_by_case: dict[UUID, list[EntityRecord]] = {}

    for case_index, case in enumerate(cases):
        case_sources = sources[:]
        entities: list[EntityRecord] = []
        evidence_rows: list[EvidenceRecord] = []
        entity_count = 160
        for entity_index in range(entity_count):
            kind = ENTITY_KINDS[entity_index % len(ENTITY_KINDS)]
            name = f"{kind.title()}-{case_index + 1:02d}-{entity_index + 1:03d}"
            entity = EntityRecord(
                entity_id=sid(f"entity:{case.case_id}:{entity_index}"),
                case_id=case.case_id,
                evidence_id=sid(f"evidence:{case.case_id}:0"),
                entity_type=kind,
                surface_form=name,
                normalized_form=name.lower(),
                confidence=round(0.62 + rng.random() * 0.37, 3),
                first_seen=now - timedelta(days=180 - entity_index),
                last_seen=now - timedelta(hours=rng.randint(1, 120)),
                metadata_json={"synthetic": True, "case_index": case_index},
            )
            entities.append(entity)
        all_entities_by_case[case.case_id] = entities

        for evidence_index in range(evidence_per_case):
            source = case_sources[evidence_index % len(case_sources)]
            observed = now - timedelta(hours=rng.randint(1, 24 * 180))
            content_hash = digest(case.case_id, evidence_index, source.source_id)
            evidence = EvidenceRecord(
                evidence_id=sid(f"evidence:{case.case_id}:{evidence_index}"),
                case_id=case.case_id,
                source_id=source.source_id,
                source_type=source.source_type,
                observed_at=observed,
                collected_at=observed + timedelta(minutes=rng.randint(1, 240)),
                entity_type=ENTITY_KINDS[evidence_index % len(ENTITY_KINDS)],
                entity_value_hash=digest("entity", case.case_id, evidence_index),
                context_hash=digest("context", case.case_id, evidence_index),
                raw_artifact_uri=f"synthetic://aegis/{case.case_id}/evidence/{evidence_index}",
                artifact_id=sid(f"artifact:{case.case_id}:{evidence_index}"),
                sha256=content_hash,
                collector_name="synthetic-corpus",
                collector_version="1.0.0",
                normalizer_version="1.2.0",
                extraction_version="2.1.0",
                source_reliability=source.reliability,
                independence_group=f"demo-source-{evidence_index % len(case_sources)}",
                metadata_json={
                    "synthetic": True,
                    "title": f"Synthetic intelligence observation {evidence_index + 1:04d}",
                    "summary": f"Synthetic observation linking entities in {case.name}.",
                    "language": "en",
                    "severity": ["low", "medium", "high"][evidence_index % 3],
                },
            )
            evidence_rows.append(evidence)

        artifacts = [
            ArtifactRecord(
                artifact_id=sid(f"artifact:{case.case_id}:{i}"),
                sha256=e.sha256,
                storage_uri=e.raw_artifact_uri,
                media_type="application/json",
                size_bytes=512 + (i % 17) * 97,
            )
            for i, e in enumerate(evidence_rows)
        ]
        db.add_all(artifacts)
        db.add_all(evidence_rows)
        db.flush()
        # Entity evidence FK points at the deterministic first evidence row; update it
        # after evidence exists so all entity records are valid and queryable.
        for i, entity in enumerate(entities):
            entity.evidence_id = evidence_rows[i % len(evidence_rows)].evidence_id
        db.add_all(entities)
        db.flush()
        all_evidence_by_case[case.case_id] = evidence_rows
        total_evidence += len(evidence_rows)
        total_entities += len(entities)

        relationships: list[RelationshipRecord] = []
        for relation_index in range(entity_count * 2):
            left = entities[(relation_index * 7) % entity_count]
            right = entities[(relation_index * 13 + 3) % entity_count]
            if left.entity_id == right.entity_id:
                continue
            start = now - timedelta(days=rng.randint(2, 160))
            end = start + timedelta(days=rng.randint(1, 90))
            relationships.append(
                RelationshipRecord(
                    relationship_id=sid(f"relationship:{case.case_id}:{relation_index}"),
                    case_id=case.case_id,
                    subject_entity_id=left.entity_id,
                    object_entity_id=right.entity_id,
                    relationship_type=RELATIONSHIPS[relation_index % len(RELATIONSHIPS)],
                    first_seen=start,
                    last_seen=end,
                    valid_from=start,
                    valid_until=end,
                    confidence=round(0.55 + rng.random() * 0.44, 3),
                    evidence_ids=[
                        str(evidence_rows[(relation_index * 3) % len(evidence_rows)].evidence_id)
                    ],
                    metadata_json={"synthetic": True},
                )
            )
        db.add_all(relationships)
        total_relationships += len(relationships)

        for hypothesis_index in range(HYPOTHESES_PER_CASE):
            subject = entities[hypothesis_index % entity_count]
            target = entities[(hypothesis_index * 11 + 7) % entity_count]
            if subject.entity_id == target.entity_id:
                target = entities[(hypothesis_index * 11 + 8) % entity_count]
            score = round(0.42 + rng.random() * 0.55, 4)
            support = round(score * (0.78 + rng.random() * 0.2), 4)
            contradiction = round((1 - score) * rng.random() * 0.7, 4)
            final = round(max(0.0, min(1.0, support - contradiction * 0.35)), 4)
            hypothesis_id = sid(f"hypothesis:{case.case_id}:{hypothesis_index}")
            evidence_ids = [
                str(evidence_rows[(hypothesis_index * 3 + offset) % len(evidence_rows)].evidence_id)
                for offset in range(3)
            ]
            db.add(
                HypothesisRecord(
                    hypothesis_id=hypothesis_id,
                    case_id=case.case_id,
                    subject_entity_id=subject.entity_id,
                    object_entity_id=target.entity_id,
                    kind="attribution",
                    status="supported" if final >= 0.72 else "candidate",
                    missing_evidence=[] if final >= 0.72 else ["independent corroboration"],
                    analyst_disposition=(
                        "Synthetic benchmark hypothesis; not a real-world attribution."
                    ),
                    metadata_json={"synthetic": True},
                )
            )
            db.flush()

            for evidence_id in evidence_ids:
                db.add(
                    HypothesisLinkRecord(
                        hypothesis_id=hypothesis_id,
                        evidence_id=UUID(evidence_id),
                        role="supporting" if final >= 0.72 else "context",
                        modality="synthetic",
                        independence_group="demo",
                        weight=round(0.6 + rng.random() * 0.4, 3),
                    )
                )
            db.add(
                AssessmentRecord(
                    assessment_id=sid(f"assessment:{case.case_id}:{hypothesis_index}"),
                    hypothesis_id=hypothesis_id,
                    case_id=case.case_id,
                    model_id="temporal-hgt-learned",
                    model_version="phase-19.1",
                    raw_score=score,
                    calibrated_confidence=final,
                    calibration_version="synthetic-demo-v1",
                    signals_json={
                        signal: round(0.45 + rng.random() * 0.5, 3) for signal in SIGNALS
                    },
                    supporting_evidence_ids=evidence_ids,
                    contradictory_evidence_ids=[]
                    if final > 0.6
                    else [str(evidence_rows[hypothesis_index].evidence_id)],
                    explanations=[
                        "Synthetic temporal relationship signal.",
                        "Synthetic cross-source corroboration signal.",
                    ],
                    limitations=["Synthetic dataset; no real-world identity inference."],
                )
            )
            total_assessments += 1

        audit = AuditService(db)
        threat_messages = [
            ("relationship.updated", "New infrastructure association detected"),
            ("evidence.collected", "New evidence ingested"),
            ("assessment.updated", "Attribution confidence revised"),
            ("alert.critical", "Critical queue escalation"),
            ("threat.infrastructure", "Infrastructure link surfaced"),
            ("threat.attribution", "Hypothesis support shifted"),
        ]
        for event_index in range(52):
            action, template = threat_messages[event_index % len(threat_messages)]
            actor = entities[event_index % len(entities)]
            infra = entities[(event_index * 5 + 2) % len(entities)]
            audit.record(
                action,
                entity_type="case",
                entity_id=str(case.case_id),
                case_id=case.case_id,
                payload={
                    "synthetic": True,
                    "message": (
                        f"{template} — {actor.surface_form} → {infra.surface_form} "
                        f"({case.name})"
                    ),
                    "severity": "critical" if "critical" in action else "info",
                },
                occurred_at=now - timedelta(minutes=event_index * 11 + case_index * 5),
            )

    db.commit()
    return {
        "cases": len(cases),
        "evidence": total_evidence,
        "entities": total_entities,
        "relationships": total_relationships,
        "assessments": total_assessments,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-per-case", type=int, default=650)
    parser.add_argument(
        "--index", action="store_true", help="also bulk-index synthetic evidence in OpenSearch"
    )
    args = parser.parse_args()
    if args.evidence_per_case < 50:
        raise SystemExit("--evidence-per-case must be >= 50")
    with SessionLocal() as db:
        result = seed(db, args.evidence_per_case)
        print(result)
        if args.index and result.get("evidence", 0):
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
