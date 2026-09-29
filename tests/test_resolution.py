"""Phase 09 entity-resolution tests (features, metrics, baselines, harness).

Covers the nine plan features and six plan metrics against
hand-computed examples, the five plan baselines in specification
order, and the frozen evaluation harness: actor-grouped split,
leakage audit against independent recomputation, handle-feature
ablation, cross-run determinism, and the train_baselines script's
experiment-registry artifact.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aegis.collection.corpus import SyntheticCorpusBuilder, build_default_corpus
from aegis.graph import InMemoryGraphStore, MissingNodeError, NodeLabel
from aegis.ontology import RelationshipType
from aegis.resolution.baselines import (
    CandidatePair,
    EditDistanceBaseline,
    ExactHandleBaseline,
    LogisticRegressionBaseline,
    TfIdfCosineBaseline,
    XgboostBaseline,
    all_baselines,
)
from aegis.resolution.evaluate import (
    ResolutionReport,
    build_activities,
    build_interaction_graph,
    evaluate_baselines,
    format_report,
    split_actors,
)
from aegis.resolution.features import (
    FEATURE_NAMES,
    AliasActivity,
    CandidatePairFeatures,
    PairFeatureExtractor,
    TfidfModel,
    char_ngram_counts,
    cosine_counts,
    handle_similarity,
    hour_histogram,
    levenshtein,
    normalize_handle,
    stable_hash_int,
    validate_feature_registry,
)
from aegis.resolution.metrics import (
    average_precision,
    best_f1_threshold,
    classification_metrics,
    precision_recall_f1,
    precision_recall_f1_at_threshold,
    ranking_metrics,
    recall_at_k,
    reciprocal_rank,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAMES = [
    "exact_handle",
    "edit_distance",
    "tfidf_cosine",
    "logistic_regression",
    "xgboost",
]
JAN = datetime(2026, 1, 1, tzinfo=UTC)
JUN = datetime(2026, 6, 1, tzinfo=UTC)


def _activity(
    alias_id: str,
    handle: str,
    *,
    platform: str = "forum_alpha",
    first_seen: datetime = JAN,
    last_seen: datetime = JUN,
    documents: tuple[str, ...] = (),
    timestamps: tuple[datetime, ...] = (),
) -> AliasActivity:
    return AliasActivity(
        alias_id=alias_id,
        handle=handle,
        platforms=frozenset({platform}),
        first_seen=first_seen,
        last_seen=last_seen,
        documents=documents,
        timestamps=timestamps,
    )


def _model(*documents: str, min_df: int = 1) -> TfidfModel:
    return TfidfModel.fit(list(documents), min_df=min_df)


# ---------------------------------------------------------- text helpers


def test_normalize_handle_folds_case_sigils_and_separators() -> None:
    assert normalize_handle("@Ghost.Broker") == normalize_handle("ghost_broker")
    assert normalize_handle("#Vendor--Shop") == normalize_handle("vendor shop")
    # full-width characters fold via NFKC
    assert normalize_handle("ｇｈｏｓｔ") == "ghost"
    assert normalize_handle("") == ""


def test_levenshtein_known_values() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("same", "same") == 0
    assert levenshtein("", "abc") == 3
    assert levenshtein("flaw", "") == 4
    assert levenshtein("ghost", "ghosts") == 1


def test_handle_similarity_bounds_and_ordering() -> None:
    assert handle_similarity("ghost", "ghost") == 1.0
    assert handle_similarity("", "") == 1.0
    assert handle_similarity("ghostbroker", "ghostbroker2") > handle_similarity(
        "ghostbroker", "alice1234"
    )
    assert 0.0 <= handle_similarity("a", "zzzzzzzzzz") <= 1.0


def test_char_ngrams_and_cosine() -> None:
    grams_a = char_ngram_counts("ghostbroker")
    grams_b = char_ngram_counts("ghostbroker")
    assert grams_a  # n-grams extracted
    assert cosine_counts(grams_a, grams_b) == pytest.approx(1.0)
    assert cosine_counts(grams_a, char_ngram_counts("totally-different")) < 0.5
    assert cosine_counts({}, {"x": 1.0}) == 0.0
    # identical dicts with known geometry: orthogonal -> 0
    assert cosine_counts({"a": 1.0}, {"b": 1.0}) == 0.0


def test_hour_histogram_bins() -> None:
    stamps = tuple(JAN + timedelta(hours=h) for h in (0, 0, 13, 23))
    histogram = hour_histogram(stamps)
    assert len(histogram) == 24
    assert histogram[0] == 2
    assert histogram[13] == 1
    assert histogram[23] == 1


# ---------------------------------------------------------- TF-IDF


def test_tfidf_fit_is_deterministic_and_vectors_normalize() -> None:
    documents = [
        "escrow fees stay fixed",
        "escrow fees rotate asap",
        "unrelated listing appears",
    ]
    first = TfidfModel.fit(documents, min_df=1)
    second = TfidfModel.fit(documents, min_df=1)
    assert first.vocabulary == second.vocabulary
    assert first.idf == second.idf

    vector = first.vectorize("escrow fees stay fixed")
    assert vector
    norm = sum(weight * weight for weight in vector.values()) ** 0.5
    assert norm == pytest.approx(1.0)


def test_tfidf_ignores_out_of_vocabulary_terms() -> None:
    model = TfidfModel.fit(["alpha beta", "alpha gamma"], min_df=1)
    unknown = model.vectorize("completely unrelated words")
    assert unknown == {}
    # partially known content keeps only in-vocabulary terms
    partial = model.vectorize("alpha novelterm")
    assert partial and all(isinstance(key, int) for key in partial)


def test_tfidf_min_df_filters_rare_terms() -> None:
    model = TfidfModel.fit(["rare shared", "other shared"], min_df=2)
    assert "shared" in model.vocabulary
    assert "rare" not in model.vocabulary


def test_tfidf_rejects_invalid_min_df() -> None:
    with pytest.raises(ValueError, match="min_df"):
        TfidfModel.fit(["a"], min_df=0)


# ---------------------------------------------------------- activities


def test_alias_activity_validation() -> None:
    with pytest.raises(ValueError, match="alias_id"):
        _activity("", "handle")
    with pytest.raises(ValueError, match="last_seen"):
        _activity("a", "h", first_seen=JUN, last_seen=JAN)
    with pytest.raises(ValueError, match="align"):
        _activity("a", "h", documents=("doc",), timestamps=())
    with pytest.raises(ValueError, match="timezone-aware"):
        _activity(
            "a",
            "h",
            first_seen=datetime(2026, 1, 1),  # naive
            last_seen=JUN,
        )


def test_feature_registry_stays_in_sync() -> None:
    validate_feature_registry()
    assert CandidatePairFeatures.feature_names() == FEATURE_NAMES


# ---------------------------------------------------------- extractor


def test_extractor_covers_all_nine_features() -> None:
    model = _model("escrow fees", "escrow rotation")
    extractor = PairFeatureExtractor(tfidf=model)
    left = _activity(
        "left",
        "@ghost.broker",
        documents=("escrow fees",),
        timestamps=(JAN + timedelta(hours=9),),
    )
    right = _activity(
        "right",
        "ghost-broker",
        platform="market_beta",
        documents=("escrow rotation",),
        timestamps=(JAN + timedelta(hours=9),),
    )
    features = extractor.extract(left, right)

    names = CandidatePairFeatures.feature_names()
    assert len(features.as_vector()) == len(names) == 9
    for name, value in zip(names, features.as_vector(), strict=True):
        assert 0.0 <= value <= 1.0, f"{name} out of [0, 1]: {value}"
    # handle signals strong: near-identical handles
    assert features.handle_similarity > 0.6
    assert features.char_ngram_similarity > 0.6
    # temporal: identical windows and same hour
    assert features.temporal_overlap == 1.0
    assert features.behavior_similarity == 1.0
    # no graph / no identifiers -> documented neutral defaults
    assert features.shared_identifier == 0.0
    assert features.graph_neighborhood_similarity == 0.0
    assert features.source_reliability == 0.5
    # different platforms -> zero marketplace overlap
    assert features.marketplace_overlap == 0.0


def test_extractor_temporal_overlap_partial_window() -> None:
    model = _model("a b", "a c")
    extractor = PairFeatureExtractor(tfidf=model)
    left = _activity("l", "h1", first_seen=JAN, last_seen=JUN)
    # right window overlaps the first quarter of 2026 only
    right = _activity("r", "h2", first_seen=JAN, last_seen=datetime(2026, 2, 1, tzinfo=UTC))
    features = extractor.extract(left, right)
    # overlap = Jan1-Feb1 (31d) / union = Jan1-Jun1 (152d)
    assert features.temporal_overlap == pytest.approx(31 / 152, abs=0.01)


def test_extractor_shared_identifier_jaccard_and_reliability() -> None:
    model = _model("a b", "c d")
    extractor = PairFeatureExtractor(
        tfidf=model,
        shared_identifiers={
            "l": frozenset({"wallet-1", "wallet-2"}),
            "r": frozenset({"wallet-2", "wallet-3"}),
        },
        source_reliability={"l": 1.0, "r": 0.0},
    )
    features = extractor.extract(_activity("l", "h1"), _activity("r", "h2"))
    assert features.shared_identifier == pytest.approx(1 / 3)  # |{2}| / |{1,2,3}|
    assert features.source_reliability == pytest.approx(0.5)  # mean(1.0, 0.0)


def test_extractor_rejects_out_of_range_reliability() -> None:
    model = _model("a b")
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        PairFeatureExtractor(tfidf=model, source_reliability={"x": 1.5})
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        PairFeatureExtractor(tfidf=model, default_reliability=-0.1)


def test_extractor_graph_feature_uses_store_and_fails_loudly() -> None:
    store = InMemoryGraphStore()
    for alias_id in ("l", "r", "mutual"):
        store.add_node(alias_id, NodeLabel.HANDLE)
    store.add_edge(
        RelationshipType.ASSOCIATED_WITH,
        "l",
        "mutual",
        first_seen=JAN,
        last_seen=JUN,
        confidence=1.0,
    )
    store.add_edge(
        RelationshipType.ASSOCIATED_WITH,
        "r",
        "mutual",
        first_seen=JAN,
        last_seen=JUN,
        confidence=1.0,
    )
    model = _model("a b", "c d")
    extractor = PairFeatureExtractor(tfidf=model, graph=store)
    features = extractor.extract(_activity("l", "h1"), _activity("r", "h2"))
    assert features.graph_neighborhood_similarity == 1.0  # shared neighbor "mutual"

    # unregistered alias nodes raise rather than silently defaulting
    with pytest.raises(MissingNodeError):
        extractor.extract(_activity("ghost", "h3"), _activity("r", "h2"))


def test_extractor_behavior_similarity_needs_activity_on_both_sides() -> None:
    model = _model("a b", "c d")
    extractor = PairFeatureExtractor(tfidf=model)
    active = _activity(
        "l",
        "h1",
        documents=("post one", "post two", "post three"),
        timestamps=(JAN + timedelta(hours=1),) * 3,
    )
    dormant = _activity("r", "h2")
    assert extractor.extract(active, dormant).behavior_similarity == 0.0
    assert extractor.extract(dormant, dormant).behavior_similarity == 0.0


def test_stable_hash_is_deterministic() -> None:
    assert stable_hash_int("actor-1") == stable_hash_int("actor-1")
    assert stable_hash_int("actor-1", seed=1) != stable_hash_int("actor-1", seed=2)


# ---------------------------------------------------------- metrics


def test_precision_recall_f1_hand_computed() -> None:
    predicted = [True, True, False, False, True]
    actual = [True, False, True, False, True]
    precision, recall, f1 = precision_recall_f1(predicted, actual)
    assert precision == pytest.approx(2 / 3)
    assert recall == pytest.approx(2 / 3)
    assert f1 == pytest.approx(2 / 3)


def test_precision_recall_f1_zero_denominator() -> None:
    precision, recall, f1 = precision_recall_f1([False, False], [False, True])
    assert precision == 0.0  # predicted nothing
    assert recall == 0.0
    assert f1 == 0.0


def test_average_precision_hand_computed() -> None:
    # ranks: score .9 (label 1) -> P@1 = 1; score .8 (label 0); score .4 (label 1) -> P@3 = 2/3
    # AP = (1 + 2/3) / 2
    assert average_precision([0.9, 0.8, 0.4], [1, 0, 1]) == pytest.approx((1 + 2 / 3) / 2)
    assert average_precision([0.5, 0.4], [0, 0]) == 0.0  # no positives
    with pytest.raises(ValueError, match="align"):
        average_precision([0.5], [1, 0])


def test_threshold_metrics_and_best_threshold() -> None:
    scores = [0.9, 0.6, 0.4, 0.2]
    labels = [1, 1, 0, 0]
    precision, recall, f1 = precision_recall_f1_at_threshold(scores, labels, 0.5)
    assert (precision, recall, f1) == (1.0, 1.0, 1.0)
    # best F1 over the candidate thresholds separates cleanly
    assert best_f1_threshold(scores, labels) == pytest.approx(0.6)
    with pytest.raises(ValueError, match="threshold"):
        best_f1_threshold([], [])


def test_reciprocal_rank_and_recall_at_k() -> None:
    assert reciprocal_rank([0, 1, 1]) == pytest.approx(0.5)
    assert reciprocal_rank([1, 1]) == 1.0
    assert reciprocal_rank([0, 0]) == 0.0
    assert recall_at_k([1, 0, 1, 1], 2) == pytest.approx(1 / 3)
    assert recall_at_k([0, 0], 3) == 0.0
    with pytest.raises(ValueError, match="k"):
        recall_at_k([1], 0)


def test_ranking_metrics_average_over_queries() -> None:
    metrics = ranking_metrics([[1, 0], [0, 1, 0]], k=1)
    # query 1: RR = 1, R@1 = 1; query 2: RR = 1/2, R@1 = 0
    assert metrics.mrr == pytest.approx(0.75)
    assert metrics.recall_at_k == pytest.approx(0.5)
    assert metrics.query_count == 2
    assert metrics.k == 1
    empty = ranking_metrics([], k=5)
    assert empty.mrr == 0.0 and empty.query_count == 0
    with pytest.raises(ValueError, match="k"):
        ranking_metrics([[1]], k=0)


def test_classification_metrics_combines_both_families() -> None:
    metrics = classification_metrics([0.9, 0.2, 0.7, 0.1], [1, 0, 1, 0], threshold=0.5)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0
    assert metrics.pr_auc == 1.0


# ---------------------------------------------------------- baselines


def _features(**overrides: float) -> CandidatePairFeatures:
    base: dict[str, float] = {
        "handle_similarity": 0.5,
        "char_ngram_similarity": 0.5,
        "text_similarity": 0.5,
        "temporal_overlap": 0.5,
        "shared_identifier": 0.0,
        "marketplace_overlap": 0.0,
        "behavior_similarity": 0.5,
        "graph_neighborhood_similarity": 0.0,
        "source_reliability": 0.5,
    }
    base.update(overrides)
    return CandidatePairFeatures(**base)  # type: ignore[arg-type]


def _pair(
    *,
    label: int = 0,
    left_handle: str = "ghost",
    right_handle: str = "ghost2",
    features: CandidatePairFeatures | None = None,
) -> CandidatePair:
    return CandidatePair(
        left_alias_id="alias-left",
        right_alias_id="alias-right",
        left_handle=left_handle,
        right_handle=right_handle,
        features=features if features is not None else _features(),
        label=label,
    )


def _separable_pairs() -> list[CandidatePair]:
    """Alternating positives/negatives separable by handle + text signal."""
    pairs: list[CandidatePair] = []
    for index in range(40):
        positive = index % 2 == 0
        pairs.append(
            _pair(
                label=int(positive),
                left_handle=f"handle-{index}-a",
                right_handle=f"handle-{index}-b" if positive else f"other-{index}",
                features=_features(
                    handle_similarity=0.92 if positive else 0.08,
                    char_ngram_similarity=0.88 if positive else 0.12,
                    text_similarity=0.9 if positive else 0.1,
                ),
            )
        )
    return pairs


def test_all_baselines_in_plan_order() -> None:
    assert [model.name for model in all_baselines()] == BASELINE_NAMES


def test_exact_handle_baseline_normalizes_before_comparing() -> None:
    baseline = ExactHandleBaseline()
    assert baseline.score(_pair(left_handle="@Ghost.Broker", right_handle="ghost_broker")) == 1.0
    assert baseline.score(_pair(left_handle="ghost", right_handle="ghosts")) == 0.0
    assert baseline.score(_pair(left_handle="", right_handle="")) == 0.0


def test_edit_distance_baseline_bounds_symmetry_and_ordering() -> None:
    baseline = EditDistanceBaseline()
    close = baseline.score(_pair(left_handle="ghostbroker", right_handle="ghostbroker2"))
    far = baseline.score(_pair(left_handle="ghostbroker", right_handle="alice1234"))
    assert 0.0 <= far < close <= 1.0
    swapped = baseline.score(_pair(left_handle="abc", right_handle="abd"))
    original = baseline.score(_pair(left_handle="abd", right_handle="abc"))
    assert swapped == original


def test_tfidf_cosine_baseline_reads_text_feature() -> None:
    baseline = TfIdfCosineBaseline()
    assert baseline.score(_pair(features=_features(text_similarity=0.75))) == 0.75


def test_stateless_baselines_ignore_fit() -> None:
    ExactHandleBaseline().fit([])
    EditDistanceBaseline().fit([])
    TfIdfCosineBaseline().fit([])


def test_learned_baselines_fail_loudly_before_fit() -> None:
    for baseline in (LogisticRegressionBaseline(), XgboostBaseline()):
        assert baseline.fitted is False
        with pytest.raises(RuntimeError, match="fit"):
            baseline.score(_pair())
        with pytest.raises(ValueError, match="empty"):
            baseline.fit([])


def test_logistic_regression_separates_and_is_deterministic() -> None:
    pairs = _separable_pairs()
    first, second = LogisticRegressionBaseline(), LogisticRegressionBaseline()
    first.fit(pairs)
    second.fit(pairs)
    assert first.fitted and second.fitted

    positive = _pair(
        label=1,
        features=_features(handle_similarity=0.95, text_similarity=0.92),
    )
    negative = _pair(
        label=0,
        features=_features(handle_similarity=0.05, text_similarity=0.08),
    )
    assert first.score(positive) > first.score(negative)
    assert first.score(positive) == second.score(positive)  # bit-identical full-batch GD
    assert all(0.0 <= first.score(pair) <= 1.0 for pair in pairs)


def test_xgboost_separates_and_is_deterministic() -> None:
    pairs = _separable_pairs()
    first, second = XgboostBaseline(), XgboostBaseline()
    first.fit(pairs)
    second.fit(pairs)

    positive = _pair(
        label=1,
        features=_features(handle_similarity=0.95, text_similarity=0.92),
    )
    negative = _pair(
        label=0,
        features=_features(handle_similarity=0.05, text_similarity=0.08),
    )
    assert first.score(positive) > first.score(negative)
    assert first.score(positive) == second.score(positive)  # fixed seed, nthread=1
    assert all(0.0 <= first.score(pair) <= 1.0 for pair in pairs)


def test_xgboost_dmatrix_constrains_its_own_openmp_team(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the invariant that stops the full suite dying with SIGSEGV.

    torch and xgboost wheels each ship their own LLVM libomp under different
    install names, so dyld loads both and an OpenMP team xgboost forks reads a
    kmp_info allocated by the other runtime. Setting ``params["nthread"]`` is
    not enough on its own: it throttles the booster, while the crashing team
    belongs to DMatrix's own SparsePage::Push. Asserting on the recorded kwarg
    is the only way to guard this, because a regression segfaults the process
    instead of failing an assertion.
    """
    import xgboost

    recorded: list[object] = []
    real_dmatrix = xgboost.DMatrix

    def _recording_dmatrix(*args: object, **kwargs: object) -> object:
        recorded.append(kwargs.get("nthread"))
        return real_dmatrix(*args, **kwargs)

    monkeypatch.setattr(xgboost, "DMatrix", _recording_dmatrix)

    model = XgboostBaseline()
    model.fit(_separable_pairs())
    model.score(_pair(label=1, features=_features(handle_similarity=0.95, text_similarity=0.92)))

    assert recorded, "no DMatrix was constructed"
    assert recorded == [1] * len(recorded)


