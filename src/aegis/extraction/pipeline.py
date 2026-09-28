"""Extraction pipeline (Phase 07): text + provenance → canonical Entities.

The pipeline slices spans out of the source text (so ``surface_form``
provably equals ``text[start:end]``), validates every match against the
canonical :class:`~aegis.schemas.entity.Entity` schema, and never
touches the database — persistence is layered on separately.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aegis.extraction.extractors import (
    DEFAULT_EXTRACTORS,
    BaseExtractor,
    EntityMatch,
    extract_all,
)
from aegis.extraction.ner import PlatformMentionExtractor, RoleCueAliasExtractor
from aegis.ontology import EntityType
from aegis.schemas.entity import Entity, EntitySpan


@dataclass(frozen=True)
class ExtractionResult:
    """Canonical entities plus the matches they were built from."""

    entities: tuple[Entity, ...]
    matches: tuple[EntityMatch, ...]

    def by_type(self) -> dict[EntityType, list[Entity]]:
        grouped: dict[EntityType, list[Entity]] = {}
        for entity in self.entities:
            grouped.setdefault(entity.entity_type, []).append(entity)
        return grouped

    def count(self, entity_type: EntityType) -> int:
        return sum(1 for e in self.entities if e.entity_type == entity_type)


class ExtractionPipeline:
    """Deterministic extraction (+ optional domain NER) over one text."""

    def __init__(
        self,
        extractors: Sequence[BaseExtractor] | None = None,
        *,
        include_ner: bool = True,
    ) -> None:
        if extractors is not None:
            self.extractors = tuple(extractors)
        elif include_ner:
            self.extractors = DEFAULT_EXTRACTORS + (
                PlatformMentionExtractor(),
                RoleCueAliasExtractor(),
            )
        else:
            self.extractors = DEFAULT_EXTRACTORS

    def extract_matches(self, text: str) -> list[EntityMatch]:
        """All validated matches, deduplicated by (type, span), sorted."""
        return extract_all(text, self.extractors)

    def extract(
        self,
        text: str,
        *,
        evidence_id: UUID,
        case_id: UUID | None = None,
        field_name: str = "body",
        first_seen: datetime | None = None,
        last_seen: datetime | None = None,
    ) -> ExtractionResult:
        matches = self.extract_matches(text)
        entities: list[Entity] = []

        for match in matches:
            if not 0 <= match.start < match.end <= len(text):
                raise ValueError(
                    f"span [{match.start}, {match.end}) outside text of "
                    f"length {len(text)}"
                )
            surface = text[match.start : match.end]
            if match.surface_form and surface != match.surface_form:
                raise ValueError(
                    f"span provenance mismatch for {match.entity_type}: "
                    f"{surface!r} != {match.surface_form!r}"
                )
            entities.append(
                Entity(
                    entity_type=match.entity_type,
                    surface_form=surface,
                    normalized_form=match.normalized_form,
                    confidence=match.confidence,
                    evidence_id=evidence_id,
                    span=EntitySpan(
                        start=match.start, end=match.end, field=field_name
                    ),
                    case_id=case_id,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    metadata=dict(match.metadata),
                )
            )

        return ExtractionResult(
            entities=tuple(entities), matches=tuple(matches)
        )
