"""Lightweight domain NER (Phase 07, after deterministic extraction).

No ML runtime dependency: a gazetteer plus context-cue grammar gives
precision-first recognition of the entity types this domain cares
about — platforms (marketplaces/forums/channels) and role-scoped
aliases — where an off-the-shelf NER model would tag neither.

The extractor interface matches the deterministic fleet, so the same
pipeline, span provenance, and tests cover both.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from aegis.extraction.extractors import BaseExtractor, EntityMatch, _match
from aegis.ontology import EntityType

#: Default gazetteer seeded from the synthetic corpus platform names.
DEFAULT_PLATFORM_GAZETTEER: dict[str, EntityType] = {
    "forum_alpha": EntityType.FORUM,
    "market_beta": EntityType.MARKETPLACE,
    "chat_delta": EntityType.CHANNEL,
    "paste_gamma": EntityType.FORUM,
}

#: Role cues that introduce a person-scoped alias ("vendor ghostbroker").
ROLE_CUES: frozenset[str] = frozenset(
    {
        "vendor", "seller", "buyer", "customer", "admin", "administrator",
        "moderator", "mod", "operator", "staff", "reseller", "owner",
        "curator", "broker", "supplier", "affiliate",
    }
)

#: Tokens that follow role cues but are prose, not names.
NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "will", "would", "shall", "should", "may", "might", "must", "can",
        "could", "do", "does", "did", "has", "have", "had", "not", "no",
        "and", "or", "but", "if", "then", "than", "so", "as", "of", "to",
        "for", "from", "by", "in", "on", "at", "with", "without", "into",
        "this", "that", "these", "those", "it", "its", "they", "them",
        "who", "what", "when", "where", "why", "how", "all", "any", "some",
        "shipped", "ship", "sent", "send", "paid", "pay", "buy", "sell",
        "listed", "posts", "post", "writes", "write", "said", "says",
        "here", "there", "now", "today", "yesterday", "new", "old",
        "first", "last", "next", "previous", "please", "thanks", "thank",
    }
)

#: Names that commonly precede a platform suffix in prose but do not
#: denote a platform: "traded on the black market" must not extract
#: a marketplace entity.
SUFFIX_NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "on", "in", "at", "to", "for", "from", "by",
        "black", "grey", "gray", "underground", "open", "free", "global",
        "local", "new", "old", "second", "secret", "hidden", "dark",
        "job", "stock", "capital", "property", "farmers", "real",
        "world", "night", "wide", "source", "media",
        "social", "online", "digital", "virtual", "whole",
    }
)

#: Generic single-word platforms that should not become entities from
#: prose alone (only the explicit ``X market/forum`` grammar fires).
_PLATFORM_SUFFIX_GRAMMAR: tuple[tuple[str, EntityType], ...] = (
    ("marketplace", EntityType.MARKETPLACE),
    ("market", EntityType.MARKETPLACE),
    ("forum", EntityType.FORUM),
    ("board", EntityType.FORUM),
    ("channel", EntityType.CHANNEL),
    ("community", EntityType.FORUM),
)


@dataclass(frozen=True)
class _PlatformGazetteer:
    """Exact-name lookup with light normalization (case, separators)."""

    names: Mapping[str, EntityType] = field(default_factory=dict)

    @classmethod
    def from_iterable(
        cls, entries: Iterable[tuple[str, EntityType]]
    ) -> _PlatformGazetteer:
        return cls({name.strip().lower(): kind for name, kind in entries})

    def lookup(self, token: str) -> EntityType | None:
        return self.names.get(token.strip().lower())


class PlatformMentionExtractor(BaseExtractor):
    """Recognize platform mentions: gazetteer hits + ``X <role>`` grammar.

    Grammar covers "Acme market"/"Alpha forum" style mentions; the
    gazetteer covers exact known names.
    """

    name = "ner_platform"
    entity_types = frozenset(
        {EntityType.MARKETPLACE, EntityType.FORUM, EntityType.CHANNEL}
    )

    def __init__(
        self, gazetteer: Mapping[str, EntityType] | None = None
    ) -> None:
        table = dict(DEFAULT_PLATFORM_GAZETTEER)
        if gazetteer:
            table.update({k.strip().lower(): v for k, v in gazetteer.items()})
        self.gazetteer = _PlatformGazetteer(names=table)

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        consumed: list[tuple[int, int]] = []

        # (1) explicit "NAME <suffix>" grammar
        grammar = re.compile(
            r"(?<![A-Za-z0-9_])"
            r"(?P<name>[A-Za-z][A-Za-z0-9_-]{1,40})\s+"
            r"(?P<suffix>marketplace|market|forum|board|channel|community)"
            r"(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        for match in grammar.finditer(text):
            name = match.group("name")
            suffix = match.group("suffix").lower()
            if name.lower() in SUFFIX_NAME_STOPWORDS:
                continue
            kind = next(t for s, t in _PLATFORM_SUFFIX_GRAMMAR if s == suffix)
            normalized = f"{name.strip().lower()} {suffix}"
            consumed.append((match.start(), match.end()))
            matches.append(
                _match(
                    kind,
                    text,
                    match.start(),
                    match.end(),
                    normalized,
                    0.70,
                    cue="suffix_grammar",
                )
            )

        # (2) exact gazetteer names (single tokens / underscored names)
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9_-]{1,40}", text):
            if any(start <= match.start() < end for start, end in consumed):
                continue
            gazetteer_kind = self.gazetteer.lookup(match.group(0))
            if gazetteer_kind is None:
                continue
            matches.append(
                _match(
                    gazetteer_kind,
                    text,
                    match.start(),
                    match.end(),
                    match.group(0).lower(),
                    0.90,
                    cue="gazetteer",
                )
            )
        return matches


class RoleCueAliasExtractor(BaseExtractor):
    """``<role cue> <name>`` -> alias entity.

    Example: "vendor ghostbroker" yields an ALIAS for ``ghostbroker``
    with the role in metadata. Prose after the cue ("vendor shipped")
    is filtered by the stopword list.
    """

    name = "ner_alias"
    entity_types = frozenset({EntityType.ALIAS})

    def extract(self, text: str) -> list[EntityMatch]:
        pattern = re.compile(
            r"(?<![A-Za-z0-9_])"
            r"(?P<role>vendor|seller|buyer|customer|admin|administrator|"
            r"moderator|mod|operator|staff|reseller|owner|curator|broker|"
            r"supplier|affiliate)"
            r"(?![A-Za-z0-9_])\s*[:#@]?\s+"
            r"(?P<name>[A-Za-z0-9_][A-Za-z0-9_.-]{1,31})"
            r"(?![A-Za-z0-9_-])",
            re.IGNORECASE,
        )
        matches: list[EntityMatch] = []
        for match in pattern.finditer(text):
            role = match.group("role").lower()
            name = match.group("name").rstrip(".-")
            if len(name) < 2 or name.lower() in NAME_STOPWORDS:
                continue
            if role not in ROLE_CUES:
                continue
            matches.append(
                _match(
                    EntityType.ALIAS,
                    text,
                    match.start("name"),
                    match.end("name"),
                    name.lower(),
                    0.65,
                    role=role,
                )
            )
        return matches
