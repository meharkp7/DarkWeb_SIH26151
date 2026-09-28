"""Phase 11 stylometry tests.

Covers the plan's six steps in order — n-grams, classical features,
embeddings, the pairwise verification model, cross-marketplace
evaluation, adversarial transformations — and pins the four required
outputs (baseline metrics, cross-domain metrics, robustness curve,
error analysis). Every metrics assertion reports precision/recall/F1/
PR-AUC, never accuracy alone, mirroring the phase's metric policy.

The corpus-seeded evaluation runs once per module (fixtures are
module-scoped) because a full report takes a few seconds.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import random

import pytest

from aegis.collection.corpus import SyntheticCorpus, build_default_corpus
from aegis.stylometry import (
    DEFAULT_SEVERITIES,
    PAIR_FEATURE_NAMES,
    EmbeddingBackendUnavailable,
    EmbeddingProvider,
    EvaluationReport,
    HashingEmbeddingProvider,
    NGramConfig,
    NGramVectorizer,
    PairFeatureExtractor,
    PairFeatures,
    SentenceTransformerEmbeddingProvider,
    StylometricFeatures,
    StylometryEvaluator,
    VerificationModel,
    add_noise,
    apply_transform,
    average_precision,
    best_f1_threshold,
    build_alias_documents,
    candidate_pairs,
    change_case,
    character_ngrams,
    cosine_similarity,
    counter_cosine,
    embed_cosine,
    hashed_ngram_vector,
    normalize_slang,
    paraphrase,
    remove_punctuation,
    run_full_evaluation,
    shorten,
    stratified_split,
    stylometric_similarity,
    tokenize_words,
    translate,
    word_ngrams,
)
from aegis.stylometry.evaluation import (
    ClassificationMetrics,
    LabeledPair,
    build_alias_contexts,
)
from aegis.stylometry.features import FEATURE_NAMES, FUNCTION_WORDS
from aegis.stylometry.transforms import TRANSFORM_NAMES

# ---------------------------------------------------------------------------
# module-scoped fixtures: one full evaluation report, reused everywhere
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> SyntheticCorpus:
    """The Phase-05 deterministic fixture (100 actors / 1,000 posts)."""
    return build_default_corpus(seed=26151)


@pytest.fixture(scope="module")
def evaluator(corpus: SyntheticCorpus) -> StylometryEvaluator:
    return StylometryEvaluator(corpus)


@pytest.fixture(scope="module")
def report(evaluator: StylometryEvaluator) -> EvaluationReport:
    """The full Phase-11 report (baseline + cross-domain + robustness)."""
    return evaluator.report


# ---------------------------------------------------------------------------
# step 1 — character and word n-grams
# ---------------------------------------------------------------------------


def test_character_ngrams_counts_and_validation() -> None:
    counts = character_ngrams("aaa", 2)
    assert counts == {"aa": 2}
    assert character_ngrams("", 3) == {}
    assert character_ngrams("ab", 5) == {"ab": 1}
    assert character_ngrams("AaA", 2, lowercase=False) == {"Aa": 1, "aA": 1}
    with pytest.raises(ValueError):
        character_ngrams("abc", 0)


def test_word_ngrams_counts() -> None:
    counts = word_ngrams("to be or not to be", 2)
    assert counts["to be"] == 2
    assert counts["be or"] == 1
    assert word_ngrams("", 1) == {}
    with pytest.raises(ValueError):
        word_ngrams("a b", 0)


def test_tokenize_words_options() -> None:
    assert tokenize_words("Hello WORLD") == ["hello", "world"]
    assert tokenize_words("Hello", lowercase=False) == ["Hello"]
    assert tokenize_words("abc 123 def4x9", exclude_numeric=True) == ["abc"]


def test_counter_cosine_and_dense_cosine() -> None:
    assert counter_cosine({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.0}) == pytest.approx(1.0)
    assert counter_cosine({"a": 1.0}, {"b": 1.0}) == 0.0
    assert counter_cosine({}, {"b": 1.0}) == 0.0
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == 0.0
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0, 0.0)) == 0.0
    assert cosine_similarity((), ()) == 0.0


def test_ngram_vectorizer_is_deterministic_and_normalized() -> None:
    texts = ["escrow fees stay fixed", "vendor rotation asap", "mirror session leaks"]
    first = NGramVectorizer().fit(texts)
    second = NGramVectorizer().fit(texts)
    vector = first.transform(texts[0])
    assert vector == second.transform(texts[0])
    assert first.vocabulary_size <= first.config.max_features
    assert sum(value * value for value in vector) == pytest.approx(1.0)
    assert first.similarity(texts[0], texts[0]) == pytest.approx(1.0)
    assert first.similarity(texts[0], texts[1]) < 1.0


def test_ngram_vectorizer_requires_fit_and_config_validation() -> None:
    with pytest.raises(RuntimeError):
        NGramVectorizer().transform("anything")
    with pytest.raises(ValueError):
        NGramConfig(char_min=0)
    with pytest.raises(ValueError):
        NGramConfig(include_chars=False, include_words=False)
    with pytest.raises(ValueError):
        NGramConfig(word_max=0)


def test_hashed_ngram_vector_properties() -> None:
    vector = hashed_ngram_vector("escrow fees stay fixed", 128)
    assert len(vector) == 128
    assert sum(value * value for value in vector) == pytest.approx(1.0)
    assert vector == hashed_ngram_vector("escrow fees stay fixed", 128)
    # a bare serial number barely moves the vector (word grams are exactly
    # digit-invariant; char grams only shift around the digit's whitespace)
    serial = hashed_ngram_vector("escrow fees stay 42 fixed", 128)
    assert word_ngrams("escrow fees stay fixed", 1, exclude_numeric=True) == word_ngrams(
        "escrow fees stay 42 fixed", 1, exclude_numeric=True
    )
    assert cosine_similarity(vector, serial) > 0.8
    different = hashed_ngram_vector("vendor listing rotation", 128)
    assert cosine_similarity(vector, different) < 0.2
    assert vector != different
    assert hashed_ngram_vector("", 16) == (0.0,) * 16
    with pytest.raises(ValueError):
        hashed_ngram_vector("abc", 0)


# ---------------------------------------------------------------------------
# step 2 — classical stylometric features
# ---------------------------------------------------------------------------


def test_stylometric_features_from_text() -> None:
    text = "Hello there! This is a TEST, version 2. ok?"
    features = StylometricFeatures.from_text(text)
    assert features.word_count == 9
    assert features.sentence_count == 3
    assert 0.0 < features.punctuation_ratio < 1.0
    assert 0.0 < features.uppercase_ratio < 1.0
    assert 0.0 < features.digit_ratio < 1.0
    assert 0.0 < features.type_token_ratio <= 1.0
    assert 0.0 < features.hapax_ratio <= 1.0
    assert features.word_entropy > 0.0
    assert len(features.as_vector()) == len(FEATURE_NAMES)
    assert set(FUNCTION_WORDS) >= {"the", "and", "of"}


def test_stylometric_features_empty_text_is_zero() -> None:
    features = StylometricFeatures.from_text("")
    assert features.as_vector() == (0.0,) * len(FEATURE_NAMES)


def test_stylometric_similarity_identity_and_difference() -> None:
    text = "fees stay fixed, escrow rotation asap."
    features = StylometricFeatures.from_text(text)
    assert stylometric_similarity(features, features) == pytest.approx(1.0)
    empty = StylometricFeatures.from_text("")
    noisy = StylometricFeatures.from_text(
        "WAIT -- REALLY?! 42 things happened here, again and again, loudly!!!"
    )
    assert stylometric_similarity(features, noisy) < 0.95
    assert stylometric_similarity(empty, features) < 1.0


# ---------------------------------------------------------------------------
# step 3 — embeddings (baseline stand-in + lazy optional backend)
# ---------------------------------------------------------------------------


def test_hashing_embedding_provider_properties() -> None:
    provider = HashingEmbeddingProvider(dimensions=64, seed=7)
    assert provider.name == "hashing-baseline"
    assert provider.dimensions == 64
    assert isinstance(provider, EmbeddingProvider)

    vector = provider.embed("escrow fees stay fixed")
    assert len(vector) == 64
    assert sum(value * value for value in vector) == pytest.approx(1.0)
    assert vector == provider.embed("escrow fees stay fixed")
    assert embed_cosine(vector, vector) == pytest.approx(1.0)
    assert embed_cosine(vector, provider.embed("totally different words here")) < 1.0
    assert provider.embed("") == (0.0,) * 64
    assert provider.embed_many(["a", "b"]) == [provider.embed("a"), provider.embed("b")]
    with pytest.raises(ValueError):
        HashingEmbeddingProvider(dimensions=0)


def test_sentence_transformer_backend_is_lazy() -> None:
    provider = SentenceTransformerEmbeddingProvider()
    assert provider.name.startswith("sentence-transformer:")
    if importlib.util.find_spec("sentence_transformers") is not None:  # pragma: no cover
        pytest.skip("optional backend installed; unavailable-path not testable")
    with pytest.raises(EmbeddingBackendUnavailable):
        provider.embed("hello")
    with pytest.raises(EmbeddingBackendUnavailable):
        _ = provider.dimensions


def test_embed_cosine_edge_cases() -> None:
    assert embed_cosine((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert embed_cosine((1.0, 0.0), (0.0, 1.0)) == 0.0
    assert embed_cosine((1.0,), (1.0, 2.0)) == 0.0
    assert embed_cosine((), ()) == 0.0


# ---------------------------------------------------------------------------
# step 4 — pairwise verification model
# ---------------------------------------------------------------------------


def test_pair_features_shape_and_validation() -> None:
    assert len(PAIR_FEATURE_NAMES) == 8
    with pytest.raises(ValueError):
        PairFeatures((1.0, 1.0))
    with pytest.raises(ValueError):
        PairFeatures((2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))


def test_pair_feature_extractor_requires_fit(corpus: SyntheticCorpus) -> None:
    extractor = PairFeatureExtractor()
    with pytest.raises(RuntimeError):
        extractor.features("left", "right")
    with pytest.raises(ValueError):
        PairFeatureExtractor(distinctive_max_df=1.5)


def test_pair_feature_extractor_features(corpus: SyntheticCorpus) -> None:
    documents = build_alias_documents(corpus)
    texts = [text for text in documents.values() if text.strip()]
    extractor = PairFeatureExtractor().fit(texts[:120])
    left, right = texts[0], texts[1]
    features = extractor.features(left, right)
    assert len(features.values) == 8
    assert all(-1.0 <= value <= 1.0 for value in features.values)
    assert features == extractor.features(left, right)
    # the idiolect lexicon captures markers, not template vocabulary
    vocabulary = extractor.distinctive_vocabulary
    assert vocabulary
    assert "imo" in vocabulary  # class-0 informal marker
    assert "fees" not in vocabulary  # shared template word


def test_verification_model_learns_and_is_deterministic() -> None:
    rng = random.Random(26151)
    rows: list[tuple[float, float]] = []
    labels: list[int] = []
    for _ in range(60):
        rows.append((1.0 + rng.uniform(-0.15, 0.15), 1.0 + rng.uniform(-0.15, 0.15)))
        labels.append(1)
        rows.append((0.0 + rng.uniform(-0.15, 0.15), 0.0 + rng.uniform(-0.15, 0.15)))
        labels.append(0)

    first = VerificationModel.train(rows, labels, epochs=200, seed=42)
    second = VerificationModel.train(rows, labels, epochs=200, seed=42)
    assert first.weights == second.weights
    assert first.bias == second.bias
    assert all(weight >= 0.0 for weight in first.weights)  # monotone by construction

    correct = sum(
        1
        for row, label in zip(rows, labels, strict=True)
        if (first.predict_proba(row) >= 0.5) == bool(label)
    )
    assert correct / len(rows) >= 0.95
    assert first.predict_proba((1.0, 1.0)) > first.predict_proba((0.0, 0.0))


def test_verification_model_validation_errors() -> None:
    with pytest.raises(ValueError):
        VerificationModel.train([], [])
    with pytest.raises(ValueError):
        VerificationModel.train([(1.0, 2.0)], [1])  # single class
    with pytest.raises(ValueError):
        VerificationModel.train([(1.0, 2.0)], [0, 1])  # length mismatch
    with pytest.raises(ValueError):
        VerificationModel.train([(1.0,)], [0, 1], epochs=0)


def test_verification_model_predict_validation() -> None:
    model = VerificationModel.train([(1.0, 1.0), (0.0, 0.0)], [1, 0], epochs=50)
    with pytest.raises(ValueError):
        model.predict_proba((1.0,))  # wrong width


# ---------------------------------------------------------------------------
# steps 5+6 — evaluation: candidates, splits, metrics
# ---------------------------------------------------------------------------


def test_build_alias_documents_covers_all_posts(corpus: SyntheticCorpus) -> None:
    documents = build_alias_documents(corpus)
    assert set(documents) == {alias.alias_id for alias in corpus.aliases}
    for post in corpus.posts:
        assert post.body in documents[post.alias_id]


def test_candidate_pairs_are_labelled_and_deterministic(corpus: SyntheticCorpus) -> None:
    documents = build_alias_documents(corpus)
    pairs = candidate_pairs(corpus, documents)
    assert pairs == candidate_pairs(corpus, documents)

    positives = [pair for pair in pairs if pair.label == 1]
    negatives = [pair for pair in pairs if pair.label == 0]
    assert len(positives) == 310  # verifiable subset of the 336 ground-truth pairs
    assert len(negatives) == 3 * len(positives)

    actors = {alias.alias_id: alias.actor_id for alias in corpus.aliases}
    assert all(actors[left] != actors[right] for left, right in (p.key for p in negatives))
    empty = {alias_id for alias_id, text in documents.items() if not text.strip()}
    assert all(left not in empty and right not in empty for left, right in (p.key for p in pairs))


def test_stratified_split_properties_and_determinism() -> None:
    pairs = [LabeledPair(f"l{i}", f"r{i}", 1) for i in range(10)]
    pairs += [LabeledPair(f"x{i}", f"y{i}", 0) for i in range(10)]
    train, test = stratified_split(pairs, test_ratio=0.3, seed=1)
    assert (train, test) == stratified_split(pairs, test_ratio=0.3, seed=1)
    assert len(test) == 6 and len(train) == 14
    assert {pair.label for pair in train} == {0, 1}
    assert {pair.label for pair in test} == {0, 1}
    assert {p.key for p in train} & {p.key for p in test} == set()
    assert {p.key for p in train} | {p.key for p in test} == {p.key for p in pairs}
    with pytest.raises(ValueError):
        stratified_split(pairs, test_ratio=1.5)


def test_average_precision_values() -> None:
    # canonical argument order is (scores, labels) — shared with aegis.resolution
    assert average_precision([0.9, 0.8, 0.7, 0.6], [1, 1, 0, 0]) == pytest.approx(1.0)
    assert average_precision([0.1, 0.2, 0.9, 0.8], [1, 1, 0, 0]) == pytest.approx(0.417, abs=1e-3)
    assert average_precision([0.5, 0.5], [0, 0]) == 0.0
    with pytest.raises(ValueError, match="align"):
        average_precision([0.5, 0.5], [1])
    # swapped (labels, scores) arguments are caught by the label-domain guard
    with pytest.raises(ValueError, match="labels must be 0 or 1"):
        average_precision([1, 1, 0, 0], [0.9, 0.8, 0.7, 0.6])


def test_best_f1_threshold_picks_separating_cutoff() -> None:
    labels = [1, 1, 0, 0]
    scores = [0.9, 0.6, 0.55, 0.1]
    # expectation unchanged by the tie-break unification: F1 = 1.0 at 0.6 is a
    # unique maximum, so "highest threshold" and "closest to 0.5" agree here
    assert best_f1_threshold(scores, labels) == pytest.approx(0.6)
    with pytest.raises(ValueError, match="threshold"):
        best_f1_threshold([], [])


def test_classification_metrics_from_scores() -> None:
    metrics = ClassificationMetrics.from_scores([1, 0, 1, 0], [0.9, 0.2, 0.4, 0.8], threshold=0.5)
    assert (metrics.true_positives, metrics.false_positives) == (1, 1)
    assert (metrics.false_negatives, metrics.true_negatives) == (1, 1)
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.f1 == 0.5
    assert metrics.pr_auc == pytest.approx(0.833, abs=1e-3)
    assert metrics.accuracy == 0.5
    # the phase says "do not report only accuracy" — the richer fields exist
    names = {field.name for field in dataclasses.fields(ClassificationMetrics)}
    assert {"precision", "recall", "f1", "pr_auc"} <= names
    with pytest.raises(ValueError):
        ClassificationMetrics.from_scores([], [])


# ---------------------------------------------------------------------------
# required output 1 — baseline metrics
# ---------------------------------------------------------------------------


def test_baseline_metrics(report: EvaluationReport) -> None:
    baseline = report.baseline
    assert baseline.train_pair_count + baseline.test_pair_count == report.candidate_pair_count
    assert 0.0 < baseline.threshold < 0.5
    test = baseline.test_metrics
    # exact pin: deterministic model on the frozen corpus
    assert test == ClassificationMetrics(
        true_positives=69,
        false_positives=45,
        false_negatives=24,
        true_negatives=234,
        precision=0.605,
        recall=0.742,
        f1=0.667,
        pr_auc=0.596,
        accuracy=0.815,
        false_positive_rate=0.161,
    )
    train = baseline.train_metrics
    assert train.precision >= 0.55
    assert train.recall >= 0.70
    assert train.f1 >= 0.60
    assert train.pr_auc >= 0.50


# ---------------------------------------------------------------------------
# required output 2 — cross-marketplace (cross-domain) metrics
# ---------------------------------------------------------------------------


def test_cross_marketplace_metrics(report: EvaluationReport) -> None:
    cross = report.cross_domain
    assert (cross.train_platform, cross.test_platform) == ("forum_alpha", "market_beta")
    assert cross.train_pair_count > 0 and cross.test_pair_count > 0
    # train and test share no pairs (disjoint marketplace domains)
    assert cross.train_pair_count + cross.test_pair_count < report.candidate_pair_count
    test = cross.test_metrics
    assert test == ClassificationMetrics(
        true_positives=61,
        false_positives=33,
        false_negatives=35,
        true_negatives=204,
        precision=0.649,
        recall=0.635,
        f1=0.642,
        pr_auc=0.609,
        accuracy=0.796,
        false_positive_rate=0.139,
    )
    # cross-marketplace transfer costs only a few F1 points
    assert test.f1 >= report.baseline.test_metrics.f1 - 0.05


def test_evaluator_rejects_same_platform_split(corpus: SyntheticCorpus) -> None:
    with pytest.raises(ValueError):
        StylometryEvaluator(corpus, train_platform="forum_alpha", test_platform="forum_alpha")


# ---------------------------------------------------------------------------
# required output 3 — robustness curve
# ---------------------------------------------------------------------------


def test_robustness_curve_covers_every_transform(report: EvaluationReport) -> None:
    assert set(TRANSFORM_NAMES) == {
        "punctuation_removal",
        "case_change",
        "slang_normalization",
        "paraphrase",
        "translation",
        "shortening",
        "noise",
    }
    assert len(report.robustness) == len(TRANSFORM_NAMES) * len(DEFAULT_SEVERITIES)
    by_transform = {
        name: [point for point in report.robustness if point.transform == name]
        for name in TRANSFORM_NAMES
    }
    baseline = report.baseline.test_metrics
    for name, points in by_transform.items():
        severities = [point.severity for point in points]
        assert severities == list(DEFAULT_SEVERITIES)
        # severity 0 is the identity transform: exact baseline reproduction
        assert points[0].metrics == baseline, name
        full = points[-1].metrics
        # every metric block carries the full family, not just accuracy
        assert 0.0 <= full.precision <= 1.0
        assert 0.0 <= full.recall <= 1.0
        assert 0.0 <= full.pr_auc <= 1.0

    # invariance: case and (all-)punctuation edits are largely neutralized
    assert by_transform["case_change"][-1].metrics.f1 >= 0.60
    assert by_transform["punctuation_removal"][-1].metrics.f1 >= 0.60
    # camouflage that destroys idiolect markers costs real performance
    assert by_transform["slang_normalization"][-1].metrics.f1 <= baseline.f1 - 0.15
    assert by_transform["paraphrase"][-1].metrics.f1 <= baseline.f1 - 0.10
    assert by_transform["translation"][-1].metrics.f1 <= baseline.f1 - 0.10
    assert by_transform["shortening"][-1].metrics.f1 <= baseline.f1 - 0.15
    assert by_transform["noise"][-1].metrics.f1 <= baseline.f1 - 0.05
    # degradation is graded, not a cliff: half-severity is milder than full
    for name in ("shortening", "noise", "slang_normalization"):
        points = by_transform[name]
        assert points[len(points) // 2].metrics.f1 >= points[-1].metrics.f1


# ---------------------------------------------------------------------------
# required output 4 — error analysis
# ---------------------------------------------------------------------------


def test_error_analysis_taxonomy(report: EvaluationReport) -> None:
    analysis = report.error_analysis
    test = report.baseline.test_metrics
    assert analysis.false_positives == test.false_positives == 45
    assert analysis.false_negatives == test.false_negatives == 24
    assert analysis.hard_negatives + analysis.soft_negatives == analysis.false_positives
    assert analysis.short_evidence_fn + analysis.other_fn == analysis.false_negatives
    # every false positive shares the target's style class: the corpus's
    # information-theoretic hard-negative ceiling, reported not hidden
    assert analysis.soft_negatives == 0
    assert len(analysis.false_positive_examples) == 5
    assert len(analysis.false_negative_examples) == 5
    assert all("~" in example for example in analysis.false_positive_examples)


def test_report_is_deterministic(corpus: SyntheticCorpus, report: EvaluationReport) -> None:
    # re-run everything except the (expensive) robustness grid
    rerun = StylometryEvaluator(corpus, severities=()).report
    assert rerun.baseline == report.baseline
    assert rerun.cross_domain == report.cross_domain
    assert rerun.error_analysis == report.error_analysis
    assert rerun.candidate_pair_count == report.candidate_pair_count


def test_alias_contexts_are_evaluation_only_metadata(corpus: SyntheticCorpus) -> None:
    contexts = build_alias_contexts(corpus)
    assert len(contexts) == len(corpus.aliases)
    assert all(context.platform for context in contexts.values())
    assert all(0 <= context.style_class <= 3 for context in contexts.values())
    assert sum(context.post_count for context in contexts.values()) == len(corpus.posts)


def test_run_full_evaluation_on_small_corpus() -> None:
    from aegis.collection.corpus import SyntheticCorpusBuilder

    small = SyntheticCorpusBuilder(seed=26151, actor_count=30, post_count=300).build()
    result = run_full_evaluation(small)
    assert isinstance(result, EvaluationReport)
    assert result.baseline.test_metrics.f1 > 0.0
    assert result.cross_domain.test_metrics.pr_auc > 0.0
    assert len(result.robustness) == len(TRANSFORM_NAMES) * len(DEFAULT_SEVERITIES)


# ---------------------------------------------------------------------------
# step 6 — adversarial transformations (unit level)
# ---------------------------------------------------------------------------


def test_severity_zero_is_identity_for_every_transform() -> None:
    text = "Vendor update: fees stay fixed, escrow rotation asap. NB. check #42!"
    for name in TRANSFORM_NAMES:
        assert apply_transform(text, name, severity=0.0) == text, name
    for name in TRANSFORM_NAMES:
        transformed = apply_transform(text, name, severity=1.0, seed=26151)
        assert transformed == apply_transform(text, name, severity=1.0, seed=26151), name


def test_apply_transform_validation() -> None:
    with pytest.raises(ValueError):
        apply_transform("text", "not_a_transform")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        apply_transform("text", "noise", severity=1.5)


def test_punctuation_removal() -> None:
    assert remove_punctuation("wait -- what?! done.") == "wait what done"
    assert remove_punctuation("", severity=1.0) == ""
    stripped = remove_punctuation("symbol-heavy :-) ==> markers", severity=1.0)
    assert not any(char in stripped for char in "!?-=:,;.")


def test_case_change_modes() -> None:
    assert change_case("AbC xYz", mode="swap") == "aBc XyZ"
    assert change_case("AbC xYz", mode="upper") == "ABC XYZ"
    assert change_case("AbC xYz", mode="lower") == "abc xyz"


def test_slang_normalization_replaces_markers() -> None:
    result = normalize_slang("asap we fix it tbh", severity=1.0)
    assert "asap" not in result
    assert "tbh" not in result
    assert "promptly" in result


def test_paraphrase_substitutes_content_words() -> None:
    result = paraphrase("the fees stay fixed", severity=1.0, seed=3)
    assert "fees" not in result
    assert "fixed" not in result
    assert result == paraphrase("the fees stay fixed", severity=1.0, seed=3)


def test_translation_stand_in() -> None:
    result = translate("the escrow fees stay", language="de", severity=1.0, seed=1)
    assert "the" not in result.split()
    assert "escrow" not in result
    assert "Gebühren" in result
    with pytest.raises(ValueError):
        translate("text", language="xx")  # type: ignore[arg-type]


def test_shortening_keeps_leading_fraction() -> None:
    assert shorten("one two three four five six seven eight") == "one two"
    assert shorten("only one") == "only"  # always keeps at least one word
    assert shorten("keep me", severity=0.0) == "keep me"


def test_noise_is_seeded_and_changes_text() -> None:
    text = "escrow rotation remains stable for the vendor mirror session " * 5
    corrupted = add_noise(text, severity=1.0, seed=11)
    assert corrupted != text
    assert corrupted == add_noise(text, severity=1.0, seed=11)
    assert add_noise(text, severity=0.0, seed=11) == text
