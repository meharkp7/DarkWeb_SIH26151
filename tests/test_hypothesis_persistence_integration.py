from aegis.db.session import SessionLocal
from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLink
from aegis.synthetic.contradiction import ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.hypothesis import AttributionHypothesisBuilder
from aegis.synthetic.hypothesis_persistence import HypothesisPersistenceService


def test_hypothesis_persists_to_postgres() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    actor_ids = sorted({item.actor_id for item in evidence})

    candidate = CandidateLink(
        link_id="integration-test-link",
        source_actor_id=actor_ids[0],
        target_actor_id=actor_ids[1],
        score=0.75,
        features=(),
    )

    calibrated = ConfidenceCalibrator().calibrate(
        candidate,
        evidence,
    )

    contradiction = ContradictionDetector().analyze(
        candidate,
        evidence,
    )

    hypothesis = AttributionHypothesisBuilder().build(
        calibrated,
        contradiction,
        evidence,
    )

    db = SessionLocal()

    try:
        service = HypothesisPersistenceService(db)

        hypothesis_id = service.persist(
            hypothesis,
            contradiction,
        )

        stored = service.db.get(
            __import__(
                "aegis.db.models",
                fromlist=["AttributionHypothesisRecord"],
            ).AttributionHypothesisRecord,
            hypothesis_id,
        )

        assert stored is not None
        assert stored.source_actor_id == hypothesis.source_actor_id
        assert stored.target_actor_id == hypothesis.target_actor_id
        assert stored.status == "candidate"
        assert stored.final_score == hypothesis.final_score
        assert stored.evidence_json
    finally:
        db.rollback()
        db.close()
