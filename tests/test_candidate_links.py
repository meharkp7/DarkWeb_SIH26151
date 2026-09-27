from aegis.synthetic.candidate_links import CandidateLinkEngine
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator


def _generate():
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    return evidence


def test_candidate_links_are_deterministic() -> None:
    evidence = _generate()
    engine = CandidateLinkEngine()

    first = engine.generate(evidence)
    second = engine.generate(evidence)

    assert first == second


def test_candidate_links_have_valid_scores() -> None:
    candidates = CandidateLinkEngine().generate(_generate())

    for candidate in candidates:
        assert candidate.source_actor_id != candidate.target_actor_id
        assert 0.0 <= candidate.score <= 1.0

        for feature in candidate.features:
            assert 0.0 <= feature.score <= 1.0
            assert feature.name
            assert feature.explanation


def test_candidate_links_respect_threshold() -> None:
    evidence = _generate()

    candidates = CandidateLinkEngine().generate(
        evidence,
        min_score=1.0,
    )

    assert all(candidate.score >= 1.0 for candidate in candidates)


def test_candidate_link_ids_are_stable() -> None:
    evidence = _generate()

    candidates = CandidateLinkEngine().generate(evidence)

    assert len({candidate.link_id for candidate in candidates}) == len(candidates)
