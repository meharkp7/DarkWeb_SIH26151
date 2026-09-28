"""Synthetic collectors (Phase 05): forum, marketplace, and surface adapters.

These are the first collectors by policy (docs/data-source-policy.md
tier A): they fetch from an in-process deterministic corpus, carry full
ground truth, and never touch the database.

Exit criterion covered: ``synthetic source -> collector -> evidence``
works with the collector layer decoupled from persistence — the
orchestrator only produces value objects, and ``aegis.collection.ingest``
is the single bridge to the ledger.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256

from aegis.collection.base import Collector
from aegis.collection.corpus import PLATFORMS, SyntheticCorpus, build_default_corpus
from aegis.collection.types import (
    Candidate,
    CollectionScope,
    CollectorRejected,
    NormalizedArtifact,
    RawArtifact,
)


def _canonical_json(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class _SyntheticCollector(Collector):
    """Shared implementation for the three synthetic collector classes."""

    platform_kind: str = "forum"
    independence_group_prefix: str = "forum"

    def __init__(self, corpus: SyntheticCorpus | None = None, *, seed: int = 26151) -> None:
        self.corpus = corpus if corpus is not None else build_default_corpus(seed)
        self.rate_limit_per_minute = 0  # in-process fixtures: no external calls
        self._platforms = tuple(
            name for name, kind in PLATFORMS.items() if kind == self.platform_kind
        )

    def _in_scope(self, scope: CollectionScope) -> None:
        if scope.platforms and not set(scope.platforms) & set(self._platforms):
            raise CollectorRejected(
                f"{self.name}: scope platforms {sorted(scope.platforms)} exclude "
                f"{self.platform_kind} sources {sorted(self._platforms)}"
            )

    async def discover(self, scope: CollectionScope) -> Sequence[Candidate]:
        self._in_scope(scope)
        posts = [
            post
            for post in self.corpus.posts
            if post.platform in self._platforms
            and (scope.since is None or post.posted_at >= scope.since)
            and (scope.until is None or post.posted_at <= scope.until)
        ]
        posts.sort(key=lambda post: post.post_id)
        return [
            Candidate(
                candidate_id=post.post_id,
                source_ref=f"{post.platform}/{post.thread_id}/{post.post_id}",
                platform=post.platform,
                observed_hint=post.posted_at.isoformat(),
                metadata={"title": post.title},
            )
            for post in posts[: scope.limit]
        ]

    async def collect(self, candidate: Candidate) -> RawArtifact:
        post = next(p for p in self.corpus.posts if p.post_id == candidate.candidate_id)
        alias = self.corpus.alias_by_id[post.alias_id]
        body = _canonical_json(
            {
                "post_id": post.post_id,
                "platform": post.platform,
                "thread_id": post.thread_id,
                "parent_post_id": post.parent_post_id,
                "author_handle": alias.handle,
                "title": post.title,
                "body": post.body,
                "posted_at": post.posted_at.isoformat(),
            }
        )
        return RawArtifact(
            candidate=candidate,
            body=body,
            media_type="application/json",
            # Deterministic replay: derive collection time from the fixture
            # post rather than wall-clock, so repeated collection runs are
            # byte-identical (no clock-skew in dedup or time-travel tests).
            collected_at=post.posted_at,
            collector_name=self.name,
            collector_version=self.version,
            source_url=f"synthetic://{post.platform}/{post.post_id}",
            sha256=sha256(body).hexdigest(),
            metadata={"platform_kind": self.platform_kind},
        )

    async def normalize(self, artifact: RawArtifact) -> Sequence[NormalizedArtifact]:
        payload = json.loads(artifact.body.decode("utf-8"))
        text = f"{payload['title']}\n{payload['body']}"
        # Canonical encoding: lowercase, whitespace-collapsed; exact copy
        # detection later relies on this being stable across fetches.
        normalized_text = " ".join(text.lower().split())
        posted_at = datetime.fromisoformat(payload["posted_at"])
        platform = str(payload["platform"])
        return (
            NormalizedArtifact(
                raw=artifact,
                text=text,
                normalized_text=normalized_text,
                observed_at=posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=UTC),
                author_hint=str(payload["author_handle"]),
                platform=platform,
                independence_group=f"{self.independence_group_prefix}:{platform}",
                metadata={
                    "thread_id": payload["thread_id"],
                    "parent_post_id": payload["parent_post_id"],
                    "platform_kind": self.platform_kind,
                },
            ),
        )


class SyntheticForumCollector(_SyntheticCollector):
    """Forum adapter (``forum_alpha``)."""

    name = "synthetic_forum"
    version = "0.1.0"
    platform_kind = "forum"
    independence_group_prefix = "forum"


class SyntheticMarketplaceCollector(_SyntheticCollector):
    """Marketplace adapter (``market_beta``)."""

    name = "synthetic_marketplace"
    version = "0.1.0"
    platform_kind = "marketplace"
    independence_group_prefix = "marketplace"


class SyntheticSurfaceCollector(_SyntheticCollector):
    """Surface adapters: pastes and channels (``paste_gamma``, ``chat_delta``)."""

    name = "synthetic_surface"
    version = "0.1.0"
    platform_kind = "surface"
    independence_group_prefix = "surface"


class SyntheticChannelCollector(_SyntheticCollector):
    """Channel adapter (``chat_delta``)."""

    name = "synthetic_channel"
    version = "0.1.0"
    platform_kind = "channel"
    independence_group_prefix = "channel"