# ---------------------------------------------------------- split + harness


def test_split_actors_deterministic_disjoint_and_complete() -> None:
    corpus = SyntheticCorpusBuilder(seed=7, actor_count=40, post_count=200).build()
    train, test = split_actors(corpus)
    assert train and test
    assert train.isdisjoint(test)
    assert train | test == {actor.actor_id for actor in corpus.actors}
    assert split_actors(corpus) == (train, test)


def test_split_actors_rejects_bad_fraction() -> None:
    corpus = SyntheticCorpusBuilder(seed=7, actor_count=10, post_count=50).build()
    for bad in (0.0, 1.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="train_fraction"):
            split_actors(corpus, train_fraction=bad)


def test_evaluate_rejects_invalid_arguments() -> None:
    corpus = SyntheticCorpusBuilder(seed=7, actor_count=10, post_count=50).build()
    with pytest.raises(ValueError, match="negatives_per_positive"):
        evaluate_baselines(corpus, negatives_per_positive=-1)


def test_build_activities_aggregates_posts_per_alias() -> None:
    corpus = SyntheticCorpusBuilder(seed=7, actor_count=20, post_count=200).build()
    activities = build_activities(corpus)
    assert set(activities) == {alias.alias_id for alias in corpus.aliases}

    posts_by_alias: dict[str, int] = {}
    for post in corpus.posts:
        posts_by_alias[post.alias_id] = posts_by_alias.get(post.alias_id, 0) + 1
    for alias in corpus.aliases:
        activity = activities[alias.alias_id]
        assert len(activity.documents) == posts_by_alias.get(alias.alias_id, 0)
        assert activity.platforms == frozenset({alias.platform})
        assert list(activity.timestamps) == sorted(activity.timestamps)


