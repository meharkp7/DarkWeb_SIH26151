"""Source lineage: which sources are actually independent (Phase 06).

A marketplace mirror that copies a forum post, a paste that reposts a
mirror, etc. all descend from one original observation. Independence is
a property of the *source chain*, not of each fetch:

    origin -> mirror -> scraper   all share one independence root

The registry resolves a source to its root (cycle-safe), and provides
the redundancy discount used by evidence fusion: a group of ``n``
dependent observations counts once, not ``n`` times.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field


class LineageError(RuntimeError):
    """Raised for invalid lineage registration (unknown/foreign roots)."""


@dataclass(frozen=True)
class SourceLineage:
    """One source and (optionally) where it copies from."""

    source_id: str
    copied_from: str | None = None
    origin: str = ""
    label: str = ""

    @property
    def declared_root(self) -> str:
        return self.copied_from or self.source_id


@dataclass
class SourceLineageRegistry:
    """Maps sources to their independence root by following copy chains.

    ``A copies from B copies from C`` -> all three resolve to ``C``.
    Cycles are rejected at registration time.
    """

    _sources: dict[str, SourceLineage] = field(default_factory=dict)

    # ------------------------------------------------------------ register

    def register(
        self,
        source_id: str,
        *,
        copied_from: str | None = None,
        origin: str = "",
        label: str = "",
    ) -> SourceLineage:
        if not source_id:
            raise LineageError("source_id must be non-empty")
        if copied_from == source_id:
            raise LineageError(f"source {source_id!r} cannot copy from itself")

        if copied_from is not None and copied_from not in self._sources:
            raise LineageError(
                f"source {source_id!r} copies from unknown source {copied_from!r}"
            )

        existing = self._sources.get(source_id)
        if existing is not None:
            if existing.copied_from == copied_from:
                return existing
            # Re-registration updates the copy edge (e.g. a source's
            # upstream is confirmed later). The new edge is validated
            # before it is committed so a cycle can never persist.
            updated = SourceLineage(
                source_id=source_id,
                copied_from=copied_from,
                origin=origin or existing.origin,
                label=label or existing.label,
            )
            self._sources[source_id] = updated
            try:
                self._resolve(source_id)
            except CycleError:
                self._sources[source_id] = existing
                raise
            return updated

        record = SourceLineage(
            source_id=source_id, copied_from=copied_from, origin=origin, label=label
        )
        self._sources[source_id] = record
        return record

    def register_chain(self, source_ids: Iterable[str], *, origin: str = "") -> None:
        """Register ``A <- B <- C``: each entry copies from the previous."""
        previous: str | None = None
        for source_id in source_ids:
            self.register(source_id, copied_from=previous, origin=origin)
            previous = source_id

    # ------------------------------------------------------------- resolve

    def _resolve(self, source_id: str) -> SourceLineage:
        seen: set[str] = set()
        current = source_id
        while True:
            if current in seen:
                raise CycleError(f"lineage cycle detected at source {current!r}")
            seen.add(current)
            record = self._sources.get(current)
            if record is None:
                raise LineageError(f"unknown source {current!r}")
            if record.copied_from is None:
                return record
            current = record.copied_from

    def independence_root(self, source_id: str) -> str:
        """Root of the copy chain containing *source_id*."""
        if source_id not in self._sources:
            # Unregistered sources are their own roots (independent by default).
            return source_id
        return self._resolve(source_id).source_id

    def same_independence_group(self, left: str, right: str) -> bool:
        return self.independence_root(left) == self.independence_root(right)

    def members(self, root: str) -> list[str]:
        """Every source whose independence root is *root* (root included)."""
        return sorted(
            source_id
            for source_id in self._sources
            if self.independence_root(source_id) == root
        )

    def get(self, source_id: str) -> SourceLineage | None:
        return self._sources.get(source_id)

    @property
    def sources(self) -> dict[str, SourceLineage]:
        return dict(self._sources)

    # ------------------------------------------------------------- discount

    @staticmethod
    def redundancy_discount(dependent_count: int) -> float:
        """Discount applied to each member of a group of dependent fetches.

        ``n`` fetches of the same underlying observation contribute one
        observation total (each worth ``1/n``), so copied content cannot
        manufacture equivalent confidence. Independent evidence has
        ``n == 1`` and is undiminished.
        """
        if dependent_count < 1:
            raise ValueError("dependent_count must be >= 1")
        return 1.0 / dependent_count

    @classmethod
    def log_discount(cls, dependent_count: int) -> float:
        """Softer variant ``1 / (1 + ln n)`` for very large copy rings."""
        if dependent_count < 1:
            raise ValueError("dependent_count must be >= 1")
        return 1.0 / (1.0 + math.log(dependent_count))


class CycleError(LineageError):
    """Copy chain loops back on itself."""
