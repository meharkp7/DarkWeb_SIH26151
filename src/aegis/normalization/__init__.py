"""Normalization and deduplication layer (Phase 06).

    raw -> canonical encoding -> metadata normalization -> exact hash
        -> near-duplicate clustering -> source lineage -> Observation
"""

from aegis.normalization.canonical import (
    CANONICAL_VERSION,
    VOLATILE_METADATA_KEYS,
    canonical_text,
    normalize_metadata,
    normalized_text,
    strip_html,
)
from aegis.normalization.clusters import (
    ClusterAssignment,
    DuplicateCluster,
    DuplicateClusterer,
    Fingerprint,
)
from aegis.normalization.fingerprints import (
    content_hash,
    hamming_distance,
    jaccard_from_signatures,
    jaccard_sets,
    minhash_buckets,
    minhash_signatures,
    normalized_hash,
    shingles,
    simhash64,
)
from aegis.normalization.lineage import (
    CycleError,
    LineageError,
    SourceLineage,
    SourceLineageRegistry,
)
from aegis.normalization.pipeline import (
    BatchResult,
    NormalizationPipeline,
    NormalizedDocument,
)

__all__ = [
    "CANONICAL_VERSION",
    "BatchResult",
    "ClusterAssignment",
    "CycleError",
    "DuplicateCluster",
    "DuplicateClusterer",
    "Fingerprint",
    "LineageError",
    "NormalizedDocument",
    "NormalizationPipeline",
    "SourceLineage",
    "SourceLineageRegistry",
    "VOLATILE_METADATA_KEYS",
    "canonical_text",
    "content_hash",
    "hamming_distance",
    "jaccard_from_signatures",
    "jaccard_sets",
    "minhash_buckets",
    "minhash_signatures",
    "normalize_metadata",
    "normalized_hash",
    "normalized_text",
    "shingles",
    "simhash64",
    "strip_html",
]
