from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from aegis.gnn.graph import GnnNodeType, HeteroGraph
from aegis.gnn.models import (
    ContradictionAwareTemporalHGT,
    HGTEncoder,
    RGCNEncoder,
    TemporalHGTEncoder,
)
from aegis.ontology import RelationshipType


def _graph() -> HeteroGraph:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    graph = HeteroGraph()
    graph.add_node("actor", GnnNodeType.ACTOR, observed_at=now)
    graph.add_node("handle", GnnNodeType.HANDLE, observed_at=now + timedelta(days=30))
    graph.add_node("wallet", GnnNodeType.WALLET, observed_at=now)
    graph.add_edge(RelationshipType.USES_HANDLE, "actor", "handle", observed_at=now)
    graph.add_edge(RelationshipType.ASSOCIATED_WITH_WALLET, "actor", "wallet", observed_at=now)
    graph.set_features(GnnNodeType.ACTOR, [[1.0, 0.0]])
    graph.set_features(GnnNodeType.HANDLE, [[0.0, 1.0]])
    graph.set_features(GnnNodeType.WALLET, [[0.5, 0.5]])
    return graph


@pytest.mark.parametrize("encoder", [RGCNEncoder(), HGTEncoder(), TemporalHGTEncoder()])
def test_phase_19_encoders_produce_deterministic_bounded_pair_scores(encoder: object) -> None:
    model = encoder.fit(_graph())  # type: ignore[union-attr]
    embeddings = model.embeddings()  # type: ignore[union-attr]
    prediction = model.predict_pair("actor", "handle")  # type: ignore[union-attr]
    assert embeddings.shape == (3, 16)
    assert np.isfinite(embeddings).all()
    assert 0.0 <= prediction.raw_score <= 1.0


def test_contradiction_reduces_temporal_hgt_score() -> None:
    model = ContradictionAwareTemporalHGT().fit(_graph())
    supported = model.predict_pair("actor", "handle")
    contradicted = model.predict_pair("actor", "handle", contradiction_weight=2.0)
    assert contradicted.raw_score < supported.raw_score
