"""Frozen evaluation harness for the Phase 09 entity-resolution baselines.

The plan's exit rule: *do not start GNN training until these baselines
are frozen*.  This module produces the frozen reference numbers by
running all five baselines on the deterministic Phase 05 synthetic
corpus with a leak-free protocol:

* **Group split by actor** — an actor's aliases are never split across
  train and test, so the learned baselines cannot memorize an actor's
  alias style on one side and be scored on the other.
* **Train-only fitting** — TF-IDF document frequencies and feature
  standardization are computed from training documents only; the
  threshold for precision/recall/F1 is chosen on train predictions and
  applied unchanged to test.
* **Full test candidate space** — test pairs enumerate *all* alias
  pairs inside the test split, so PR-AUC, MRR and Recall@K are measured
  against the complete candidate population, not a sampled slice.
* **Deterministic negatives in train** — training negatives are sampled
  4-per-positive with a seeded RNG so fitting stays fast and repeatable.

Fixture signal notes (honest reporting): the synthetic fixture's handles
embed the actor id, so handle-driven features (1, 2) dominate the
frozen numbers; text features pick up the per-actor style markers;
marketplace overlap is *anti*-correlated because an actor's aliases are
placed on distinct platforms by construction.  This is a property of the
fixture, not of the models — the ``exclude_handle_features`` switch
measures how much the learned baselines rely on handles.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime

from aegis.collection.corpus import SyntheticCorpus, build_default_corpus
from aegis.graph import InMemoryGraphStore, NodeLabel
from aegis.ontology import EntityType, RelationshipType
from aegis.resolution.baselines import (
    RANDOM_SEED,
    CandidatePair,
    ResolutionBaseline,
    all_baselines,
)
from aegis.resolution.features import (
    FEATURE_NAMES,
    AliasActivity,
    PairFeatureExtractor,
    TfidfModel,
    stable_hash_int,
    validate_feature_registry,
)
from aegis.resolution.metrics import (
    DEFAULT_RECALL_K,
    BaselineMetrics,
    best_f1_threshold,
    classification_metrics,
    ranking_metrics,
)

#: Share of actors routed to the training side of the group split.
DEFAULT_TRAIN_FRACTION = 0.65
#: Negatives sampled per positive pair when building the training set.
DEFAULT_TRAIN_NEGATIVES_PER_POSITIVE = 4


@dataclass(frozen=True)
class BaselineReport:
    """Frozen metrics for one baseline on the held-out test split."""

    name: str
    threshold: float
    metrics: BaselineMetrics

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "threshold": self.threshold, **asdict(self.metrics)}


@dataclass(frozen=True)
class ResolutionReport:
    """The complete frozen-baseline reference (plan exit artifact)."""

    baselines: tuple[BaselineReport, ...]
    train_pairs: int
    train_positives: int
    test_pairs: int
    test_positives: int
    query_count: int
    corpus_seed: int
    split_seed: int
    train_fraction: float
    negatives_per_positive: int
    k: int
    use_graph: bool
    exclude_handle_features: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "baselines": [baseline.as_dict() for baseline in self.baselines],
            "train_pairs": self.train_pairs,
            "train_positives": self.train_positives,
            "test_pairs": self.test_pairs,
            "test_positives": self.test_positives,
            "query_count": self.query_count,
            "corpus_seed": self.corpus_seed,
            "split_seed": self.split_seed,
            "train_fraction": self.train_fraction,
            "negatives_per_positive": self.negatives_per_positive,
            "k": self.k,
            "use_graph": self.use_graph,
            "exclude_handle_features": self.exclude_handle_features,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=True)

    def by_name(self, name: str) -> BaselineReport:
        for baseline in self.baselines:
            if baseline.name == name:
                return baseline
        raise KeyError(f"baseline {name!r} not in report: {[b.name for b in self.baselines]}")


def build_activities(corpus: SyntheticCorpus) -> dict[str, AliasActivity]:
    """Aggregate each alias's observable activity (documents, hours, window)."""
    activities: dict[str, AliasActivity] = {}
    documents_by_alias: dict[str, list[tuple[str, datetime]]] = {}
    for post in corpus.posts:
        documents_by_alias.setdefault(post.alias_id, []).append(
            (f"{post.title}\n{post.body}", post.posted_at)
        )

    for alias in corpus.aliases:
        authored = sorted(documents_by_alias.get(alias.alias_id, []), key=lambda item: item[1])
        activities[alias.alias_id] = AliasActivity(
            alias_id=alias.alias_id,
            handle=alias.handle,
            platforms=frozenset({alias.platform}),
            first_seen=alias.first_seen,
            last_seen=alias.last_seen,
            documents=tuple(text for text, _ in authored),
            timestamps=tuple(timestamp for _, timestamp in authored),
        )
    return activities


