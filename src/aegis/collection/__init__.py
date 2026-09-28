"""Collection layer (Phase 05): collector contract, synthetic collectors,
orchestration, and the ledger ingestion bridge."""

from aegis.collection.base import Collector
from aegis.collection.corpus import (
    CorpusActor,
    CorpusAlias,
    CorpusPost,
    CorpusRelationship,
    SyntheticCorpus,
    SyntheticCorpusBuilder,
    build_default_corpus,
)
from aegis.collection.ingest import CollectionIngestor, IngestionResult
from aegis.collection.orchestrator import (
    CollectionReport,
    CollectorOrchestrator,
    RateLimiter,
)
from aegis.collection.synthetic import (
    SyntheticChannelCollector,
    SyntheticForumCollector,
    SyntheticMarketplaceCollector,
    SyntheticSurfaceCollector,
)
from aegis.collection.types import (
    Candidate,
    CollectionScope,
    CollectorError,
    CollectorRejected,
    CollectorTimeout,
    JobType,
    NormalizedArtifact,
    RawArtifact,
)

__all__ = [
    "Candidate",
    "Collector",
    "CollectorError",
    "CollectorOrchestrator",
    "CollectorRejected",
    "CollectorTimeout",
    "CollectionIngestor",
    "CollectionReport",
    "CollectionScope",
    "CorpusActor",
    "CorpusAlias",
    "CorpusPost",
    "CorpusRelationship",
    "IngestionResult",
    "JobType",
    "NormalizedArtifact",
    "RateLimiter",
    "RawArtifact",
    "SyntheticChannelCollector",
    "SyntheticCorpus",
    "SyntheticCorpusBuilder",
    "SyntheticForumCollector",
    "SyntheticMarketplaceCollector",
    "SyntheticSurfaceCollector",
    "build_default_corpus",
]
