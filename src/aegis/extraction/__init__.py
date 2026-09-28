"""Entity extraction layer (Phase 07).

Deterministic extractors (handles, PGP fingerprints, wallets, domains,
onions, emails, URLs) validated by checksums where the format defines
one, plus a lightweight domain NER for platforms and role-scoped
aliases. Output is the canonical ``Entity`` schema with span
provenance.
"""

from aegis.extraction.extractors import (
    DEFAULT_EXTRACTORS,
    BaseExtractor,
    DomainExtractor,
    EmailExtractor,
    EntityMatch,
    HandleExtractor,
    OnionExtractor,
    PgpExtractor,
    UrlExtractor,
    WalletExtractor,
    extract_all,
)
from aegis.extraction.ner import (
    DEFAULT_PLATFORM_GAZETTEER,
    NAME_STOPWORDS,
    ROLE_CUES,
    PlatformMentionExtractor,
    RoleCueAliasExtractor,
)
from aegis.extraction.pipeline import ExtractionPipeline, ExtractionResult

__all__ = [
    "DEFAULT_EXTRACTORS",
    "DEFAULT_PLATFORM_GAZETTEER",
    "NAME_STOPWORDS",
    "ROLE_CUES",
    "BaseExtractor",
    "DomainExtractor",
    "EmailExtractor",
    "EntityMatch",
    "ExtractionPipeline",
    "ExtractionResult",
    "HandleExtractor",
    "OnionExtractor",
    "PgpExtractor",
    "PlatformMentionExtractor",
    "RoleCueAliasExtractor",
    "UrlExtractor",
    "WalletExtractor",
    "extract_all",
]