def test_build_interaction_graph_structure() -> None:
    corpus = SyntheticCorpusBuilder(seed=7, actor_count=20, post_count=200).build()
    store = build_interaction_graph(corpus)
    assert set(store.nodes) == {alias.alias_id for alias in corpus.aliases}
    edges = store.edges
    assert edges  # fixture carries reply/mention relationships
    for edge in edges.values():
        assert edge.source != edge.target  # same-alias links are skipped
        assert edge.source in store.nodes and edge.target in store.nodes
        assert edge.first_seen <= edge.last_seen
        assert edge.rel_type == RelationshipType.ASSOCIATED_WITH


@pytest.fixture(scope="module")
def frozen_report() -> ResolutionReport:
    """One default-corpus run, shared by the report-consuming tests."""
    return evaluate_baselines()


def test_frozen_report_structure_and_leakage_audit(frozen_report: ResolutionReport) -> None:
    corpus = build_default_corpus()
    report = frozen_report

    assert [baseline.name for baseline in report.baselines] == BASELINE_NAMES
    assert report.corpus_seed == 26151
    assert report.split_seed == 26151

    for baseline in report.baselines:
        metrics = baseline.metrics
        for value in (
            metrics.precision,
            metrics.recall,
            metrics.f1,
            metrics.pr_auc,
            metrics.mrr,
            metrics.recall_at_k,
        ):
            assert 0.0 <= value <= 1.0, f"{baseline.name}: {value} out of [0, 1]"
        assert 0.0 <= baseline.threshold <= 1.0
        assert metrics.k == report.k

    # independent recomputation of the split: the reported counts must match
    # pairs fully contained in each side — any cross-split leakage would break
    # these equalities.
    train_actors, test_actors = split_actors(
        corpus, seed=report.split_seed, train_fraction=report.train_fraction
    )
    train_aliases = {a.alias_id for a in corpus.aliases if a.actor_id in train_actors}
    test_aliases = {a.alias_id for a in corpus.aliases if a.actor_id in test_actors}
    assert train_aliases.isdisjoint(test_aliases)

    expected_train_positives = sum(
        1
        for left, right in corpus.same_actor_pairs
        if left in train_aliases and right in train_aliases
    )
    expected_test_positives = sum(
        1
        for left, right in corpus.same_actor_pairs
        if left in test_aliases and right in test_aliases
    )
    assert report.train_positives == expected_train_positives
    assert report.test_positives == expected_test_positives
    assert report.test_pairs == len(test_aliases) * (len(test_aliases) - 1) // 2
    assert report.query_count == len(test_aliases)
    # deterministic 4-per-positive train sampling (not capped at the pool size)
    assert report.train_pairs == report.train_positives * (report.negatives_per_positive + 1)

    # fixture property (documented in evaluate.py): handle features embed the
    # actor id, so the learned baselines separate the frozen test split cleanly.
    assert report.by_name("logistic_regression").metrics.pr_auc >= 0.99
    assert report.by_name("xgboost").metrics.pr_auc >= 0.99
    assert (
        report.by_name("logistic_regression").metrics.f1
        >= report.by_name("tfidf_cosine").metrics.f1
    )


