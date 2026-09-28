"""Cross-marketplace evaluation, robustness, and error analysis (Phase 11, steps 5-6).

Produces the four required outputs of the stylometry phase:

=====================  ====================================================
output                 where
=====================  ====================================================
baseline metrics       :class:`BaselineResult` (train + held-out test)
cross-domain metrics   :class:`CrossDomainResult` (train on one
                       marketplace, test on another)
robustness curve       :class:`RobustnessPoint` tuples, one series per
                       adversarial transform across severities
error analysis         :class:`ErrorAnalysis` (FP/FN taxonomy)
=====================  ====================================================

Metric policy: every reported block carries precision, recall, F1, and
PR-AUC (plus accuracy/FPR as secondary numbers) — never accuracy
alone, per the plan.

Metric computation mirrors ``aegis.evaluation.metrics.SyntheticEvaluator``
(confusion counts -> precision/recall/F1) but extends it with PR-AUC
and accuracy over *scored* pairs; that module is frozen for this phase,
so the minimal logic lives here instead of being edited there.
Average precision and best-F1 threshold selection are *not* duplicated
here — they delegate to the canonical implementations in
:mod:`aegis.resolution.metrics`, which use the canonical
``(scores, labels)`` argument order and break threshold ties towards
the highest cutoff.

Ground truth (``same_actor_pairs``, actor style classes) is used only
for labelling and scoring — never as a model input.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property

from aegis.collection.corpus import SyntheticCorpus
from aegis.resolution.metrics import (
    average_precision as _canonical_average_precision,
)
from aegis.resolution.metrics import (
    best_f1_threshold as _canonical_best_f1_threshold,
)
from aegis.stylometry.embeddings import EmbeddingProvider
from aegis.stylometry.ngrams import NGramConfig
from aegis.stylometry.transforms import TRANSFORM_NAMES, TransformName, apply_transform
from aegis.stylometry.verification import (
    DEFAULT_SEED,
    PairFeatureExtractor,
    PairFeatures,
    VerificationModel,
)

DEFAULT_NEGATIVES_PER_POSITIVE = 3
DEFAULT_TEST_RATIO = 0.3
DEFAULT_SEVERITIES: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)

#: Cap on the per-evaluator transform memo (``StylometryEvaluator._transform_cache``).
#: That plain dict grows on every transformed scoring pass; past this many distinct
#: ``(alias, transform, severity, text)`` keys the oldest-inserted entry is evicted.
MAX_TRANSFORM_CACHE_ENTRIES = 1024


def _store_transform(
    cache: dict[tuple[str, str, float, str], str],
    key: tuple[str, str, float, str],
    value: str,
) -> None:
    """Insert a transformed text, evicting the oldest entry at the cap.

    Deterministic FIFO eviction (dicts preserve insertion order).
    Eviction only costs a recompute: the cached value is a pure
    function of the key, so results never depend on what is resident.
    """
    if len(cache) >= MAX_TRANSFORM_CACHE_ENTRIES:
        cache.pop(next(iter(cache)))
    cache[key] = value


def _safe_divide(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def best_f1_threshold(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Operating point maximising F1 on *scores*/*labels*.

    Delegates to the canonical
    :func:`aegis.resolution.metrics.best_f1_threshold` — the single
    implementation shared with entity resolution — so the argument
    order is ``(scores, labels)`` and ties resolve to the *highest*
    threshold (not the cutoff closest to 0.5).

    The logistic model is trained on a 1:N candidate set, so its raw
    probabilities are calibrated to that prior and a fixed 0.5 cutoff
    would trade away recall.  Callers must pass *training* scores —
    tuning on the held-out split would leak.
    """
    return _canonical_best_f1_threshold(scores, labels)


