from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator


def test_evidence_generation_is_deterministic() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(5)

    first = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    second = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    assert first == second


def test_evidence_is_linked_to_known_actor() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(3)
    evidence, relationships = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    actor_ids = {actor.actor_id for actor in actors}

    assert evidence
    assert all(item.actor_id in actor_ids for item in evidence)
    assert relationships


def test_relationships_reference_existing_evidence() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(3)
    evidence, relationships = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    evidence_ids = {item.evidence_id for item in evidence}

    assert all(
        relationship.source_evidence_id in evidence_ids
        and relationship.target_evidence_id in evidence_ids
        for relationship in relationships
    )
