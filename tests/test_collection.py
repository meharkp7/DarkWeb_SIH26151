"""Phase 05 collector framework tests: corpus ground truth, collector
contract, orchestration, and the source → collector → evidence exit path."""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from aegis.collection import (
    Candidate,
    CollectionScope,
    CollectorOrchestrator,
    CollectorRejected,
    JobType,
    NormalizedArtifact,
    SyntheticChannelCollector,
    SyntheticCorpusBuilder,
    SyntheticForumCollector,
    SyntheticMarketplaceCollector,
    SyntheticSurfaceCollector,
    build_default_corpus,
)
from aegis.collection.base import Collector
from aegis.collection.corpus import PLATFORMS, corpus_summary
from aegis.collection.types import RawArtifact

# --------------------------------------------------------------- corpus


def test_corpus_meets_phase_05_targets() -> None:
    corpus = build_default_corpus()
    summary = corpus_summary(corpus)

    assert summary["actors"] == 100
    assert summary["posts"] == 1_000
    assert summary["relationships"] >= 500, summary
    assert summary["ground_truth_same_actor_pairs"] > 0


def test_corpus_is_deterministic_for_seed() -> None:
    first = SyntheticCorpusBuilder(seed=26151).build()
    second = SyntheticCorpusBuilder(seed=26151).build()
    third = SyntheticCorpusBuilder(seed=99999).build()

    assert first == second
    assert first != third


def test_ground_truth_relationships_are_consistent() -> None:
    corpus = build_default_corpus()
    alias_ids = {alias.alias_id for alias in corpus.aliases}
    actor_by_alias = {alias.alias_id: alias.actor_id for alias in corpus.aliases}

    same_actor = [r for r in corpus.relationships if r.relationship_type == "same_actor"]
    assert same_actor, "corpus must contain same_actor relationships"

    for rel in same_actor:
        assert rel.source_id in alias_ids and rel.target_id in alias_ids
        # ground truth: same-actor links connect two aliases of one actor
        assert actor_by_alias[rel.source_id] == actor_by_alias[rel.target_id]

    for rel in corpus.relationships:
        assert rel.source_id and rel.target_id and rel.relationship_id


def test_ground_truth_pairs_match_alias_grouping() -> None:
    corpus = build_default_corpus()
    pairs = corpus.same_actor_pairs

    for left, right in pairs:
        assert corpus.alias_by_id[left].actor_id == corpus.alias_by_id[right].actor_id

    # every alias with a sibling alias appears in at least one pair
    aliases_by_actor: dict[str, int] = {}
    for alias in corpus.aliases:
        aliases_by_actor[alias.actor_id] = aliases_by_actor.get(alias.actor_id, 0) + 1
    multi = {a for a, count in aliases_by_actor.items() if count > 1}
    covered = {corpus.alias_by_id[pair[0]].actor_id for pair in pairs}
    assert covered == multi


# ------------------------------------------------------------ collectors


def test_synthetic_collectors_cover_every_platform() -> None:
    corpus = build_default_corpus()
    collectors = [
        SyntheticForumCollector(corpus),
        SyntheticMarketplaceCollector(corpus),
        SyntheticSurfaceCollector(corpus),
        SyntheticChannelCollector(corpus),
    ]

    scope = CollectionScope(job_type=JobType.DISCOVER, limit=10_000)
    all_candidates: list[Candidate] = []
    for collector in collectors:
        all_candidates.extend(asyncio.run(collector.discover(scope)))

    # all four platform kinds represented across the collector fleet
    assert {PLATFORMS[c.platform] for c in all_candidates} == set(PLATFORMS.values())
    # together they see the whole 1,000-post corpus
    assert len(all_candidates) == len(corpus.posts)


def test_collector_rejects_out_of_scope_platforms() -> None:
    collector = SyntheticMarketplaceCollector()
    scope = CollectionScope(job_type=JobType.DISCOVER, platforms=("forum_alpha",))
    with pytest.raises(CollectorRejected):
        asyncio.run(collector.discover(scope))