def average_precision(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Area under the precision-recall curve (average precision).

    Delegates to the canonical
    :func:`aegis.resolution.metrics.average_precision` — the single
    implementation shared with entity resolution — so the argument
    order is ``(scores, labels)``.  Scores are ranked high-to-low with
    a stable index tie-break; at every positive label the current
    precision is accumulated and divided by the number of positives.
    Returns 0.0 when there are no positives.
    """
    return _canonical_average_precision(scores, labels)


@dataclass(frozen=True)
class ClassificationMetrics:
    """Precision / recall / F1 / PR-AUC (+ accuracy, FPR) for one split."""

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1: float
    pr_auc: float
    accuracy: float
    false_positive_rate: float

    @classmethod
    def from_scores(
        cls,
        labels: Sequence[int],
        scores: Sequence[float],
        *,
        threshold: float = 0.5,
    ) -> ClassificationMetrics:
        """Threshold *scores* at *threshold* and score against *labels*.

        All reported fields are rounded to 3 decimals: rounding here is
        a *presentation* concern.  Threshold *selection* does not use
        these rounded values — it runs the canonical unrounded sweep in
        :func:`best_f1_threshold`.
        """
        if len(labels) != len(scores) or not labels:
            raise ValueError("labels and scores must be non-empty and equal length")
        predictions = [1 if score >= threshold else 0 for score in scores]
        tp = sum(1 for label, pred in zip(labels, predictions, strict=True) if label and pred)
        fp = sum(1 for label, pred in zip(labels, predictions, strict=True) if not label and pred)
        fn = sum(1 for label, pred in zip(labels, predictions, strict=True) if label and not pred)
        tn = sum(
            1 for label, pred in zip(labels, predictions, strict=True) if not label and not pred
        )
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        return cls(
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            true_negatives=tn,
            precision=round(precision, 3),
            recall=round(recall, 3),
            f1=round(_safe_divide(2 * precision * recall, precision + recall), 3),
            pr_auc=round(average_precision(scores, labels), 3),
            accuracy=round(_safe_divide(tp + tn, len(labels)), 3),
            false_positive_rate=round(_safe_divide(fp, fp + tn), 3),
        )


@dataclass(frozen=True, order=True)
class LabeledPair:
    """One candidate verification pair with its ground-truth label."""

    left_alias: str
    right_alias: str
    label: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.left_alias, self.right_alias)


@dataclass(frozen=True)
class AliasContext:
    """Evaluation-only facts about an alias (never a model input)."""

    alias_id: str
    actor_id: str
    platform: str
    style_class: int
    post_count: int


def build_alias_documents(corpus: SyntheticCorpus) -> dict[str, str]:
    """Concatenate each alias's posts (title + body) in chronological order."""
    documents: dict[str, list[str]] = {alias.alias_id: [] for alias in corpus.aliases}
    for post in sorted(corpus.posts, key=lambda item: (item.posted_at, item.post_id)):
        documents[post.alias_id].append(f"{post.title} {post.body}")
    return {alias_id: "\n".join(parts) for alias_id, parts in documents.items()}


def build_alias_contexts(corpus: SyntheticCorpus) -> dict[str, AliasContext]:
    """Per-alias evaluation context (platform, style class, post count)."""
    posts_per_alias: dict[str, int] = {}
    for post in corpus.posts:
        posts_per_alias[post.alias_id] = posts_per_alias.get(post.alias_id, 0) + 1
    actors = {actor.actor_id: actor for actor in corpus.actors}
    contexts: dict[str, AliasContext] = {}
    for alias in corpus.aliases:
        actor = actors[alias.actor_id]
        contexts[alias.alias_id] = AliasContext(
            alias_id=alias.alias_id,
            actor_id=alias.actor_id,
            platform=alias.platform,
            style_class=actor.style_marker,
            post_count=posts_per_alias.get(alias.alias_id, 0),
        )
    return contexts


def candidate_pairs(
    corpus: SyntheticCorpus,
    documents: Mapping[str, str],
    *,
    negatives_per_positive: int = DEFAULT_NEGATIVES_PER_POSITIVE,
    seed: int = DEFAULT_SEED,
) -> tuple[LabeledPair, ...]:
    """Deterministic candidate-link set: every verifiable positive plus a
    seeded sample of negatives at ``negatives_per_positive`` : 1.

    Aliases with no collected text are excluded (a verifier must abstain
    where there is no evidence), as are same-actor pairs touching them.
    """
    alias_ids = sorted(alias_id for alias_id in documents if documents[alias_id].strip())
    verifiable = set(alias_ids)

    positives = sorted(
        (left, right)
        for left, right in corpus.same_actor_pairs
        if left in verifiable and right in verifiable
    )
    positive_keys = set(positives)

    negative_pool = [
        (left, right)
        for index, left in enumerate(alias_ids)
        for right in alias_ids[index + 1 :]
        if (left, right) not in positive_keys
    ]
    wanted = negatives_per_positive * len(positives)
    rng = random.Random(seed)
    sampled = sorted(rng.sample(negative_pool, min(wanted, len(negative_pool))))

    pairs = [LabeledPair(left, right, 1) for left, right in positives]
    pairs.extend(LabeledPair(left, right, 0) for left, right in sampled)
    return tuple(pairs)


def stratified_split(
    pairs: Sequence[LabeledPair],
    *,
    test_ratio: float = DEFAULT_TEST_RATIO,
    seed: int = DEFAULT_SEED,
) -> tuple[tuple[LabeledPair, ...], tuple[LabeledPair, ...]]:
    """Seeded 70/30-style split, stratified so both splits keep both classes."""
    if not 0.0 < test_ratio < 1.0:
        raise ValueError(f"test_ratio must be within (0, 1), got {test_ratio}")
    rng = random.Random(seed)
    train: list[LabeledPair] = []
    test: list[LabeledPair] = []
    for label in (1, 0):
        group = [pair for pair in pairs if pair.label == label]
        rng.shuffle(group)
        cut = max(1, round(len(group) * test_ratio)) if len(group) > 1 else len(group)
        test.extend(sorted(group[:cut]))
        train.extend(sorted(group[cut:]))
    return tuple(sorted(train)), tuple(sorted(test))


@dataclass(frozen=True)
class BaselineResult:
    """Required output 1 — baseline metrics on the random candidate split."""

    train_metrics: ClassificationMetrics
    test_metrics: ClassificationMetrics
    train_pair_count: int
    test_pair_count: int
    threshold: float


@dataclass(frozen=True)
class CrossDomainResult:
    """Required output 2 — train on one marketplace, test on another."""

    train_platform: str
    test_platform: str
    train_metrics: ClassificationMetrics
    test_metrics: ClassificationMetrics
    train_pair_count: int
    test_pair_count: int


@dataclass(frozen=True)
class RobustnessPoint:
    """Required output 3 — one point of the robustness curve."""

    transform: str
    severity: float
    metrics: ClassificationMetrics


@dataclass(frozen=True)
class ErrorAnalysis:
    """Required output 4 — what the model got wrong, and why.

    ``hard_negatives`` are false-positive pairs whose two *actors* share
    the same corpus style class: their texts are drawn from the same
    marker vocabulary, so no stylometric verifier can separate them —
    this is the corpus's information-theoretic limit, reported openly
    rather than hidden in an aggregate score. ``soft_negatives`` are
    false positives with *conflicting* style classes: the model should
    have caught those. False negatives are split by short evidence
    (either side with at most one post).
    """

    false_positives: int
    false_negatives: int
    hard_negatives: int
    soft_negatives: int
    short_evidence_fn: int
    other_fn: int
    false_positive_examples: tuple[str, ...]
    false_negative_examples: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationReport:
    """Everything the phase-11 plan requires from one evaluation run."""

    baseline: BaselineResult
    cross_domain: CrossDomainResult
    robustness: tuple[RobustnessPoint, ...]
    error_analysis: ErrorAnalysis
    candidate_pair_count: int


class StylometryEvaluator:
    """Runs the four required Phase-11 outputs against a corpus.

    Usage::

        evaluator = StylometryEvaluator(build_default_corpus(seed=26151))
        report = evaluator.report

    The extractor is fit only on training-split documents and the
    verifier is trained in-process (logistic regression, fixed seed), so
    every number in the report is reproducible bit-for-bit for a fixed
    corpus seed.
    """

    def __init__(
        self,
        corpus: SyntheticCorpus,
        *,
        seed: int = DEFAULT_SEED,
        negatives_per_positive: int = DEFAULT_NEGATIVES_PER_POSITIVE,
        test_ratio: float = DEFAULT_TEST_RATIO,
        embedding_provider: EmbeddingProvider | None = None,
        config: NGramConfig | None = None,
        severities: Sequence[float] = DEFAULT_SEVERITIES,
        train_platform: str = "forum_alpha",
        test_platform: str = "market_beta",
        max_examples: int = 5,
    ) -> None:
        if train_platform == test_platform:
            raise ValueError("train_platform and test_platform must differ")
        self.corpus = corpus
        self.seed = seed
        self.negatives_per_positive = negatives_per_positive
        self.test_ratio = test_ratio
        self.embedding_provider = embedding_provider
        self.config = config
        self.severities = tuple(severities)
        self.train_platform = train_platform
        self.test_platform = test_platform
        self.max_examples = max_examples
        self.documents = build_alias_documents(corpus)
        self.contexts = build_alias_contexts(corpus)
        self._transform_cache: dict[tuple[str, str, float, str], str] = {}

    @cached_property
    def pairs(self) -> tuple[LabeledPair, ...]:
        """The deterministic candidate set (positives + sampled negatives)."""
        return candidate_pairs(
            self.corpus,
            self.documents,
            negatives_per_positive=self.negatives_per_positive,
            seed=self.seed,
        )

    @cached_property
    def split(self) -> tuple[tuple[LabeledPair, ...], tuple[LabeledPair, ...]]:
        """Stratified (train, test) split of :attr:`pairs`."""
        return stratified_split(self.pairs, test_ratio=self.test_ratio, seed=self.seed)

    @property
    def train_pairs(self) -> tuple[LabeledPair, ...]:
        return self.split[0]

    @property
    def test_pairs(self) -> tuple[LabeledPair, ...]:
        return self.split[1]

    def _new_extractor(self, texts: Sequence[str]) -> PairFeatureExtractor:
        extractor = PairFeatureExtractor(
            embedding_provider=self.embedding_provider, config=self.config
        )
        return extractor.fit(texts)

    @cached_property
    def baseline_model(self) -> tuple[PairFeatureExtractor, VerificationModel]:
        """Extractor (fit on train docs) + model (trained on train pairs)."""
        train_documents = sorted(
            {
                document
                for pair in self.train_pairs
                for document in (self.documents[pair.left_alias], self.documents[pair.right_alias])
            }
        )
        extractor = self._new_extractor(train_documents)
        rows: list[PairFeatures] = [
            extractor.features(self.documents[pair.left_alias], self.documents[pair.right_alias])
            for pair in self.train_pairs
        ]
        model = VerificationModel.train(
            [row.values for row in rows], [pair.label for pair in self.train_pairs]
        )
        return extractor, model

    @staticmethod
    def _scores(
        extractor: PairFeatureExtractor,
        model: VerificationModel,
        pairs: Sequence[LabeledPair],
        documents: Mapping[str, str],
        *,
        transform: TransformName | None = None,
        severity: float = 1.0,
        seed: int = DEFAULT_SEED,
        transform_cache: dict[tuple[str, str, float, str], str] | None = None,
    ) -> tuple[list[int], list[float]]:
        labels: list[int] = []
        scores: list[float] = []
        for pair in pairs:
            right_text = documents[pair.right_alias]
            if transform is not None:
                cache_key = (pair.right_alias, transform, severity, right_text)
                cached = transform_cache.get(cache_key) if transform_cache is not None else None
                if cached is not None:
                    right_text = cached
                else:
                    right_text = apply_transform(
                        right_text, transform, severity=severity, seed=seed
                    )
                    if transform_cache is not None:
                        _store_transform(transform_cache, cache_key, right_text)
            features = extractor.features(documents[pair.left_alias], right_text)
            labels.append(pair.label)
            scores.append(model.predict_proba(features.values))
        return labels, scores

    @cached_property
    def baseline(self) -> BaselineResult:
        """Required output 1 — train and held-out-test metrics.

        The decision threshold is chosen on the *training* split via
        :func:`best_f1_threshold`; the test split is only ever scored,
        never tuned on.
        """
        extractor, model = self.baseline_model
        train_labels, train_scores = self._scores(
            extractor, model, self.train_pairs, self.documents
        )
        test_labels, test_scores = self._scores(extractor, model, self.test_pairs, self.documents)
        threshold = best_f1_threshold(train_scores, train_labels)
        return BaselineResult(
            train_metrics=ClassificationMetrics.from_scores(
                train_labels, train_scores, threshold=threshold
            ),
            test_metrics=ClassificationMetrics.from_scores(
                test_labels, test_scores, threshold=threshold
            ),
            train_pair_count=len(self.train_pairs),
            test_pair_count=len(self.test_pairs),
            threshold=round(threshold, 3),
        )

    @cached_property
    def cross_domain(self) -> CrossDomainResult:
        """Required output 2 — train on one marketplace, test on another.

        Train pairs involve ``train_platform`` and never
        ``test_platform``; test pairs involve ``test_platform`` and
        never ``train_platform`` — two disjoint marketplace domains
        drawn from the same candidate set.
        """
        train_pairs = tuple(
            pair
            for pair in self.pairs
            if self._involves(pair, self.train_platform)
            and not self._involves(pair, self.test_platform)
        )
        test_pairs = tuple(
            pair
            for pair in self.pairs
            if self._involves(pair, self.test_platform)
            and not self._involves(pair, self.train_platform)
        )
        if not train_pairs or not test_pairs:
            raise ValueError(
                f"platform split produced empty data: "
                f"train={len(train_pairs)} test={len(test_pairs)}"
            )
        train_documents = sorted(
            {
                document
                for pair in train_pairs
                for document in (self.documents[pair.left_alias], self.documents[pair.right_alias])
            }
        )
        extractor = self._new_extractor(train_documents)
        rows: list[PairFeatures] = [
            extractor.features(self.documents[pair.left_alias], self.documents[pair.right_alias])
            for pair in train_pairs
        ]
        model = VerificationModel.train(
            [row.values for row in rows], [pair.label for pair in train_pairs]
        )
        train_labels, train_scores = self._scores(extractor, model, train_pairs, self.documents)
        test_labels, test_scores = self._scores(extractor, model, test_pairs, self.documents)
        threshold = best_f1_threshold(train_scores, train_labels)
        return CrossDomainResult(
            train_platform=self.train_platform,
            test_platform=self.test_platform,
            train_metrics=ClassificationMetrics.from_scores(
                train_labels, train_scores, threshold=threshold
            ),
            test_metrics=ClassificationMetrics.from_scores(
                test_labels, test_scores, threshold=threshold
            ),
            train_pair_count=len(train_pairs),
            test_pair_count=len(test_pairs),
        )

    @cached_property
    def robustness(self) -> tuple[RobustnessPoint, ...]:
        """Required output 3 — metric degradation per transform/severity.

        Each transform is applied to the *right* document of every test
        pair (the classic "one side is camouflaged" threat model) while
        the model, threshold, and left documents stay fixed. Severity
        0.0 is the identity and therefore reproduces baseline metrics.
        """
        extractor, model = self.baseline_model
        threshold = self.baseline.threshold
        points: list[RobustnessPoint] = []
        for transform in TRANSFORM_NAMES:
            for severity in self.severities:
                labels, scores = self._scores(
                    extractor,
                    model,
                    self.test_pairs,
                    self.documents,
                    transform=transform,
                    severity=severity,
                    seed=self.seed,
                    transform_cache=self._transform_cache,
                )
                points.append(
                    RobustnessPoint(
                        transform=transform,
                        severity=severity,
                        metrics=ClassificationMetrics.from_scores(
                            labels, scores, threshold=threshold
                        ),
                    )
                )
        return tuple(points)

    @cached_property
    def error_analysis(self) -> ErrorAnalysis:
        """Required output 4 — FP/FN taxonomy on the held-out test split."""
        extractor, model = self.baseline_model
        threshold = self.baseline.threshold
        labels, scores = self._scores(extractor, model, self.test_pairs, self.documents)
        fp_hard = fp_soft = fn_short = fn_other = 0
        fp_examples: list[str] = []
        fn_examples: list[str] = []
        fp_count = fn_count = 0
        for pair, label, score in zip(self.test_pairs, labels, scores, strict=True):
            predicted = 1 if score >= threshold else 0
            if predicted == label:
                continue
            left = self.contexts[pair.left_alias]
            right = self.contexts[pair.right_alias]
            description = f"{pair.left_alias}~{pair.right_alias} ({left.platform}/{right.platform})"
            if predicted == 1:
                fp_count += 1
                if left.style_class == right.style_class:
                    fp_hard += 1
                else:
                    fp_soft += 1
                if len(fp_examples) < self.max_examples:
                    fp_examples.append(description)
            else:
                fn_count += 1
                if left.post_count <= 1 or right.post_count <= 1:
                    fn_short += 1
                else:
                    fn_other += 1
                if len(fn_examples) < self.max_examples:
                    fn_examples.append(description)
        return ErrorAnalysis(
            false_positives=fp_count,
            false_negatives=fn_count,
            hard_negatives=fp_hard,
            soft_negatives=fp_soft,
            short_evidence_fn=fn_short,
            other_fn=fn_other,
            false_positive_examples=tuple(fp_examples),
            false_negative_examples=tuple(fn_examples),
        )

    @cached_property
    def report(self) -> EvaluationReport:
        """All four required outputs bundled together."""
        return EvaluationReport(
            baseline=self.baseline,
            cross_domain=self.cross_domain,
            robustness=self.robustness,
            error_analysis=self.error_analysis,
            candidate_pair_count=len(self.pairs),
        )

    def _involves(self, pair: LabeledPair, platform: str) -> bool:
        return (
            self.contexts[pair.left_alias].platform == platform
            or self.contexts[pair.right_alias].platform == platform
        )


def run_full_evaluation(
    corpus: SyntheticCorpus,
    *,
    seed: int = DEFAULT_SEED,
    train_platform: str = "forum_alpha",
    test_platform: str = "market_beta",
) -> EvaluationReport:
    """Convenience wrapper producing the complete Phase-11 report."""
    return StylometryEvaluator(
        corpus,
        seed=seed,
        train_platform=train_platform,
        test_platform=test_platform,
    ).report
