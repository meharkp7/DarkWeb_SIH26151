from datetime import UTC, datetime, timedelta

from aegis.evaluation.metrics import EvaluationMetrics
from aegis.evaluation.protocols import (
    migration_degradation,
    platform_disjoint_split,
    temporal_split,
)
from aegis.synthetic.evidence import SyntheticEvidence
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.persona_simulator import AdversarialPersonaSimulator, MigrationLevel


def _evidence(platform: str, observed_at: datetime) -> SyntheticEvidence:
    return SyntheticEvidence("e", "actor", "handle", "alias", 0.8, observed_at, platform, "source")


def _metrics(f1: float) -> EvaluationMetrics:
    return EvaluationMetrics(1, 0, 0, 1, f1, f1, f1, 0.0)


def test_temporal_and_platform_splits_do_not_leak() -> None:
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    evidence = [_evidence("alpha", origin), _evidence("beta", origin + timedelta(days=1))]
    assert temporal_split(evidence, origin + timedelta(hours=12)).kind == "temporal"
    split = platform_disjoint_split(evidence, {"beta"})
    assert [item.platform for item in split.train] == ["alpha"]
    assert [item.platform for item in split.test] == ["beta"]


def test_migration_degradation_covers_the_full_severity_ladder() -> None:
    actor = SyntheticActorGenerator().generate(1)[0]
    simulator = AdversarialPersonaSimulator()
    migrations = [simulator.migrate(actor, level) for level in MigrationLevel]
    results = migration_degradation(
        _metrics(1.0), migrations, lambda level, _: _metrics(1.0 - level / 10)
    )
    assert [result.level for result in results] == list(MigrationLevel)
    assert results[-1].f1_degradation == 0.5
