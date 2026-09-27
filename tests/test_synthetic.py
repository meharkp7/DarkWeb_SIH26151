from aegis.synthetic.generator import SyntheticActorGenerator


def test_generator_is_deterministic() -> None:
    first = SyntheticActorGenerator(seed=26151).generate(5)
    second = SyntheticActorGenerator(seed=26151).generate(5)

    assert first == second


def test_generator_creates_requested_count() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(12)

    assert len(actors) == 12
    assert len({actor.actor_id for actor in actors}) == 12


def test_actor_contains_cross_platform_identities() -> None:
    actor = SyntheticActorGenerator(seed=26151).generate(1)[0]

    assert 2 <= len(actor.identities) <= 3
    assert len(actor.indicators) == 3
    assert all(identity.identity_hash for identity in actor.identities)


def test_invalid_count_is_rejected() -> None:
    generator = SyntheticActorGenerator()

    try:
        generator.generate(0)
    except ValueError as exc:
        assert str(exc) == "count must be greater than zero"
    else:
        raise AssertionError("Expected ValueError")


def test_generator_contains_controlled_benchmark_overlap() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(4)

    actor_1 = actors[0]
    actor_2 = actors[1]
    actor_3 = actors[2]
    actor_4 = actors[3]

    assert actor_1.indicators[0] == actor_2.indicators[0]
    assert actor_1.indicators[1] == actor_2.indicators[1]
    assert actor_3.indicators[2] == actor_4.indicators[2]
