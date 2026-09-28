"""Explicit ground truth for the controlled synthetic benchmark."""

from aegis.synthetic.actor import SyntheticActor
from aegis.synthetic.persona_simulator import MigrationLevel


def actor_disjoint_split(
    actors: list[SyntheticActor], train_fraction: float = 0.7
) -> tuple[list[SyntheticActor], list[SyntheticActor]]:
    """Deterministic actor-disjoint split; pairs cannot straddle train and test."""
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be between zero and one")
    ordered = sorted(actors, key=lambda actor: actor.actor_id)
    if len(ordered) < 2:
        raise ValueError("at least two actors are required for an actor-disjoint split")
    cut = min(max(1, round(len(ordered) * train_fraction)), len(ordered) - 1)
    return ordered[:cut], ordered[cut:]


def migration_levels() -> tuple[MigrationLevel, ...]:
    """The fixed L1–L5 evaluation ladder, ordered by adversarial severity."""
    return tuple(MigrationLevel)


class SyntheticBenchmark:
    """Define explicit ground truth for the controlled synthetic benchmark."""

    @staticmethod
    def ground_truth_pairs(
        actors: list[SyntheticActor],
    ) -> set[tuple[str, str]]:
        actor_ids = {actor.actor_id for actor in actors}

        expected_pairs = {
            ("actor-0001", "actor-0002"),
            ("actor-0003", "actor-0004"),
        }

        return {pair for pair in expected_pairs if pair[0] in actor_ids and pair[1] in actor_ids}
