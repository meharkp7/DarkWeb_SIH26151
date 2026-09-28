from uuid import UUID

from aegis.db.models import AttributionHypothesisRecord, HypothesisContradictionRecord
from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLink
from aegis.synthetic.contradiction import ContradictionAnalysis, ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.hypothesis import AttributionHypothesis, AttributionHypothesisBuilder
from aegis.synthetic.hypothesis_persistence import HypothesisPersistenceService


class _SpySession:
    """Session stand-in recording add/flush/commit traffic (no database)."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushes = 0
        self.commits = 0
        self.refreshes = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj: object) -> None:
        self.refreshes += 1


def _build_case() -> tuple[AttributionHypothesis, ContradictionAnalysis]:
    """Build one hypothesis/contradiction pair the way the API route does."""
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    actor_ids = sorted({item.actor_id for item in evidence})

    candidate = CandidateLink(
        link_id="persistence-test",
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
    return hypothesis, contradiction


def records_of(db: _SpySession) -> list[AttributionHypothesisRecord]:
    return [obj for obj in db.added if isinstance(obj, AttributionHypothesisRecord)]


def test_hypothesis_persistence_payload_is_constructible() -> None:
    hypothesis, _ = _build_case()

    assert hypothesis.status == "candidate"
    assert hypothesis.source_actor_id
    assert hypothesis.target_actor_id
    assert hypothesis.evidence
    assert 0.0 <= hypothesis.final_score <= 1.0


def test_persist_flushes_without_committing() -> None:
    """Flush-only contract: the CALLER owns commit (batch round-trip finding).

    ``run_synthetic_analysis`` commits once after every hypothesis, so a
    single ``persist()`` must emit the rows (flush) but never commit or
    refresh — and the returned id must be usable without either.
    """
    hypothesis, contradiction = _build_case()
    db = _SpySession()

    hypothesis_id = HypothesisPersistenceService(db).persist(hypothesis, contradiction)

    assert db.commits == 0, "persist() must not commit; run_synthetic_analysis does"
    assert db.flushes == 1, "rows must still be flushed so violations surface early"
    assert db.refreshes == 0, "every column read downstream is set client-side"

    records = [obj for obj in db.added if isinstance(obj, AttributionHypothesisRecord)]
    contradictions = [obj for obj in db.added if isinstance(obj, HypothesisContradictionRecord)]
    assert len(records) == 1
    assert len(contradictions) == len(contradiction.contradictions)

    # the id is assigned client-side, so it survives without a commit/refresh
    assert isinstance(hypothesis_id, UUID)
    assert records[0].hypothesis_id == hypothesis_id
    assert all(item.hypothesis_id == hypothesis_id for item in contradictions)


def test_persist_does_not_reuse_ids_across_calls() -> None:
    """A non-uuid hypothesis id yields a fresh uuid4 per row (unchanged)."""
    hypothesis, contradiction = _build_case()
    db = _SpySession()
    service = HypothesisPersistenceService(db)

    first = service.persist(hypothesis, contradiction)
    second = service.persist(hypothesis, contradiction)

    assert first != second
    assert {record.hypothesis_id for record in records_of(db)} == {first, second}
    assert db.commits == 0