def test_format_report_and_json_round_trip(frozen_report: ResolutionReport) -> None:
    text = format_report(frozen_report)
    for name in BASELINE_NAMES:
        assert name in text
    assert str(frozen_report.corpus_seed) in text

    payload = json.loads(frozen_report.to_json())
    assert payload["baselines"][0]["name"] == "exact_handle"
    assert payload["train_pairs"] == frozen_report.train_pairs
    assert payload["use_graph"] is True

    with pytest.raises(KeyError, match="not in report"):
        frozen_report.by_name("no_such_baseline")


def test_exclude_handle_features_ablation(frozen_report: ResolutionReport) -> None:
    corpus = build_default_corpus()
    ablated = evaluate_baselines(corpus, exclude_handle_features=True)
    assert ablated.exclude_handle_features is True
    assert ablated.test_pairs == frozen_report.test_pairs  # same split, same space

    full_lr = frozen_report.by_name("logistic_regression").metrics
    ablated_lr = ablated.by_name("logistic_regression").metrics
    assert ablated_lr.f1 < full_lr.f1  # the fixture's actor signal lives in handles

    # raw baselines never read the nine features -> identical under the ablation
    for name in ("exact_handle", "edit_distance", "tfidf_cosine"):
        assert ablated.by_name(name).as_dict() == frozen_report.by_name(name).as_dict()


