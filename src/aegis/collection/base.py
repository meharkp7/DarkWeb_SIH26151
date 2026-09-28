"""Collector interface (spec §11).

Every collector implements the same three-phase contract::

    discover(scope)  -> list[Candidate]     # find what could be collected
    collect(candidate) -> RawArtifact       # fetch bytes (rate-limited)
    normalize(artifact) -> list[NormalizedArtifact]  # canonical observations

Collectors never import the database layer; they are pure functions of
their input plus their configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from aegis.collection.types import (
    Candidate,
    CollectionScope,
    NormalizedArtifact,
    RawArtifact,
)


class Collector(ABC):
    """Base class for all collectors."""

    #: Unique collector name recorded on every evidence record.
    name: str = "collector"
    #: Semver of the collector; recorded as ``collector_version``.
    version: str = "0.0.0"
    #: Independent sources copied from this one share an independence group.
    independence_group: str = "collector-default"
    #: Maximum fetches per minute (0 = collector-defined default).
    rate_limit_per_minute: int = 60

    @abstractmethod
    async def discover(self, scope: CollectionScope) -> Sequence[Candidate]:
        """Return candidates matching *scope* without fetching bodies."""

    @abstractmethod
    async def collect(self, candidate: Candidate) -> RawArtifact:
        """Fetch the raw bytes for one candidate."""

    @abstractmethod
    async def normalize(self, artifact: RawArtifact) -> Sequence[NormalizedArtifact]:
        """Produce canonical observations from a raw artifact."""

    async def run(self, scope: CollectionScope) -> list[NormalizedArtifact]:
        """discover → collect → normalize for every candidate in scope."""
        out: list[NormalizedArtifact] = []
        for candidate in await self.discover(scope):
            artifact = await self.collect(candidate)
            out.extend(await self.normalize(artifact))
        return out
