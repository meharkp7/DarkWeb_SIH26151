from aegis.evaluation.benchmark import actor_disjoint_split, migration_levels
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.persona_simulator import AdversarialPersonaSimulator, MigrationLevel


def test_migration_ladder_applies_the_expected_modalities() -> None:
    actor = SyntheticActorGenerator().generate(1)[0]
    simulator = AdversarialPersonaSimulator()
    l1 = simulator.migrate(actor, MigrationLevel.L1_ALIAS)
    l5 = simulator.migrate(actor, MigrationLevel.L5_MULTIMODAL)
    assert l1.changed_modalities == ("alias",)
    assert l5.changed_modalities == (
        "alias",
        "vocabulary",
        "behavior",
        "marketplace",
        "identifiers",
        "infrastructure",
    )
    assert l5.migrated.identities != actor.identities
    assert l5.migrated.indicators != actor.indicators


def test_actor_disjoint_split_and_ladder_are_deterministic() -> None:
    actors = SyntheticActorGenerator().generate(5)
    train, test = actor_disjoint_split(actors)
    assert {actor.actor_id for actor in train}.isdisjoint(actor.actor_id for actor in test)
    assert migration_levels() == tuple(MigrationLevel)
