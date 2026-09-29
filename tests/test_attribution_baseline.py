from __future__ import annotations

import pytest

from aegis.attribution.baseline import (
    AttributionExample,
    LogisticAttributionBaseline,
    TransparentAttributionBaseline,
    XgboostAttributionBaseline,
)
from aegis.attribution.signals import ChannelSignals


def _signals(**overrides: float) -> ChannelSignals:
    values = {
        "handle": 0.0,
        "pgp": 0.0,
        "wallet": 0.0,
        "temporal": 0.0,
        "behavior": 0.0,
        "infrastructure": 0.0,
    }
    values.update(overrides)
    return ChannelSignals(**values)


def _training_set() -> list[AttributionExample]:
    return [
        AttributionExample("p1", _signals(handle=1.0, wallet=1.0, temporal=0.8), 1),
        AttributionExample("p2", _signals(handle=0.9, pgp=0.8, behavior=0.7), 1),
        AttributionExample("p3", _signals(wallet=0.8, infrastructure=0.7), 1),
        AttributionExample("n1", _signals(), 0),
        AttributionExample("n2", _signals(handle=0.1, wallet=0.0), 0),
        AttributionExample("n3", _signals(behavior=0.1, infrastructure=0.1), 0),
    ]


def test_transparent_formula_is_deterministic_and_traceable() -> None:
    example = AttributionExample(
        "pair-1",
        _signals(handle=1.0, wallet=1.0),
        1,
        evidence_ids=("e1", "e2"),
    )
    score = TransparentAttributionBaseline().score(example)

    assert score.model_id == "transparent-fusion"
    assert score.model_version == "baseline-0.1"
    assert score.evidence_ids == ("e1", "e2")
    assert score.signals["S_h"] == 1.0
    assert score.raw_score == pytest.approx(0.610639, abs=1e-6)


def test_transparent_zero_signal_does_not_create_full_support() -> None:
    score = TransparentAttributionBaseline().score(
        AttributionExample("no-signal", ChannelSignals.zeros(), 0)
    )
    assert score.raw_score == 0.5


def test_logistic_requires_both_classes_and_is_deterministic() -> None:
    model = LogisticAttributionBaseline(epochs=80)
    with pytest.raises(ValueError, match="both positive and negative"):
        model.fit([AttributionExample("only-positive", _signals(wallet=1.0), 1)])

    examples = _training_set()
    model.fit(examples)
    first = model.score(examples[0])
    second = model.score(examples[0])

    assert model.fitted
    assert first.raw_score == second.raw_score
    assert first.raw_score > model.score(examples[-1]).raw_score


def test_xgboost_requires_both_classes() -> None:
    model = XgboostAttributionBaseline(estimators=5)
    with pytest.raises(ValueError, match="both positive and negative"):
        model.fit([AttributionExample("only-negative", _signals(), 0)])


def test_xgboost_dmatrix_constrains_its_own_openmp_team(monkeypatch: pytest.MonkeyPatch) -> None:
    """See test_resolution.py for why this cannot be caught by an assertion.

    torch and xgboost wheels each ship their own LLVM libomp under different
    install names; an OpenMP team that DMatrix forks then reads a kmp_info
    allocated by the other runtime and segfaults. params["nthread"] throttles
    the booster only, so DMatrix needs its own nthread.
    """
    import xgboost

    recorded: list[object] = []
    real_dmatrix = xgboost.DMatrix

    def _recording_dmatrix(*args: object, **kwargs: object) -> object:
        recorded.append(kwargs.get("nthread"))
        return real_dmatrix(*args, **kwargs)

    monkeypatch.setattr(xgboost, "DMatrix", _recording_dmatrix)

    model = XgboostAttributionBaseline(estimators=5)
    model.fit(_training_set())
    model.score(_training_set()[0])

    assert recorded, "no DMatrix was constructed"
    assert recorded == [1] * len(recorded)


def test_invalid_training_example_is_rejected() -> None:
    with pytest.raises(ValueError, match="label must be 0 or 1"):
        AttributionExample("bad", ChannelSignals.zeros(), 2)
