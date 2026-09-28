"""Normalization pipeline (Phase 06): raw → canonical encoding →
metadata normalization → exact hash → near-duplicate clustering →
source lineage → :class:`Observation`.

The pipeline is pure: it turns text + metadata + provenance into
canonical ``Observation`` schemas and never touches the database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from aegis.normalization.canonical import (
    CANONICAL_VERSION,
    canonical_text,
    normalize_metadata,
    normalized_text,
)
from aegis.normalization.clusters import (
    ClusterAssignment,
    DuplicateCluster,
    DuplicateClusterer,
    Fingerprint,
)
from aegis.normalization.fingerprints import (
    content_hash,
    minhash_signatures,
    normalized_hash,
    simhash64,
)
from aegis.normalization.lineage import SourceLineageRegistry
from aegis.schemas.evidence import Observation


@dataclass(frozen=True)
class NormalizedDocument:
    """Result of canonical encoding + fingerprinting one text."""

    document_id: str
    text: str
    canonical: str
    normalized: str
    content_hash: str
    normalized_hash: str
    simhash: int
    minhash: tuple[int, ...]
    metadata: dict[str, Any]

    def fingerprint(self) -> Fingerprint:
        return Fingerprint(
            document_id=self.document_id,
            normalized_hash=self.normalized_hash,
            simhash=self.simhash,
            minhash=self.minhash,
        )


@dataclass(frozen=True)
class BatchResult:
    """Everything one batch pass produced."""

    documents: tuple[NormalizedDocument, ...]
    assignment: ClusterAssignment
    observations: tuple[Observation, ...]

    def clusters(self) -> tuple[DuplicateCluster, ...]:
        return self.assignment.clusters

    @property
    def duplicate_groups(self) -> list[DuplicateCluster]:
        return self.assignment.duplicate_groups


class NormalizationPipeline:
    """Stateless text normalization + batch clustering orchestration."""

    version = CANONICAL_VERSION

    def __init__(
        self,
        *,
        clusterer: DuplicateClusterer | None = None,
        lineage: SourceLineageRegistry | None = None,
    ) -> None:
        self.clusterer = clusterer or DuplicateClusterer()
        self.lineage = lineage or SourceLineageRegistry()

    # ------------------------------------------------------------ single doc

    def normalize_document(
        self,
        text: str,
        *,
        document_id: str,
        metadata: dict[str, Any] | None = None,
        html_input: bool = False,
    ) -> NormalizedDocument:
        if not document_id:
            raise ValueError("document_id must be non-empty")
        canonical = canonical_text(text, html_input=html_input)
        normalized = normalized_text(text, html_input=html_input)
        return NormalizedDocument(
            document_id=document_id,
            text=text,
            canonical=canonical,
            normalized=normalized,
            content_hash=content_hash(canonical),
            normalized_hash=normalized_hash(normalized),
            simhash=simhash64(normalized),
            minhash=minhash_signatures(normalized),
            metadata=normalize_metadata(metadata or {}),
        )

    # -------------------------------------------------------------- lineage

    def independence_group_for(self, source_id: str) -> str:
        """Independence group = root of the source's copy chain."""
        return self.lineage.independence_root(source_id)

    def lineage_path(self, source_id: str) -> tuple[str, ...]:
        """Chain ``root -> ... -> source_id`` (inclusive)."""
        if source_id not in self.lineage.sources:
            return (source_id,)
        path: list[str] = [source_id]
        current = source_id
        while True:
            record = self.lineage.get(current)
            if record is None or record.copied_from is None:
                break
            current = record.copied_from
            path.append(current)
        return tuple(reversed(path))

    # --------------------------------------------------------------- batch

    def process_batch(
        self,
        items: Sequence[tuple[str, str, dict[str, Any]]],
        *,
        evidence_ids: Sequence[UUID],
        source_id: str,
        collected_at: datetime,
        observed_at: datetime | None = None,
        independence_group: str | None = None,
    ) -> BatchResult:
        """Normalize a batch, cluster duplicates, emit Observations.

        ``items`` is a sequence of ``(document_id, text, metadata)``.
        """
        if len(items) != len(evidence_ids):
            raise ValueError("evidence_ids must align with items")

        documents = tuple(
            self.normalize_document(
                text, document_id=document_id, metadata=metadata
            )
            for document_id, text, metadata in items
        )
        assignment = self.clusterer.cluster(
            [document.fingerprint() for document in documents]
        )

        group = independence_group or self.independence_group_for(source_id)
        lineage_path = self.lineage_path(source_id)

        observations = tuple(
            self.build_observation(
                document,
                evidence_id=evidence_id,
                cluster_id=assignment.cluster_of(document.document_id) or "unassigned",
                independence_group=group,
                lineage_path=lineage_path,
                collected_at=collected_at,
                observed_at=observed_at,
            )
            for document, evidence_id in zip(documents, evidence_ids, strict=True)
        )

        return BatchResult(
            documents=documents, assignment=assignment, observations=observations
        )

    def build_observation(
        self,
        document: NormalizedDocument,
        *,
        evidence_id: UUID,
        cluster_id: str,
        independence_group: str,
        lineage_path: tuple[str, ...],
        collected_at: datetime,
        observed_at: datetime | None = None,
    ) -> Observation:
        """Wrap one normalized document in the canonical Observation schema."""
        return Observation(
            evidence_id=evidence_id,
            content_hash=document.content_hash,
            normalized_hash=document.normalized_hash,
            simhash=document.simhash,
            minhash_signatures=document.minhash,
            duplicate_cluster_id=cluster_id,
            source_lineage=lineage_path,
            independence_group=independence_group,
            normalization_version=self.version,
            observed_at=observed_at,
            collected_at=collected_at,
            metadata=dict(document.metadata),
        )
