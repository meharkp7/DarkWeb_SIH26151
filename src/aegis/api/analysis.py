import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from aegis.api.deps import get_db
from aegis.db.models import EvidenceRecord
from aegis.evidence.artifacts import ArtifactStore
from aegis.evidence.search_index import EvidenceSearchIndexer
from aegis.evidence.service import EvidenceService
from aegis.schemas.analysis import (
    SyntheticAnalysisRequest,
    SyntheticAnalysisResponse,
)
from aegis.search.opensearch import OpenSearchAdapter
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

logger = logging.getLogger(__name__)


def run_synthetic_analysis(
    payload: SyntheticAnalysisRequest,
    db: Session,
) -> SyntheticAnalysisResponse:
    """Generate a synthetic case, analyze it, and persist the results.

    Transaction shape (review finding): evidence rows are committed in
    one batch by
    :meth:`~aegis.synthetic.persistence.SyntheticPersistenceService.persist_evidence`,
    while hypotheses are only flushed per candidate by
    :meth:`~aegis.synthetic.hypothesis_persistence.HypothesisPersistenceService.persist`.
    This function therefore commits **once** at the end — a single
    round-trip for every hypothesis row (and its audit entry) — and rolls
    the session back before re-raising if anything fails, so no
    half-written batch survives.
    """
    try:
        outcome = _analyze(payload, db)
        response = SyntheticAnalysisResponse(
            seed=payload.seed,
            actor_count=outcome.actor_count,
            evidence_count=outcome.evidence_count,
            relationship_count=outcome.relationship_count,
            candidate_count=outcome.candidate_count,
            persisted_hypothesis_count=len(outcome.hypotheses),
            hypotheses=outcome.hypotheses,
        )
        db.commit()  # one commit for every flushed hypothesis (audit rows included)
        _index_committed_evidence(outcome.evidence_records)
    except Exception:
        db.rollback()
        raise
    return response


@dataclass(frozen=True)
class _AnalysisOutcome:
    """Summary counts plus the hypothesis rows built by :func:`_analyze`."""

    hypotheses: list[dict[str, object]]
    evidence_records: list[EvidenceRecord]
    actor_count: int
    evidence_count: int
    relationship_count: int
    candidate_count: int


def _index_committed_evidence(records: list[EvidenceRecord]) -> None:
    """Synchronize committed PostgreSQL evidence into OpenSearch."""
    if not records:
        return

    username = settings.opensearch_username
    password = settings.opensearch_password
    auth = (username, password) if username is not None and password is not None else None

    try:
        search = OpenSearchAdapter(
            settings.opensearch_url,
            index_prefix=settings.opensearch_index_prefix,
            http_auth=auth,
        )
        indexed = EvidenceSearchIndexer(search).index_many(records)
        logger.info("Indexed %d committed evidence records", indexed)
    except Exception:
        # PostgreSQL is the source of truth. Search synchronization is
        # separately observable and must never undo a successful commit.
        logger.exception(
            "OpenSearch synchronization failed for %d committed evidence records",
            len(records),
        )


def _analyze(payload: SyntheticAnalysisRequest, db: Session) -> _AnalysisOutcome:
    """Run the pipeline up to (but excluding) the final commit.

    Every database write here is flushed, never committed — the caller
    (``run_synthetic_analysis``) owns the single commit/rollback.
    """
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
    evidence_records = persistence.persist_evidence(source_id, actors, evidence)

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

    return _AnalysisOutcome(
        hypotheses=hypotheses,
        evidence_records=evidence_records,
        actor_count=len(actors),
        evidence_count=len(evidence),
        relationship_count=len(relationships),
        candidate_count=len(candidates),
    )


def get_analysis_db(
    db: Annotated[Session, Depends(get_db)],
) -> Session:
    return db
