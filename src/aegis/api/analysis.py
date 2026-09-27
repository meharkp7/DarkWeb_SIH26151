from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.evidence.artifacts import ArtifactStore
from aegis.evidence.service import EvidenceService
from aegis.schemas.analysis import (
    SyntheticAnalysisRequest,
    SyntheticAnalysisResponse,
)
from aegis.settings import settings
from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLinkEngine
from aegis.synthetic.contradiction import ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.graph import EvidenceGraphBuilder
from aegis.synthetic.hypothesis import AttributionHypothesisBuilder
from aegis.synthetic.hypothesis_persistence import HypothesisPersistenceService
from aegis.synthetic.persistence import SyntheticPersistenceService


def run_synthetic_analysis(
    payload: SyntheticAnalysisRequest,
    db: Session,
) -> SyntheticAnalysisResponse:
    evidence_service = EvidenceService(
        db,
        ArtifactStore(settings.evidence_storage_path),
    )

    actor_generator = SyntheticActorGenerator(seed=payload.seed)
    actors = actor_generator.generate(payload.actor_count)

    evidence_generator = SyntheticEvidenceGenerator(seed=payload.seed)
    evidence, relationships = evidence_generator.generate(actors)

    # Validate the generated evidence graph before analysis.
    EvidenceGraphBuilder().build(evidence, relationships)

    persistence = SyntheticPersistenceService(evidence_service)
    source_id = persistence.create_source()
    persistence.persist_evidence(source_id, actors, evidence)

    candidate_engine = CandidateLinkEngine()
    candidates = candidate_engine.generate(
        evidence,
        min_score=payload.min_score,
    )

    calibrator = ConfidenceCalibrator()
    contradiction_detector = ContradictionDetector()
    hypothesis_builder = AttributionHypothesisBuilder()
    hypothesis_persistence = HypothesisPersistenceService(db)

    hypotheses: list[dict[str, object]] = []

    for candidate in candidates:
        calibrated = calibrator.calibrate(candidate, evidence)
        contradiction = contradiction_detector.analyze(
            candidate,
            evidence,
        )

        hypothesis = hypothesis_builder.build(
            calibrated,
            contradiction,
            evidence,
        )

        hypothesis_db_id = hypothesis_persistence.persist(
            hypothesis,
            contradiction,
        )

        hypotheses.append(
            {
                "hypothesis_id": str(hypothesis_db_id),
                "source_actor_id": hypothesis.source_actor_id,
                "target_actor_id": hypothesis.target_actor_id,
                "raw_score": hypothesis.raw_score,
                "support_score": hypothesis.support_score,
                "contradiction_score": hypothesis.contradiction_score,
                "final_score": hypothesis.final_score,
                "status": hypothesis.status,
                "evidence_count": len(hypothesis.evidence),
                "explanations": list(hypothesis.explanations),
            }
        )

    return SyntheticAnalysisResponse(
        seed=payload.seed,
        actor_count=len(actors),
        evidence_count=len(evidence),
        relationship_count=len(relationships),
        candidate_count=len(candidates),
        persisted_hypothesis_count=len(hypotheses),
        hypotheses=hypotheses,
    )


def get_analysis_db(
    db: Annotated[Session, Depends(get_db)],
) -> Session:
    return db
