"""Content fingerprints: exact hashes, SimHash, and MinHash (Phase 06).

    exact hash          SHA-256 over canonical text
    normalized hash     SHA-256 over case-folded canonical text
    SimHash (64-bit)    near-duplicate distance signal
    MinHash (64 perms)  Jaccard estimate for shingle sets

All functions are deterministic and dependency-free.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable, Sequence

DEFAULT_MINHASH_PERMUTATIONS = 64
DEFAULT_SHINGLE_SIZE = 3

_MASK64 = (1 << 64) - 1


def content_hash(canonical: str) -> str:
    """SHA-256 of the canonical encoding (case preserved)."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalized_hash(normalized: str) -> str:
    """SHA-256 of the case-folded canonical encoding."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return [token for token in text.lower().split() if token]


def _feature_hash(feature: str) -> int:
    return int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")


def simhash64(text: str) -> int:
    """64-bit SimHash over word tokens and character 3-grams."""
    features: dict[str, float] = {}

    for token in _tokens(text):
        features[f"w:{token}"] = features.get(f"w:{token}", 0.0) + 1.0
        padded = f"#{token}#"
        for index in range(len(padded) - 2):
            gram = padded[index : index + 3]
            key = f"c:{gram}"
            features[key] = features.get(key, 0.0) + 0.5

    if not features:
        return 0

    vector = [0] * 64
    for feature, weight in features.items():
        digest = _feature_hash(feature)
        for bit in range(64):
            if digest >> bit & 1:
                vector[bit] += int(weight * 2) or 1
            else:
                vector[bit] -= int(weight * 2) or 1

    value = 0
    for bit in range(64):
        if vector[bit] > 0:
            value |= 1 << bit
    return value & _MASK64


def hamming_distance(left: int, right: int) -> int:
    """Population count of the XOR of two 64-bit fingerprints."""
    return ((left ^ right) & _MASK64).bit_count()


def shingles(text: str, size: int = DEFAULT_SHINGLE_SIZE) -> set[str]:
    """Word shingles of order *size* (stable, order-sensitive)."""
    tokens = _tokens(text)
    if not tokens:
        return set()
    if len(tokens) < size:
        return {" ".join(tokens)}
    return {" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def _shingle_hash(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def minhash_signatures(
    text: str,
    *,
    permutations: int = DEFAULT_MINHASH_PERMUTATIONS,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
) -> tuple[int, ...]:
    """MinHash signature estimating Jaccard similarity of shingle sets."""
    values = shingles(text, shingle_size)
    if not values:
        return tuple(0 for _ in range(permutations))

    base = sorted(_shingle_hash(v) for v in values)
    signatures: list[int] = []
    for seed in range(permutations):
        # Affine family f_seed(h) = a*h + b (mod 2^64). Parameters depend
        # ONLY on the seed, never on the document, so two documents are
        # always hashed into the same family and their minima comparable.
        multiplier = (2 * seed + 1) | 1  # odd -> bijective mod 2^64
        offset = ((seed + 1) * 0x9E3779B97F4A7C15) & _MASK64
        best = _MASK64
        for h in base:
            candidate = (multiplier * h + offset) & _MASK64
            if candidate < best:
                best = candidate
        signatures.append(best)
    return tuple(signatures)


def jaccard_from_signatures(left: Sequence[int], right: Sequence[int]) -> float:
    """Fraction of equal MinHash slots."""
    if not left or len(left) != len(right):
        return 0.0
    matches = sum(1 for a, b in zip(left, right, strict=True) if a == b)
    return matches / len(left)


def jaccard_sets(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def minhash_buckets(signatures: Sequence[int], band_size: int = 8) -> list[tuple[int, int]]:
    """LSH band buckets: (band_index, band_hash) candidate keys."""
    if band_size <= 0 or len(signatures) % band_size != 0:
        raise ValueError(
            f"signature length {len(signatures)} not divisible by band size {band_size}"
        )
    buckets: list[tuple[int, int]] = []
    for band_index, start in enumerate(range(0, len(signatures), band_size)):
        band = signatures[start : start + band_size]
        packed = b"".join(struct.pack(">Q", value & _MASK64) for value in band)
        digest = int.from_bytes(hashlib.blake2b(packed, digest_size=8).digest(), "big")
        buckets.append((band_index, digest))
    return buckets