def build_interaction_graph(corpus: SyntheticCorpus) -> InMemoryGraphStore:
    """Alias-level interaction graph from reply/mention relationships.

    Feeds feature 8 (graph neighborhood similarity).  Nodes are alias
    handles; edges aggregate the corpus's ``replies_to`` and ``mentions``
    relationships up to alias level with the interaction time window.
    """
    store = InMemoryGraphStore()
    for alias in corpus.aliases:
        store.add_node(
            alias.alias_id,
            NodeLabel.HANDLE,
            entity_type=EntityType.HANDLE,
            properties={"handle": alias.handle, "platform": alias.platform},
        )

    posts = {post.post_id: post for post in corpus.posts}
    interactions: dict[tuple[str, str], list[datetime]] = {}
    for relationship in corpus.relationships:
        if relationship.relationship_type == "same_actor":
            continue  # ground truth never enters model inputs
        source_post = posts.get(relationship.source_id)
        target_post = posts.get(relationship.target_id)
        if source_post is None or target_post is None:
            continue  # not an alias-level relationship
        source_alias = source_post.alias_id
        target_alias = target_post.alias_id
        if source_alias == target_alias:
            continue
        key = (min(source_alias, target_alias), max(source_alias, target_alias))
        interactions.setdefault(key, []).extend([source_post.posted_at, target_post.posted_at])

    for (left, right), timestamps in sorted(interactions.items()):
        store.add_edge(
            RelationshipType.ASSOCIATED_WITH,
            left,
            right,
            first_seen=min(timestamps),
            last_seen=max(timestamps),
            confidence=1.0,
        )
    return store


def split_actors(
    corpus: SyntheticCorpus,
    *,
    seed: int = RANDOM_SEED,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
) -> tuple[frozenset[str], frozenset[str]]:
    """Deterministic group split of actor ids into (train, test).

    Ranking by a seeded SHA-256 makes the split stable under actor
    insertion order and reproducible across runs and machines.
    """
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be within (0, 1)")
    actor_ids = sorted({alias.actor_id for alias in corpus.aliases})
    ranked = sorted(actor_ids, key=lambda actor_id: stable_hash_int(actor_id, seed=seed))
    train_size = int(round(len(ranked) * train_fraction))
    train_size = min(max(train_size, 1), len(ranked) - 1)
    return frozenset(ranked[:train_size]), frozenset(ranked[train_size:])


def _positive_pairs(corpus: SyntheticCorpus, alias_ids: set[str]) -> list[tuple[str, str]]:
    """Ground-truth same-actor pairs fully contained in ``alias_ids``."""
    pairs: list[tuple[str, str]] = []
    for left, right in corpus.same_actor_pairs:
        if left in alias_ids and right in alias_ids:
            pairs.append((min(left, right), max(left, right)))
    return sorted(pairs)


def _all_pairs(alias_ids: set[str]) -> list[tuple[str, str]]:
    ordered = sorted(alias_ids)
    return [(left, right) for index, left in enumerate(ordered) for right in ordered[index + 1 :]]


def _sample_negatives(
    alias_ids: set[str],
    positives: set[tuple[str, str]],
    *,
    count: int,
    seed: int,
) -> list[tuple[str, str]]:
    """Deterministic sample of non-positive pairs from the candidate space."""
    candidates = [pair for pair in _all_pairs(alias_ids) if pair not in positives]
    rng = random.Random(seed)
    if count >= len(candidates):
        return sorted(candidates)
    return sorted(rng.sample(candidates, count))


