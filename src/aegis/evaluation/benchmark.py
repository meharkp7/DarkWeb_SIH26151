"""Explicit ground truth for the controlled synthetic benchmark."""

from aegis.synthetic.actor import SyntheticActor


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
