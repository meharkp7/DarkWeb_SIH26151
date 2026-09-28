"""Entity-resolution baselines (Phase 09).

The plan freezes five baselines — exact handle, edit distance, TF-IDF
cosine, logistic regression, XGBoost — over nine fixed candidate-pair
features, measured with the plan's six metrics (precision, recall, F1,
PR-AUC, MRR, Recall@K).  :func:`evaluate.evaluate_baselines` produces
the frozen reference report; GNN training (Phase 19) must not start
until those numbers exist.
"""

from aegis.resolution.baselines import (
    RANDOM_SEED,
    CandidatePair,
    EditDistanceBaseline,
    ExactHandleBaseline,
    LogisticRegressionBaseline,
    ResolutionBaseline,
    TfIdfCosineBaseline,
    XgboostBaseline,
    all_baselines,
)
from aegis.resolution.evaluate import (
    BaselineReport,
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
    validate_feature_registry,
)
from aegis.resolution.metrics import (
    DEFAULT_RECALL_K,
    BaselineMetrics,
    ClassificationMetrics,
    RankingMetrics,
    average_precision,
    best_f1_threshold,
    classification_metrics,
    precision_recall_f1,
    precision_recall_f1_at_threshold,
    ranking_metrics,
    recall_at_k,
    reciprocal_rank,
)

__all__ = [
    "DEFAULT_RECALL_K",
    "FEATURE_NAMES",
    "RANDOM_SEED",
    "AliasActivity",
    "BaselineMetrics",
    "BaselineReport",
    "CandidatePair",
    "CandidatePairFeatures",
    "ClassificationMetrics",
    "EditDistanceBaseline",
    "ExactHandleBaseline",
    "LogisticRegressionBaseline",
    "PairFeatureExtractor",
    "RankingMetrics",
    "ResolutionBaseline",
    "ResolutionReport",
    "TfIdfCosineBaseline",
    "TfidfModel",
    "XgboostBaseline",
    "all_baselines",
    "average_precision",
    "best_f1_threshold",
    "build_activities",
    "build_interaction_graph",
    "char_ngram_counts",
    "classification_metrics",
    "cosine_counts",
    "evaluate_baselines",
    "format_report",
    "handle_similarity",
    "hour_histogram",
    "levenshtein",
    "normalize_handle",
    "precision_recall_f1",
    "precision_recall_f1_at_threshold",
    "ranking_metrics",
    "recall_at_k",
    "reciprocal_rank",
    "split_actors",
    "validate_feature_registry",
]
