"""Deterministic synthetic corpus with known ground truth (Phase 05).

Target dataset from the implementation plan:

    100 actors
    1,000 posts
    500+ known relationships

Ground truth (which aliases belong to which actor, who replied to whom)
is carried *in* the corpus so evaluation code can compare against it, and
is never exposed to model inputs.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

PLATFORMS: dict[str, str] = {
    "forum_alpha": "forum",
    "market_beta": "marketplace",
    "paste_gamma": "surface",
    "chat_delta": "channel",
}

PERSONAS: tuple[str, ...] = ("broker", "developer", "operator", "seller", "researcher")
LANGUAGES: tuple[str, ...] = ("en", "ru", "de", "fr", "es")

_TOPIC_TERMS: tuple[str, ...] = (
    "escrow",
    "dump",
    "fees",
    "rotation",
    "listing",
    "vendor",
    "wallet",
    "session",
    "mirror",
    "invites",
    "reviews",
    "shipping",
    "leak",
    "bounty",
)

_STYLE_MARKERS: dict[int, tuple[str, ...]] = {
    0: ("imo", "tbh", "lol"),  # casual
    1: ("nb.", "regards,", "per above"),  # formal
    2: (":-)", "==>", "fyi"),  # symbol-heavy
    3: ("shipped", "asap", "net"),  # clipped
}


@dataclass(frozen=True)
class CorpusActor:
    actor_id: str
    persona: str
    language: str
    style_marker: int
    home_platform: str


@dataclass(frozen=True)
class CorpusAlias:
    alias_id: str
    actor_id: str  # ground truth — never a model input
    handle: str
    platform: str
    first_seen: datetime
    last_seen: datetime


@dataclass(frozen=True)
class CorpusPost:
    post_id: str
    alias_id: str
    platform: str
    thread_id: str
    parent_post_id: str | None
    title: str
    body: str
    posted_at: datetime


@dataclass(frozen=True)
class CorpusRelationship:
    relationship_id: str
    source_id: str
    target_id: str
    relationship_type: str  # same_actor | replies_to | mentions


@dataclass(frozen=True)
class SyntheticCorpus:
    """Immutable generated corpus + ground truth."""

    seed: int
    actors: tuple[CorpusActor, ...]
    aliases: tuple[CorpusAlias, ...]
    posts: tuple[CorpusPost, ...]
    relationships: tuple[CorpusRelationship, ...]
    platforms: tuple[str, ...] = tuple(PLATFORMS)

    @property
    def same_actor_pairs(self) -> set[tuple[str, str]]:
        """Ground-truth alias pairs that belong to one actor (order-normalized)."""
        by_actor: dict[str, list[str]] = {}
        for alias in self.aliases:
            by_actor.setdefault(alias.actor_id, []).append(alias.alias_id)

        pairs: set[tuple[str, str]] = set()
        for alias_ids in by_actor.values():
            ordered = sorted(alias_ids)
            for index, left in enumerate(ordered):
                for right in ordered[index + 1 :]:
                    pairs.add((left, right))
        return pairs

    @property
    def alias_by_id(self) -> dict[str, CorpusAlias]:
        return {alias.alias_id: alias for alias in self.aliases}

    def posts_for_platform(self, platform_kind: str) -> list[CorpusPost]:
        kinds = {name for name, kind in PLATFORMS.items() if kind == platform_kind}
        return [post for post in self.posts if post.platform in kinds]


def _stable_id(*parts: object, length: int = 16) -> str:
    material = "|".join(str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]


class SyntheticCorpusBuilder:
    """Build the Phase 05 benchmark corpus deterministically from a seed."""

    def __init__(
        self,
        seed: int = 26151,
        actor_count: int = 100,
        post_count: int = 1000,
    ) -> None:
        self.seed = seed
        self.actor_count = actor_count
        self.post_count = post_count

    def build(self) -> SyntheticCorpus:
        rng = random.Random(self.seed)
        platform_names = list(PLATFORMS)

        base_time = datetime(2026, 1, 1, tzinfo=UTC)

        # ----------------------------------------------------------- actors
        actors: list[CorpusActor] = []
        for index in range(self.actor_count):
            actor_id = f"actor-{index + 1:04d}"
            actors.append(
                CorpusActor(
                    actor_id=actor_id,
                    persona=rng.choice(PERSONAS),
                    language=rng.choice(LANGUAGES),
                    style_marker=index % len(_STYLE_MARKERS),
                    home_platform=rng.choice(platform_names),
                )
            )

        # ----------------------------------------------------------- aliases
        aliases: list[CorpusAlias] = []
        for actor in actors:
            alias_count = 2 + rng.randint(0, 2)  # 2..4 aliases -> multi-platform personas
            chosen = rng.sample(platform_names, k=min(alias_count, len(platform_names)))
            for position, platform in enumerate(chosen):
                handle = f"{actor.actor_id}_{platform}_{position}"
                first_seen = base_time + timedelta(days=rng.randint(0, 40))
                last_seen = first_seen + timedelta(days=rng.randint(30, 120))
                aliases.append(
                    CorpusAlias(
                        alias_id=_stable_id("alias", actor.actor_id, platform, position),
                        actor_id=actor.actor_id,
                        handle=handle,
                        platform=platform,
                        first_seen=first_seen,
                        last_seen=last_seen,
                    )
                )

        alias_by_id = {alias.alias_id: alias for alias in aliases}
        aliases_by_platform: dict[str, list[CorpusAlias]] = {}
        for alias in aliases:
            aliases_by_platform.setdefault(alias.platform, []).append(alias)

        # ------------------------------------------------------------- posts
        posts: list[CorpusPost] = []
        thread_ids = [f"thread-{n:04d}" for n in range(max(10, self.post_count // 10))]
        posts_by_platform: dict[str, list[CorpusPost]] = {name: [] for name in PLATFORMS}

        for index in range(self.post_count):
            platform = rng.choice(platform_names)
            alias = rng.choice(aliases_by_platform[platform])
            actor = next(a for a in actors if a.actor_id == alias.actor_id)
            style = _STYLE_MARKERS[actor.style_marker]
            terms = rng.sample(_TOPIC_TERMS, k=3)
            parent: CorpusPost | None = None
            existing = posts_by_platform[platform]
            if existing and rng.random() < 0.15:
                parent = rng.choice(existing[-25:])

            posted_at = alias.first_seen + timedelta(
                days=rng.randint(0, 90), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
            )
            title = f"{terms[0]} {terms[1]} #{index:04d}"
            body = (
                f"{terms[0]} update: {terms[1]} {terms[2]} {rng.choice(style)}. "
                f"fees stay fixed, {terms[0]} rotation asap."
            )
            post = CorpusPost(
                post_id=f"post-{index:05d}",
                alias_id=alias.alias_id,
                platform=platform,
                thread_id=parent.thread_id if parent else rng.choice(thread_ids),
                parent_post_id=parent.post_id if parent else None,
                title=title,
                body=body,
                posted_at=posted_at,
            )
            posts.append(post)
            posts_by_platform[platform].append(post)

        # ----------------------------------------------------- relationships
        relationships: list[CorpusRelationship] = []

        # (1) same-actor alias pairs (ground-truth identity links)
        by_actor: dict[str, list[CorpusAlias]] = {}
        for alias in aliases:
            by_actor.setdefault(alias.actor_id, []).append(alias)
        for _, alias_list in sorted(by_actor.items()):
            ordered = sorted(alias_list, key=lambda a: a.alias_id)
            for index, left in enumerate(ordered):
                for right in ordered[index + 1 :]:
                    relationships.append(
                        CorpusRelationship(
                            relationship_id=_stable_id("rel", left.alias_id, right.alias_id),
                            source_id=left.alias_id,
                            target_id=right.alias_id,
                            relationship_type="same_actor",
                        )
                    )

        # (2) reply links (cross-alias interaction)
        for post in posts:
            if post.parent_post_id:
                parent = next(p for p in posts if p.post_id == post.parent_post_id)
                if parent.alias_id != post.alias_id:
                    relationships.append(
                        CorpusRelationship(
                            relationship_id=_stable_id("rel", parent.post_id, post.post_id),
                            source_id=post.post_id,
                            target_id=parent.post_id,
                            relationship_type="replies_to",
                        )
                    )

        # (3) mention links (cross-alias interaction)
        alias_ids = sorted(alias_by_id)
        for index, post in enumerate(posts):
            if index % 9 == 0:
                target = alias_ids[(index * 7) % len(alias_ids)]
                if target != post.alias_id:
                    relationships.append(
                        CorpusRelationship(
                            relationship_id=_stable_id("rel", post.post_id, target),
                            source_id=post.post_id,
                            target_id=target,
                            relationship_type="mentions",
                        )
                    )

        return SyntheticCorpus(
            seed=self.seed,
            actors=tuple(actors),
            aliases=tuple(aliases),
            posts=tuple(posts),
            relationships=tuple(relationships),
        )


def build_default_corpus(seed: int = 26151) -> SyntheticCorpus:
    """The Phase 05 default fixture: 100 actors / 1,000 posts / 500+ relations."""
    return SyntheticCorpusBuilder(seed=seed).build()


def corpus_summary(corpus: SyntheticCorpus) -> dict[str, int]:
    counts = {
        "actors": len(corpus.actors),
        "aliases": len(corpus.aliases),
        "posts": len(corpus.posts),
        "relationships": len(corpus.relationships),
        "ground_truth_same_actor_pairs": len(corpus.same_actor_pairs),
    }
    return counts


def iter_platforms(corpus: SyntheticCorpus, kind: str) -> Sequence[str]:
    return [name for name, k in PLATFORMS.items() if k == kind]