def test_collector_respects_time_window_and_limit() -> None:
    from datetime import datetime

    collector = SyntheticForumCollector()
    full = asyncio.run(collector.discover(CollectionScope(limit=10_000)))
    limited = asyncio.run(collector.discover(CollectionScope(limit=5)))
    assert len(limited) == 5
    assert {c.candidate_id for c in limited} <= {c.candidate_id for c in full}

    earliest = min(c.observed_hint for c in full)
    windowed = asyncio.run(
        collector.discover(
            CollectionScope(limit=10_000, since=datetime.fromisoformat(earliest))
        )
    )
    assert all(c.observed_hint >= earliest for c in windowed)


def test_collect_normalize_produces_independence_groups() -> None:
    collector = SyntheticForumCollector()
    scope = CollectionScope(limit=10)
    observations = asyncio.run(collector.run(scope))

    assert observations
    for obs in observations:
        assert isinstance(obs, NormalizedArtifact)
        assert obs.independence_group.startswith("forum:")
        assert obs.text and obs.normalized_text == " ".join(obs.text.lower().split())
        assert obs.observed_at is not None
        assert obs.author_hint
        assert obs.raw.sha256 and len(obs.raw.sha256) == 64


def test_normalization_is_stable_across_fetches() -> None:
    collector = SyntheticForumCollector()
    scope = CollectionScope(limit=5)
    first = asyncio.run(collector.run(scope))
    second = asyncio.run(collector.run(scope))
    assert [o.normalized_text for o in first] == [o.normalized_text for o in second]
    assert [o.raw.sha256 for o in first] == [o.raw.sha256 for o in second]


# ---------------------------------------------------------- orchestrator


class _FailingCollector(Collector):
    name = "failing"
    version = "0.0.1"

    async def discover(self, scope: CollectionScope) -> list[Candidate]:  # noqa: ARG002
        return [Candidate(candidate_id="c1", source_ref="x", platform="forum_alpha")]

    async def collect(self, candidate: Candidate) -> RawArtifact:  # noqa: ARG002
        raise RuntimeError("boom")

    async def normalize(self, artifact: RawArtifact) -> list[NormalizedArtifact]:  # noqa: ARG002
        return []


def test_orchestrator_isolates_collector_failures() -> None:
    good = SyntheticForumCollector()
    bad = _FailingCollector()
    orchestrator = CollectorOrchestrator([bad, good])

    report = asyncio.run(orchestrator.run(CollectionScope(limit=5)))

    assert report.total_observations > 0
    failing = next(o for o in report.outcomes if o.collector_name == "failing")
    healthy = next(o for o in report.outcomes if o.collector_name == "synthetic_forum")
    assert failing.errors and "boom" in failing.errors[0]
    assert healthy.errors == ()
    assert report.error_count >= 1
    assert report.duration_seconds >= 0.0


def test_orchestrator_requires_at_least_one_collector() -> None:
    with pytest.raises(ValueError, match="at least one collector"):
        CollectorOrchestrator([])


# ----------------------------------------------------- exit criterion (unit side)


def test_collector_modules_do_not_import_database_code() -> None:
    """Collectors must stay decoupled from persistence: only the ingest
    bridge (a separate module) may import the evidence/db layers."""
    package_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "aegis" / "collection"
    allowed = {"ingest.py"}
    forbidden_markers = ("aegis.db", "aegis.evidence", "sqlalchemy")

    for path in sorted(package_dir.glob("*.py")):
        if path.name in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for marker in forbidden_markers:
            assert marker not in source, f"{path.name} must not reference {marker}"


def test_source_to_collector_to_evidence_without_db() -> None:
    """Phase 05 exit criterion at the unit level: the full collector chain
    produces observations carrying every provenance field the ledger requires."""
    orchestrator = CollectorOrchestrator(
        [
            SyntheticForumCollector(),
            SyntheticMarketplaceCollector(),
            SyntheticSurfaceCollector(),
            SyntheticChannelCollector(),
        ]
    )
    report = asyncio.run(orchestrator.run(CollectionScope(limit=20)))

    assert report.total_observations == 80
    assert report.error_count == 0
    for observation in report.observations:
        assert observation.raw.collector_name
        assert observation.raw.collector_version
        assert observation.raw.sha256 and len(observation.raw.sha256) == 64
        assert observation.independence_group
        assert observation.observed_at is not None
        assert observation.platform
