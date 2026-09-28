"""Stylometry and authorship verification (Phase 11).

Step order from the plan:

1. character and word n-grams      -> :mod:`aegis.stylometry.ngrams`
2. classical stylometric features  -> :mod:`aegis.stylometry.features`
3. transformer embeddings          -> :mod:`aegis.stylometry.embeddings`
4. pairwise verification model     -> :mod:`aegis.stylometry.verification`
5. cross-marketplace evaluation    -> :mod:`aegis.stylometry.evaluation`
6. adversarial transformations     -> :mod:`aegis.stylometry.transforms`

Everything is deterministic (fixed seeds), pure Python, and scoped to
synthetic/defensive evaluation of alias-verification robustness.
"""

from aegis.stylometry.embeddings import (
    EmbeddingBackendUnavailable,
    EmbeddingProvider,
    HashingEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    embed_cosine,
    embed_many,
)
from aegis.stylometry.evaluation import (
    DEFAULT_SEVERITIES,
    AliasContext,
    BaselineResult,
    ClassificationMetrics,
    CrossDomainResult,
    ErrorAnalysis,
    EvaluationReport,
    LabeledPair,
    RobustnessPoint,
    StylometryEvaluator,
    average_precision,
    best_f1_threshold,
    build_alias_contexts,
    build_alias_documents,
    candidate_pairs,
    run_full_evaluation,
    stratified_split,
)
from aegis.stylometry.features import (
    FEATURE_NAMES,
    FUNCTION_WORDS,
    StylometricFeatures,
    stylometric_similarity,
)
from aegis.stylometry.ngrams import (
    NGramConfig,
    NGramVectorizer,
    character_ngrams,
    cosine_similarity,
    counter_cosine,
    hashed_ngram_vector,
    tokenize_words,
    word_ngrams,
)
from aegis.stylometry.transforms import (
    DEFAULT_PARAPHRASES,
    DEFAULT_SLANG,
    DEFAULT_TRANSLATIONS,
    TRANSFORM_NAMES,
    TransformName,
    add_noise,
    apply_transform,
    change_case,
    normalize_slang,
    paraphrase,
    remove_punctuation,
    shorten,
    translate,
)
from aegis.stylometry.verification import (
    DEFAULT_SEED,
    PairFeatureExtractor,
    PairFeatures,
    Standardizer,
    VerificationModel,
)
from aegis.stylometry.verification import (
    FEATURE_NAMES as PAIR_FEATURE_NAMES,
)

__all__ = [
    "DEFAULT_PARAPHRASES",
    "DEFAULT_SEED",
    "DEFAULT_SLANG",
    "DEFAULT_TRANSLATIONS",
    "FEATURE_NAMES",
    "FUNCTION_WORDS",
    "TRANSFORM_NAMES",
    "AliasContext",
    "BaselineResult",
    "ClassificationMetrics",
    "CrossDomainResult",
    "DEFAULT_SEVERITIES",
    "EmbeddingBackendUnavailable",
    "EmbeddingProvider",
    "ErrorAnalysis",
    "EvaluationReport",
    "HashingEmbeddingProvider",
    "LabeledPair",
    "NGramConfig",
    "NGramVectorizer",
    "PAIR_FEATURE_NAMES",
    "PairFeatureExtractor",
    "PairFeatures",
    "RobustnessPoint",
    "SentenceTransformerEmbeddingProvider",
    "Standardizer",
    "StylometricFeatures",
    "StylometryEvaluator",
    "TransformName",
    "VerificationModel",
    "add_noise",
    "apply_transform",
    "average_precision",
    "best_f1_threshold",
    "build_alias_contexts",
    "build_alias_documents",
    "candidate_pairs",
    "change_case",
    "character_ngrams",
    "cosine_similarity",
    "counter_cosine",
    "embed_cosine",
    "embed_many",
    "hashed_ngram_vector",
    "normalize_slang",
    "paraphrase",
    "remove_punctuation",
    "run_full_evaluation",
    "shorten",
    "stratified_split",
    "stylometric_similarity",
    "tokenize_words",
    "translate",
    "word_ngrams",
]