def test_evaluate_baselines_deterministic_on_small_corpus() -> None:
    corpus = SyntheticCorpusBuilder(seed=99, actor_count=30, post_count=300).build()
    first = evaluate_baselines(corpus)
    second = evaluate_baselines(corpus)
    assert first.as_dict() == second.as_dict()
    assert first.train_positives > 0 and first.test_positives > 0
    assert len(first.baselines) == len(BASELINE_NAMES)


def test_train_baselines_script_writes_registry(
    tmp_path: Path, frozen_report: ResolutionReport
) -> None:
    script = REPO_ROOT / "scripts" / "train_baselines.py"
    spec = importlib.util.spec_from_file_location("train_baselines", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main(["--output-dir", str(tmp_path)]) == 0
    payload = json.loads((tmp_path / "resolution_baselines.json").read_text(encoding="utf-8"))

    assert payload["experiment_id"] == "phase09-resolution-baselines"
    assert payload["seed"] == frozen_report.split_seed
    assert payload["git_commit"]
    assert set(payload["metrics"]) == set(BASELINE_NAMES)
    assert payload["report"] == frozen_report.as_dict()  # second run reproduces exactly

    hyper = payload["hyperparameters"]
    assert hyper["train_fraction"] == frozen_report.train_fraction
    assert hyper["negatives_per_positive"] == frozen_report.negatives_per_positive
    assert hyper["k"] == frozen_report.k
    assert hyper["use_graph"] is True
    assert hyper["exclude_handle_features"] is False
