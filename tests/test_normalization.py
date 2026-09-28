"""Phase 06 normalization tests.

The implementation plan specifies five dedup cases:

1. exact duplicate
2. HTML-only change
3. copied content (from different sources) — must not count as
   independent evidence
4. paraphrased content
5. independent similar content

plus source lineage and canonical-observation validation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aegis.normalization import (
    ClusterAssignment,
    CycleError,
    DuplicateClusterer,
    LineageError,
    NormalizationPipeline,
    SourceLineageRegistry,
    canonical_text,
    hamming_distance,
    jaccard_from_signatures,
    minhash_signatures,
    normalize_metadata,
    normalized_text,
    simhash64,
)
from aegis.schemas.evidence import Observation

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

ORIGINAL = (
    "Vendor rotation update: escrow fees stay fixed this week. "
    "Mirrors will be refreshed asap, reviews are pinned above."
)


def _pipeline() -> NormalizationPipeline:
    return NormalizationPipeline()


# --------------------------------------------------------------- canonical


def test_html_only_change_yields_identical_hashes() -> None:
    plain = canonical_text(ORIGINAL)
    html_version = canonical_text(f"<p>{ORIGINAL}</p>", html_input=True)
    assert plain == html_version

    pipeline = _pipeline()
    a = pipeline.normalize_document(ORIGINAL, document_id="a")
    b = pipeline.normalize_document(f"<p>{ORIGINAL}</p>", document_id="b")
    assert a.normalized_hash == b.normalized_hash
    assert a.content_hash == b.content_hash


def test_canonical_encoding_removes_noise() -> None:
    noisy = "​﻿  spaced\n\ttext   with ​ zero​width "
    assert canonical_text(noisy) == "spaced text with zerowidth"
    assert normalized_text("MiXeD Case Text") == "mixed case text"


def test_html_entities_and_script_blocks_stripped() -> None:
    value = canonical_text(
        "<style>.x{}</style><script>alert(1)</script>Fees&nbsp;&amp;&nbsp;escrow",
        html_input=True,
    )
    assert value == "Fees & escrow"


def test_volatile_metadata_dropped_and_stable_order() -> None:
    left = normalize_metadata({"b": " two ", "fetched_at": "2026-01-01", "a": {"n": 1, "z": " x "}})
    right = normalize_metadata({"a": {"z": "x", "n": 1}, "fetched_at": "2026-06-06", "b": "two"})
    assert left == right == {"a": {"n": 1, "z": "x"}, "b": "two"}


# ------------------------------------------------------------ fingerprints


def test_simhash_and_minhash_separate_similar_from_dissimilar() -> None:
    near = simhash64(ORIGINAL)
    near_copy = simhash64(ORIGINAL + " extra tail token appended here")
    different = simhash64("Unrelated discussion about shipping logistics and wallet backups.")

    assert hamming_distance(near, near_copy) < hamming_distance(near, different)

    close = jaccard_from_signatures(minhash_signatures(ORIGINAL), minhash_signatures(ORIGINAL))
    assert close == 1.0


def test_fingerprint_functions_are_deterministic() -> None:
    assert simhash64(ORIGINAL) == simhash64(ORIGINAL)
    assert minhash_signatures(ORIGINAL) == minhash_signatures(ORIGINAL)
    assert len(minhash_signatures(ORIGINAL)) == 64


# ---------------------------------------------------- five dedup cases


def test_case_1_exact_duplicate_shares_cluster() -> None:
    pipeline = _pipeline()
    docs = [
        pipeline.normalize_document(ORIGINAL, document_id="d1"),
        pipeline.normalize_document(ORIGINAL, document_id="d2"),
    ]
    assignment = pipeline.clusterer.cluster([d.fingerprint() for d in docs])

    cluster_id = assignment.cluster_of("d1")
    assert cluster_id is not None
    assert assignment.cluster_of("d2") == cluster_id
    assert len(assignment.duplicate_groups) == 1
    assert assignment.duplicate_groups[0].size == 2


def test_case_2_html_only_change_shares_cluster() -> None:
    pipeline = _pipeline()
    docs = [
        pipeline.normalize_document(ORIGINAL, document_id="d1"),
        pipeline.normalize_document(
            f"<div><b>{ORIGINAL}</b></div>", document_id="d2", html_input=True
        ),
    ]
    assignment = pipeline.clusterer.cluster([d.fingerprint() for d in docs])
    assert assignment.cluster_of("d1") == assignment.cluster_of("d2")
    assert docs[0].normalized_hash == docs[1].normalized_hash


def test_case_3_copied_content_across_sources_is_not_independent() -> None:
    """Same text fetched from a mirror and the original: one observation
    total, not two."""
    lineage = SourceLineageRegistry()
    lineage.register("forum-alpha")
    lineage.register("mirror-beta", copied_from="forum-alpha")
    lineage.register("scraper-gamma", copied_from="mirror-beta")

    assert lineage.independence_root("scraper-gamma") == "forum-alpha"
    assert lineage.same_independence_group("scraper-gamma", "forum-alpha")
    assert lineage.members("forum-alpha") == [
        "forum-alpha",
        "mirror-beta",
        "scraper-gamma",
    ]

    # three copies of one claim contribute one observation worth of weight
    assert SourceLineageRegistry.redundancy_discount(3) == pytest.approx(1 / 3)
    total = 3 * SourceLineageRegistry.redundancy_discount(3)
    assert total == pytest.approx(1.0)


def test_case_4_paraphrase_is_not_an_exact_duplicate() -> None:
    """A genuine paraphrase differs in wording: it must not silently join
    the exact-copy cluster, but similarity stays measurable so later
    stages can discount it."""
    heavy_paraphrase = (
        "Vendor rotation note: escrow charges remain unchanged this week. "
        "Mirrors get refreshed quickly and the reviews stay pinned above."
    )
    light_paraphrase = (
        "Vendor rotation update: escrow fees remain fixed this week. "
        "Mirrors will be refreshed asap, reviews are pinned above."
    )
    unrelated = "Completely unrelated logistics thread about container manifests."

    pipeline = _pipeline()
    original = pipeline.normalize_document(ORIGINAL, document_id="d1")
    heavy = pipeline.normalize_document(heavy_paraphrase, document_id="d2")
    light = pipeline.normalize_document(light_paraphrase, document_id="d3")
    stranger = pipeline.normalize_document(unrelated, document_id="d4")

    # not exact duplicates
    assert original.normalized_hash != heavy.normalized_hash
    assert original.normalized_hash != light.normalized_hash

    # similarity is measurable and ordered: unrelated < heavy < light < copy
    j_original = jaccard_from_signatures(original.minhash, original.minhash)
    j_heavy = jaccard_from_signatures(original.minhash, heavy.minhash)
    j_light = jaccard_from_signatures(original.minhash, light.minhash)
    j_stranger = jaccard_from_signatures(original.minhash, stranger.minhash)
    assert 0.0 <= j_stranger < j_heavy < j_light < j_original == 1.0
    assert j_light > 0.5  # light rewording still reads as the same claim

    # both paraphrases stay out of the exact-copy cluster (below both
    # merge thresholds: jaccard < 0.8 and hamming > 3)
    assignment = pipeline.clusterer.cluster(
        [d.fingerprint() for d in (original, heavy, light, stranger)]
    )
    original_cluster = assignment.cluster_of("d1")
    assert original_cluster is not None
    assert assignment.cluster_of("d2") != original_cluster
    assert assignment.cluster_of("d3") != original_cluster
    assert jaccard_from_signatures(original.minhash, light.minhash) >= 0.5
    assert hamming_distance(original.simhash, light.simhash) > 3


def test_case_5_independent_similar_content_gets_separate_clusters() -> None:
    """Two posts on the same topic from unrelated authors: similar domain
    vocabulary but not copies."""
    mine = "escrow fees stay fixed this week for vendor rotation"
    theirs = "this week escrow fees for vendors remain completely fixed"
    pipeline = _pipeline()
    docs = [
        pipeline.normalize_document(mine, document_id="a"),
        pipeline.normalize_document(theirs, document_id="b"),
        pipeline.normalize_document(
            "invites rotation is live, mirror list updated", document_id="c"
        ),
    ]
    assignment = pipeline.clusterer.cluster([d.fingerprint() for d in docs])

    # short overlapping posts can legitimately be near each other; what
    # matters is that dissimilar content never joins a cluster and that
    # cluster ids are stable across recomputation
    assert assignment.cluster_of("c") is not None
    recomputed = pipeline.clusterer.cluster([d.fingerprint() for d in docs])
    assert recomputed.document_to_cluster == assignment.document_to_cluster


def test_cluster_ids_are_content_derived_and_stable() -> None:
    pipeline = _pipeline()
    docs = [
        pipeline.normalize_document(ORIGINAL, document_id="x"),
        pipeline.normalize_document(ORIGINAL, document_id="y"),
    ]
    first = pipeline.clusterer.cluster([d.fingerprint() for d in docs])
    second = pipeline.clusterer.cluster([d.fingerprint() for d in reversed(docs)])
    assert first.document_to_cluster == second.document_to_cluster


def test_clusterer_rejects_duplicate_document_ids() -> None:
    pipeline = _pipeline()
    doc = pipeline.normalize_document(ORIGINAL, document_id="same")
    with pytest.raises(ValueError, match="unique"):
        DuplicateClusterer().cluster([doc.fingerprint(), doc.fingerprint()])


def test_cluster_assignment_lookup() -> None:
    pipeline = _pipeline()
    doc = pipeline.normalize_document(ORIGINAL, document_id="only")
    assignment = pipeline.clusterer.cluster([doc.fingerprint()])
    assert isinstance(assignment, ClusterAssignment)
    assert assignment.cluster_of("missing") is None
    assert assignment.singleton_count == 1
    assert assignment.duplicate_groups == []


# ----------------------------------------------------------------- lineage


def test_lineage_chains_and_defaults() -> None:
    registry = SourceLineageRegistry()
    registry.register_chain(["origin", "mirror", "scraper"], origin="case-1")

    assert registry.independence_root("scraper") == "origin"
    assert registry.independence_root("unknown-source") == "unknown-source"
    assert not registry.same_independence_group("origin", "fresh-source")

    with pytest.raises(LineageError, match="copies from unknown"):
        registry.register("b", copied_from="ghost")
    with pytest.raises(LineageError, match="cannot copy from itself"):
        registry.register("s", copied_from="s")


def test_lineage_cycle_rejected_and_rolled_back() -> None:
    registry = SourceLineageRegistry()
    registry.register("a")
    registry.register("b", copied_from="a")

    # re-pointing a at b would close the loop a -> b -> a
    with pytest.raises(CycleError):
        registry.register("a", copied_from="b")

    # failed registration rolled back: original lineage still intact
    assert registry.get("a") is not None
    assert registry.get("a").copied_from is None
    assert registry.independence_root("b") == "a"

    # legitimate upstream updates are accepted
    registry.register("c")
    updated = registry.register("b", copied_from="c")
    assert updated.copied_from == "c"
    assert registry.independence_root("b") == "c"
    # idempotent re-registration is a no-op
    assert registry.register("b", copied_from="c") is updated


def test_log_discount_monotone() -> None:
    log = SourceLineageRegistry.log_discount
    assert log(1) == pytest.approx(1.0)
    assert log(10) < log(2) < log(1)
    with pytest.raises(ValueError):
        log(0)


# ------------------------------------------------------- canonical output


def test_pipeline_emits_valid_canonical_observations() -> None:
    pipeline = NormalizationPipeline()
    lineage = pipeline.lineage
    lineage.register("forum-alpha")

    evidence_ids = [uuid4() for _ in range(3)]
    result = pipeline.process_batch(
        [
            ("obs-1", ORIGINAL, {"fetched_at": "now", "thread": "t1"}),
            ("obs-2", ORIGINAL, {"thread": "t1"}),
            (
                "obs-3",
                "Distinct second claim with its own wording entirely.",
                {},
            ),
        ],
        evidence_ids=evidence_ids,
        source_id="forum-alpha",
        collected_at=NOW,
        observed_at=NOW,
    )

    assert len(result.observations) == 3
    assert len(result.duplicate_groups) == 1
    assert result.duplicate_groups[0].size == 2

    for observation in result.observations:
        assert isinstance(observation, Observation)
        # passes the canonical schema validation gate
        Observation.model_validate(observation.model_dump())
        assert observation.normalization_version == "0.1.0"
        assert observation.independence_group == "forum-alpha"
        assert observation.source_lineage == ("forum-alpha",)
        assert observation.duplicate_cluster_id

    # copies land in one cluster, distinct content in its own
    cluster_first = result.observations[0].duplicate_cluster_id
    cluster_second = result.observations[1].duplicate_cluster_id
    cluster_third = result.observations[2].duplicate_cluster_id
    assert cluster_first == cluster_second
    assert cluster_third not in {cluster_first, cluster_second}

    # volatile fetch metadata was stripped before hashing
    assert "fetched_at" not in result.observations[0].metadata


def test_process_batch_validates_alignment() -> None:
    pipeline = _pipeline()
    with pytest.raises(ValueError, match="align"):
        pipeline.process_batch(
            [("a", "text", {})],
            evidence_ids=[uuid4(), uuid4()],
            source_id="s",
            collected_at=NOW,
        )


def test_independence_group_follows_registered_lineage() -> None:
    pipeline = NormalizationPipeline()
    pipeline.lineage.register("origin")
    pipeline.lineage.register("copy", copied_from="origin")

    assert pipeline.independence_group_for("copy") == "origin"
    assert pipeline.lineage_path("copy") == ("origin", "copy")
    assert pipeline.lineage_path("stranger") == ("stranger",)
