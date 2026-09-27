from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SyntheticEvidence:
    evidence_id: str
    actor_id: str
    evidence_type: str
    value: str
    confidence: float
    observed_at: datetime
    platform: str
    independence_group: str


@dataclass(frozen=True)
class SyntheticRelationship:
    relationship_id: str
    source_evidence_id: str
    target_evidence_id: str
    relationship_type: str
    confidence: float
