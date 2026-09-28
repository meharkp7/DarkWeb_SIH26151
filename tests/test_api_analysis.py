"""Transaction-shape tests for :func:`aegis.api.analysis.run_synthetic_analysis`.

``run_synthetic_analysis`` owns the **single** commit for the whole
synthetic pipeline: evidence is committed in one batch by
``SyntheticPersistenceService``, hypotheses are only flushed by
``HypothesisPersistenceService``, and this wrapper commits exactly once
on success — rolling back (and re-raising) on any failure so no
half-written batch survives.

The heavy pipeline (``_analyze``) is stubbed out; what is under test is
the commit/rollback discipline and the response built around it.
"""

from __future__ import annotations

from typing import Any

import pytest

import aegis.api.analysis as analysis_module
from aegis.api.analysis import _AnalysisOutcome, run_synthetic_analysis
from aegis.schemas.analysis import SyntheticAnalysisRequest


class _SpySession:
    """Session double recording commit/rollback traffic."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1

    def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1


def _outcome() -> _AnalysisOutcome:
    return _AnalysisOutcome(
        hypotheses=[
            {
                "hypothesis_id": "h-1",
                "source_actor_id": "actor-0",
                "target_actor_id": "actor-1",
                "raw_score": 0.9,
                "support_score": 0.8,
                "contradiction_score": 0.1,
                "final_score": 0.85,
                "status": "supported",
                "evidence_count": 3,
                "explanations": ["shared wallet"],
            }
        ],
        actor_count=4,
        evidence_count=12,
        relationship_count=6,
        candidate_count=5,
    )


def test_success_commits_exactly_once(monkeypatch: Any) -> None:
    db = _SpySession()
    monkeypatch.setattr(analysis_module, "_analyze", lambda payload, session: _outcome())

    run_synthetic_analysis(SyntheticAnalysisRequest(), db)

    assert db.commits == 1, "the whole pipeline commits in ONE round-trip"
    assert db.rollbacks == 0


def test_response_reflects_outcome(monkeypatch: Any) -> None:
    db = _SpySession()
    monkeypatch.setattr(analysis_module, "_analyze", lambda payload, session: _outcome())

    response = run_synthetic_analysis(SyntheticAnalysisRequest(seed=99), db)

    assert response.seed == 99
    assert response.actor_count == 4
    assert response.evidence_count == 12
    assert response.relationship_count == 6
    assert response.candidate_count == 5
    assert response.persisted_hypothesis_count == 1
    assert response.hypotheses[0]["hypothesis_id"] == "h-1"


def test_failure_rolls_back_and_reraises(monkeypatch: Any) -> None:
    db = _SpySession()

    def exploding(payload: Any, session: Any) -> _AnalysisOutcome:
        raise RuntimeError("half-written batch")

    monkeypatch.setattr(analysis_module, "_analyze", exploding)

    with pytest.raises(RuntimeError, match="half-written batch"):
        run_synthetic_analysis(SyntheticAnalysisRequest(), db)

    assert db.commits == 0, "a failed pipeline must not leave a committed batch"
    assert db.rollbacks == 1
    assert db.events == ["rollback"]


def test_commit_happens_after_analysis(monkeypatch: Any) -> None:
    """Ordering: analysis completes fully, THEN the single commit fires."""
    db = _SpySession()

    def analyze(payload: Any, session: Any) -> _AnalysisOutcome:
        session.events.append("analyze")
        return _outcome()

    monkeypatch.setattr(analysis_module, "_analyze", analyze)

    run_synthetic_analysis(SyntheticAnalysisRequest(), db)

    assert db.events == ["analyze", "commit"]
