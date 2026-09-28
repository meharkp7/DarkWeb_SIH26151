import pytest

from aegis.attribution.baseline import AttributionExample, TransparentAttributionBaseline
from aegis.attribution.evaluation import EvaluationExample, actor_disjoint_split, evaluate_baselines
from aegis.attribution.signals import ChannelSignals


def ex(pair, actor, label, value, split):
    return EvaluationExample(
        actor,
        AttributionExample(
            pair,
            ChannelSignals(
                handle=value,
                pgp=value,
                wallet=value,
                temporal=value,
                behavior=value,
                infrastructure=value,
            ),
            label,
        ),
        split,
    )


def dataset():
    return [
        ex("t1", "a1", 1, 1.0, "train"),
        ex("t2", "a2", 1, 0.9, "train"),
        ex("t3", "a3", 0, 0.0, "train"),
        ex("t4", "a4", 0, 0.1, "train"),
        ex("v1", "a5", 1, 0.8, "validation"),
        ex("v2", "a6", 0, 0.1, "validation"),
        ex("e1", "a7", 1, 0.9, "test"),
        ex("e2", "a8", 0, 0.0, "test"),
    ]


def test_split_is_actor_disjoint():
    splits = actor_disjoint_split(dataset())
    assert len(splits["train"]) == 4


def test_actor_overlap_is_rejected():
    data = dataset()
    data.append(ex("bad", "a1", 1, 0.8, "test"))
    with pytest.raises(ValueError, match="actor-disjoint"):
        actor_disjoint_split(data)


def test_evaluation_returns_traceable_metrics():
    result = evaluate_baselines(dataset(), [TransparentAttributionBaseline()])[0]
    assert result.model_id == "transparent-fusion"
    assert result.metrics["roc_auc"] == pytest.approx(1.0)
    assert result.metrics["pr_auc"] == pytest.approx(1.0)
    assert len(result.scores) == 2
