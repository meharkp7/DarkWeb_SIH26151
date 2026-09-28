from aegis.synthetic.candidate_links import CandidateLinkEngine, LinkFeature
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


def test_indicator_similarity_has_higher_weight_than_handle_overlap():
    engine = CandidateLinkEngine()

    features = [
        LinkFeature(
            name="handle_overlap",
            score=1.0,
            explanation="shared handle",
        ),
        LinkFeature(
            name="indicator_similarity",
            score=0.0,
            explanation="no shared indicators",
        ),
    ]

    assert engine._aggregate(features) == 0.15


def test_indicator_similarity_dominates_candidate_score():
    engine = CandidateLinkEngine()

    features = [
        LinkFeature(
            name="handle_overlap",
            score=0.0,
            explanation="no shared handle",
        ),
        LinkFeature(
            name="indicator_similarity",
            score=1.0,
            explanation="all indicators match",
        ),
    ]

    assert engine._aggregate(features) == 0.85


def test_low_confidence_indicator_match_is_weaker() -> None:
    engine = CandidateLinkEngine()

    high_confidence = [
        LinkFeature(
            name="indicator_similarity",
            score=0.90,
            explanation="high-confidence indicator match",
        )
    ]
    low_confidence = [
        LinkFeature(
            name="indicator_similarity",
            score=0.30,
            explanation="low-confidence indicator match",
        )
    ]

    assert engine._aggregate(high_confidence) > engine._aggregate(low_confidence)


def test_evidence_type_weights_are_explicit() -> None:
    engine = CandidateLinkEngine()

    features = [
        LinkFeature(
            name="handle_overlap",
            score=0.0,
            explanation="no shared handle",
        ),
        LinkFeature(
            name="indicator_similarity",
            score=1.0,
            explanation="all indicators match",
        ),
    ]

    assert engine._aggregate(features) == 0.85


def test_index_is_built_once_per_actor(monkeypatch) -> None:
    """``generate()`` hoists index construction out of the O(n^2) pair loop."""
    evidence = _generate()
    actor_ids = {item.actor_id for item in evidence}
    assert len(actor_ids) >= 2, "fixture must contain several actors"

    baseline = CandidateLinkEngine().generate(evidence)

    calls = 0
    original = CandidateLinkEngine.index

    def counting_index(items):  # noqa: ANN001, ANN202
        nonlocal calls
        calls += 1
        return original(items)

    monkeypatch.setattr(CandidateLinkEngine, "index", staticmethod(counting_index))
    instrumented = CandidateLinkEngine().generate(evidence)

    assert calls == len(actor_ids), "one index build per actor, not per pair"
    assert instrumented == baseline