def evaluate_baselines(
    corpus: SyntheticCorpus | None = None,
    *,
    baselines: Sequence[ResolutionBaseline] | None = None,
    seed: int = RANDOM_SEED,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    negatives_per_positive: int = DEFAULT_TRAIN_NEGATIVES_PER_POSITIVE,
    k: int = DEFAULT_RECALL_K,
    use_graph: bool = True,
    exclude_handle_features: bool = False,
) -> ResolutionReport:
    """Run every baseline under the frozen protocol and return the report.

    Parameters mirror the protocol decisions documented in the module
    docstring; every default is what CI and ``make train-baselines`` use.
    """
    validate_feature_registry()
    if negatives_per_positive < 0:
        raise ValueError("negatives_per_positive must be >= 0")
    corpus = corpus if corpus is not None else build_default_corpus()
    models = list(baselines) if baselines is not None else all_baselines()

    activities = build_activities(corpus)
    train_actors, test_actors = split_actors(corpus, seed=seed, train_fraction=train_fraction)
    train_aliases = {a.alias_id for a in corpus.aliases if a.actor_id in train_actors}
    test_aliases = {a.alias_id for a in corpus.aliases if a.actor_id in test_actors}

    train_positives = _positive_pairs(corpus, train_aliases)
    test_pairs = _all_pairs(test_aliases)
    train_positives_set = set(train_positives)
    train_negatives = _sample_negatives(
        train_aliases,
        train_positives_set,
        count=len(train_positives) * negatives_per_positive,
        seed=seed,
    )
    train_pair_keys = [(left, right, 1) for left, right in train_positives] + [
        (left, right, 0) for left, right in train_negatives
    ]

    # TF-IDF fitted on training documents only (no test leakage)
    train_documents = [
        "\n".join(activities[alias_id].documents) for alias_id in sorted(train_aliases)
    ]
    tfidf = TfidfModel.fit(train_documents)

    graph = build_interaction_graph(corpus) if use_graph else None
    extractor = PairFeatureExtractor(tfidf=tfidf, graph=graph)

    def make_pair(left: str, right: str, label: int) -> CandidatePair:
        features = extractor.extract(activities[left], activities[right])
        if exclude_handle_features:
            features = replace(features, handle_similarity=0.0, char_ngram_similarity=0.0)
        return CandidatePair(
            left_alias_id=left,
            right_alias_id=right,
            left_handle=activities[left].handle,
            right_handle=activities[right].handle,
            features=features,
            label=label,
        )

    train_pairs = [make_pair(left, right, label) for left, right, label in train_pair_keys]
    test_labels = {
        (left, right): int((min(left, right), max(left, right)) in corpus.same_actor_pairs)
        for left, right in test_pairs
    }
    scored_test = [make_pair(left, right, test_labels[(left, right)]) for left, right in test_pairs]

    # per-query rankings over the full test candidate space
    partners: dict[str, list[CandidatePair]] = {}
    for pair in scored_test:
        partners.setdefault(pair.left_alias_id, []).append(pair)
        partners.setdefault(pair.right_alias_id, []).append(pair)
    rankings_by_model: dict[str, list[list[int]]] = {model.name: [] for model in models}

    reports: list[BaselineReport] = []
    for model in models:
        model.fit(train_pairs)
        train_scores = [model.score(pair) for pair in train_pairs]
        train_labels = [pair.label for pair in train_pairs]
        threshold = best_f1_threshold(train_scores, train_labels)

        query_rankings: list[list[int]] = []
        for alias_id in sorted(partners):
            ranked = sorted(
                partners[alias_id],
                key=lambda pair: (
                    -model.score(pair),
                    pair.left_alias_id,
                    pair.right_alias_id,
                ),
            )
            # each partner appears twice for this query (once as left, once as
            # right of the same pair) only when both directions are appended —
            # de-duplicate by the partner's alias id first.
            seen: set[str] = set()
            labels: list[int] = []
            for pair in ranked:
                partner = (
                    pair.right_alias_id if pair.left_alias_id == alias_id else pair.left_alias_id
                )
                if partner in seen:
                    continue
                seen.add(partner)
                labels.append(pair.label)
            query_rankings.append(labels)
        rankings_by_model[model.name] = query_rankings

        test_scores = [model.score(pair) for pair in scored_test]
        test_label_list = [pair.label for pair in scored_test]
        classification = classification_metrics(test_scores, test_label_list, threshold)
        ranking = ranking_metrics(query_rankings, k=k)
        reports.append(
            BaselineReport(
                name=model.name,
                threshold=threshold,
                metrics=BaselineMetrics(
                    precision=classification.precision,
                    recall=classification.recall,
                    f1=classification.f1,
                    pr_auc=classification.pr_auc,
                    mrr=ranking.mrr,
                    recall_at_k=ranking.recall_at_k,
                    k=k,
                ),
            )
        )

    return ResolutionReport(
        baselines=tuple(reports),
        train_pairs=len(train_pairs),
        train_positives=len(train_positives),
        test_pairs=len(scored_test),
        test_positives=sum(test_labels.values()),
        query_count=len(partners),
        corpus_seed=corpus.seed,
        split_seed=seed,
        train_fraction=train_fraction,
        negatives_per_positive=negatives_per_positive,
        k=k,
        use_graph=use_graph,
        exclude_handle_features=exclude_handle_features,
    )


def format_report(report: ResolutionReport) -> str:
    """Human-readable table of the frozen baseline metrics."""
    header = (
        f"{'baseline':<22} {'prec':>6} {'rec':>6} {'f1':>6} "
        f"{'pr-auc':>7} {'mrr':>6} {'r@' + str(report.k):>6}"
    )
    lines = [
        f"Entity-resolution baselines (Phase 09) — corpus seed {report.corpus_seed}",
        f"train {report.train_pairs} pairs ({report.train_positives} positive) / "
        f"test {report.test_pairs} pairs ({report.test_positives} positive, "
        f"{report.query_count} queries)",
        header,
        "-" * len(header),
    ]
    for baseline in report.baselines:
        metrics = baseline.metrics
        lines.append(
            f"{baseline.name:<22} {metrics.precision:>6.3f} {metrics.recall:>6.3f} "
            f"{metrics.f1:>6.3f} {metrics.pr_auc:>7.3f} {metrics.mrr:>6.3f} "
            f"{metrics.recall_at_k:>6.3f}"
        )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_TRAIN_FRACTION",
    "DEFAULT_TRAIN_NEGATIVES_PER_POSITIVE",
    "FEATURE_NAMES",
    "BaselineReport",
    "ResolutionReport",
    "build_activities",
    "build_interaction_graph",
    "evaluate_baselines",
    "format_report",
    "split_actors",
]
