from aegis.evaluation.scenarios import ScenarioBuilder
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator


def _build_scenarios():
    actors = SyntheticActorGenerator(seed=26151).generate(4)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    return ScenarioBuilder().build(evidence)


def test_scenario_builder_creates_all_expected_scenarios():
    scenarios = _build_scenarios()

    assert [scenario.name for scenario in scenarios] == [
        "clean_strong",
        "clean_weak",
        "contradictory",
        "noisy_match",
        "no_match",
    ]


def test_scenarios_have_expected_pairs():
    scenarios = _build_scenarios()

    assert scenarios[0].source_actor_id == "actor-0001"
    assert scenarios[0].target_actor_id == "actor-0002"

    assert scenarios[1].source_actor_id == "actor-0003"
    assert scenarios[1].target_actor_id == "actor-0004"


def test_scenarios_have_expected_match_labels():
    scenarios = _build_scenarios()

    expected = {
        "clean_strong": True,
        "clean_weak": True,
        "contradictory": False,
        "noisy_match": False,
        "no_match": False,
    }

    for scenario in scenarios:
        assert scenario.expected_match is expected[scenario.name]


def test_noisy_match_contains_low_confidence_signal():
    scenarios = _build_scenarios()
    scenario = next(item for item in scenarios if item.name == "noisy_match")

    assert any(item.confidence == 0.35 for item in scenario.evidence)


def test_scenarios_are_deterministic():
    first = _build_scenarios()
    second = _build_scenarios()

    assert first == second
