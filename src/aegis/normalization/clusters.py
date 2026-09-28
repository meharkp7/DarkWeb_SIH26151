"""Duplicate clustering: exact and near-duplicate grouping (Phase 06).

Pipeline position 3–4: ``exact hash -> near-duplicate -> cluster``.

Algorithm (scales via LSH, no O(n^2) full comparison):

1. **Exact**: identical ``normalized_hash`` -> same cluster.
2. **Candidate generation**:
   - MinHash LSH banding (64 permutations / bands of 8) for shingle
     overlap, and
   - SimHash banding (4 chunks of 16 bits) for edit-distance proximity.
3. **Verification**: candidate pairs merge only when estimated Jaccard
   >= threshold *and/or* Hamming distance <= threshold.
4. **Cluster id** is content-derived (hash of sorted member hashes) so
   the same member set always yields the same id.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from aegis.normalization.fingerprints import (
    hamming_distance,
    jaccard_from_signatures,
    minhash_buckets,
)

DEFAULT_JACCARD_THRESHOLD = 0.8
DEFAULT_SIMHASH_MAX_DISTANCE = 3


@dataclass(frozen=True)
class Fingerprint:
    """What the clusterer needs about one document."""

    document_id: str
    normalized_hash: str
    simhash: int
    minhash: tuple[int, ...]


@dataclass(frozen=True)
class DuplicateCluster:
    """A set of documents treating each other as copies."""

    cluster_id: str
    member_ids: tuple[str, ...]
    representative_hash: str

    @property
    def size(self) -> int:
        return len(self.member_ids)


@dataclass
class ClusterAssignment:
    """Clustering result for a batch."""

    clusters: tuple[DuplicateCluster, ...]
    document_to_cluster: dict[str, str]

    def cluster_of(self, document_id: str) -> str | None:
        return self.document_to_cluster.get(document_id)

    @property
    def duplicate_groups(self) -> list[DuplicateCluster]:
        return [cluster for cluster in self.clusters if cluster.size > 1]

    @property
    def singleton_count(self) -> int:
        return len(self.clusters) - len(self.duplicate_groups)


class _UnionFind:
    def __init__(self, keys: Sequence[str]) -> None:
        self._parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        # path compression
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root


class DuplicateClusterer:
    """Assigns duplicate clusters to a batch of fingerprints."""

    def __init__(
        self,
        *,
        jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
        simhash_max_distance: int = DEFAULT_SIMHASH_MAX_DISTANCE,
        band_size: int = 8,
        simhash_chunks: int = 4,
    ) -> None:
        if not 0.0 < jaccard_threshold <= 1.0:
            raise ValueError("jaccard_threshold must be in (0, 1]")
        if simhash_max_distance < 0 or simhash_max_distance > 64:
            raise ValueError("simhash_max_distance must be in [0, 64]")
        self.jaccard_threshold = jaccard_threshold
        self.simhash_max_distance = simhash_max_distance
        self.band_size = band_size
        self.simhash_chunks = simhash_chunks

    # ------------------------------------------------------------ analysis

    def cluster(self, documents: Sequence[Fingerprint]) -> ClusterAssignment:
        ids = [doc.document_id for doc in documents]
        if len(set(ids)) != len(ids):
            raise ValueError("document ids must be unique within a batch")

        union = _UnionFind(ids)
        by_id = {doc.document_id: doc for doc in documents}

        # (1) exact matches ------------------------------------------------
        by_normalized: dict[str, list[str]] = {}
        for doc in documents:
            by_normalized.setdefault(doc.normalized_hash, []).append(doc.document_id)
        for group in by_normalized.values():
            for other in group[1:]:
                union.union(group[0], other)

        # (2) candidate pairs from LSH buckets ------------------------------
        candidates: set[tuple[str, str]] = set()

        def _add_pairs(bucket_members: list[str]) -> None:
            for position, left_id in enumerate(bucket_members):
                for right_id in bucket_members[position + 1 :]:
                    candidates.add((left_id, right_id))

        minhash_index: dict[tuple[int, int], list[str]] = {}
        for doc in documents:
            try:
                signature_bands = minhash_buckets(doc.minhash, self.band_size)
            except ValueError:
                # Signature length not divisible by band size: skip LSH
                # for this document; exact/simhash paths still apply.
                signature_bands = []
            for band in signature_bands:
                minhash_index.setdefault(band, []).append(doc.document_id)
        for members in minhash_index.values():
            _add_pairs(members)

        chunk_width = 64 // self.simhash_chunks
        simhash_index: dict[tuple[int, int], list[str]] = {}
        for doc in documents:
            for chunk in range(self.simhash_chunks):
                part = (doc.simhash >> (chunk * chunk_width)) & ((1 << chunk_width) - 1)
                simhash_index.setdefault((chunk, part), []).append(doc.document_id)
        for members in simhash_index.values():
            _add_pairs(members)

        # (3) verification --------------------------------------------------
        for left_id, right_id in sorted(candidates):
            left_doc, right_doc = by_id[left_id], by_id[right_id]
            if left_doc.normalized_hash == right_doc.normalized_hash:
                union.union(left_id, right_id)
                continue
            jaccard = jaccard_from_signatures(left_doc.minhash, right_doc.minhash)
            distance = hamming_distance(left_doc.simhash, right_doc.simhash)
            if jaccard >= self.jaccard_threshold or distance <= self.simhash_max_distance:
                union.union(left_id, right_id)

        # (4) deterministic cluster ids -------------------------------------
        members_by_root: dict[str, list[str]] = {}
        for doc_id in ids:
            members_by_root.setdefault(union.find(doc_id), []).append(doc_id)

        clusters: list[DuplicateCluster] = []
        document_to_cluster: dict[str, str] = {}
        for members in members_by_root.values():
            ordered = tuple(sorted(members))
            # Content-derived id: members -> their normalized hashes sorted.
            member_hashes = sorted(by_id[member].normalized_hash for member in ordered)
            cluster_id = sha256("|".join(member_hashes).encode("utf-8")).hexdigest()[:16]
            clusters.append(
                DuplicateCluster(
                    cluster_id=cluster_id,
                    member_ids=ordered,
                    representative_hash=min(member_hashes),
                )
            )
            for member in ordered:
                document_to_cluster[member] = cluster_id

        clusters.sort(key=lambda cluster: cluster.cluster_id)
        return ClusterAssignment(
            clusters=tuple(clusters), document_to_cluster=document_to_cluster
        )
