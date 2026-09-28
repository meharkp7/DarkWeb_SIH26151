"""BehaviorProfile — behavioural features for an actor (Phase 12).

Nine feature groups from the plan:

======================  ==================================================
feature                 field(s)
======================  ==================================================
hour-of-day             :attr:`BehaviorProfile.hour_of_day` (24 bins)
day-of-week             :attr:`BehaviorProfile.day_of_week` (7 bins)
posting rate            :attr:`BehaviorProfile.posting_rate`
burstiness              :attr:`BehaviorProfile.burstiness`
inter-arrival           :attr:`BehaviorProfile.inter_arrival_distribution`
response latency        :attr:`BehaviorProfile.response_latency_mean`
topic distribution      :attr:`BehaviorProfile.topic_distribution`
platform distribution   :attr:`BehaviorProfile.platform_distribution`
interaction degree      :attr:`BehaviorProfile.interaction_degree`
======================  ==================================================

Profiles are built from :class:`PostingEvent` records (a small,
dependency-free adapter over collected posts) and are immutable and
deterministic. Comparison happens in :mod:`aegis.behavior.similarity`
via statistical distances — sequence models are explicitly deferred
(see that module's docstring for the roadmap note).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from aegis.collection.corpus import SyntheticCorpus

#: Default topic vocabulary; override per corpus if the domain differs.
DEFAULT_TOPIC_VOCABULARY: tuple[str, ...] = (
    "escrow",
    "bounty",
    "dump",
    "fees",
    "invites",
    "leak",
    "listing",
    "mirror",
    "reviews",
    "rotation",
    "session",
    "shipping",
    "vendor",
    "wallet",
)

#: Inter-arrival gap bins in seconds: <5m, <30m, <2h, <6h, <24h, <3d, <7d, >=7d.
INTER_ARRIVAL_BIN_EDGES: tuple[float, ...] = (
    300.0,
    1800.0,
    7200.0,
    21600.0,
    86400.0,
    259200.0,
    604800.0,
)
INTER_ARRIVAL_BIN_LABELS: tuple[str, ...] = (
    "<5m",
    "5-30m",
    "30m-2h",
    "2-6h",
    "6-24h",
    "1-3d",
    "3-7d",
    ">7d",
)

HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7
_MIN_WINDOW_DAYS = 1.0


@dataclass(frozen=True)
class PostingEvent:
    """One observable posting/interaction event.

    Args:
        event_id: Stable identifier of the post.
        author_id: The alias/account that produced it (the profiled
            identity groups several of these).
        posted_at: Publication timestamp (timezone-aware).
        platform: Source platform name.
        text: Post text, used for topic assignment.
        parent_author_id: Author of the post being replied to, if any.
        parent_posted_at: Timestamp of the parent post, if known —
            required for response-latency measurement.
    """

    event_id: str
    author_id: str
    posted_at: datetime
    platform: str
    text: str = ""
    parent_author_id: str | None = None
    parent_posted_at: datetime | None = None


def _normalized(counts: Sequence[float]) -> tuple[float, ...]:
    total = sum(counts)
    if total <= 0:
        return tuple(0.0 for _ in counts)
    return tuple(count / total for count in counts)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / len(values))


def assign_topic(text: str, vocabulary: Sequence[str]) -> str:
    """First vocabulary term present in *text* (else ``"general"``).

    A deterministic keyword scan stands in for a topic model; the
    vocabulary is caller-controlled so the function never depends on
    any ML component.
    """
    lowered = text.lower()
    for term in vocabulary:
        if term.lower() in lowered:
            return term
    return "general"


def events_from_corpus(
    corpus: SyntheticCorpus, actor_id: str | None = None
) -> tuple[PostingEvent, ...]:
    """Adapter: corpus posts to :class:`PostingEvent` records.

    Args:
        corpus: The synthetic corpus fixture.
        actor_id: When given, only that actor's aliases are returned;
            replies still resolve parents from the *whole* corpus so
            latency and counterparties stay correct.

    Returns:
        Events ordered by (timestamp, event id).
    """
    alias_actor = {alias.alias_id: alias.actor_id for alias in corpus.aliases}
    posts_by_id = {post.post_id: post for post in corpus.posts}
    events: list[PostingEvent] = []
    for post in corpus.posts:
        if actor_id is not None and alias_actor[post.alias_id] != actor_id:
            continue
        parent = posts_by_id.get(post.parent_post_id) if post.parent_post_id else None
        events.append(
            PostingEvent(
                event_id=post.post_id,
                author_id=post.alias_id,
                posted_at=post.posted_at,
                platform=post.platform,
                text=f"{post.title} {post.body}",
                parent_author_id=parent.alias_id if parent else None,
                parent_posted_at=parent.posted_at if parent else None,
            )
        )
    return tuple(sorted(events, key=lambda event: (event.posted_at, event.event_id)))


@dataclass(frozen=True)
class BehaviorProfile:
    """Statistical behaviour profile of one identity over a time window.

    Distributions are normalized (sum to 1) tuples with fixed widths
    except the topic/platform distributions, which carry explicit label
    tuples (:attr:`topic_labels`, :attr:`platform_labels`) so profiles
    built with different vocabularies can still be compared by label.
    """

    profile_id: str
    window_start: datetime
    window_end: datetime
    event_count: int
    hour_of_day: tuple[float, ...]
    day_of_week: tuple[float, ...]
    posting_rate: float
    burstiness: float
    inter_arrival_distribution: tuple[float, ...]
    response_latency_mean: float
    topic_labels: tuple[str, ...]
    topic_distribution: tuple[float, ...]
    platform_labels: tuple[str, ...]
    platform_distribution: tuple[float, ...]
    interaction_degree: float

    @property
    def window_days(self) -> float:
        """Length of the observation window in days (>= 1 day)."""
        return max((self.window_end - self.window_start).total_seconds() / 86400.0, 1.0)


def build_behavior_profile(
    events: Sequence[PostingEvent],
    *,
    profile_id: str,
    topic_vocabulary: Sequence[str] = DEFAULT_TOPIC_VOCABULARY,
    context_events: Sequence[PostingEvent] | None = None,
) -> BehaviorProfile:
    """Aggregate *events* into a :class:`BehaviorProfile`.

    Args:
        events: The events authored by the identity being profiled.
            Must be non-empty.
        profile_id: Identifier copied onto the profile.
        topic_vocabulary: Keywords for :func:`assign_topic`.
        context_events: Wider event stream (optional) used to count
            *inbound* replies; without it the interaction degree only
            sees outbound counterparties.

    Raises:
        ValueError: If *events* is empty or timestamps are naive.
    """
    if not events:
        raise ValueError("cannot build a BehaviorProfile from zero events")
    if any(event.posted_at.tzinfo is None for event in events):
        raise ValueError("event timestamps must be timezone-aware")

    ordered = sorted(events, key=lambda event: (event.posted_at, event.event_id))
    hours = [0.0] * HOURS_PER_DAY
    days = [0.0] * DAYS_PER_WEEK
    topic_counts: dict[str, float] = {}
    platform_counts: dict[str, float] = {}
    gaps: list[float] = []
    latencies: list[float] = []
    counterparties: set[str] = set()

    for event in ordered:
        hours[event.posted_at.hour] += 1.0
        days[event.posted_at.weekday()] += 1.0
        topic = assign_topic(event.text, topic_vocabulary)
        topic_counts[topic] = topic_counts.get(topic, 0.0) + 1.0
        platform_counts[event.platform] = platform_counts.get(event.platform, 0.0) + 1.0
        if event.parent_author_id is not None:
            counterparties.add(event.parent_author_id)
            if event.parent_posted_at is not None:
                latency = (event.posted_at - event.parent_posted_at).total_seconds()
                if latency >= 0.0:
                    latencies.append(latency)

    for previous, current in zip(ordered, ordered[1:], strict=False):
        gap = (current.posted_at - previous.posted_at).total_seconds()
        if gap >= 0.0:
            gaps.append(gap)

    if context_events is not None:
        authors = {event.author_id for event in ordered}
        for event in context_events:
            if event.author_id in authors:
                continue  # our own post — already counted above
            if event.parent_author_id is not None and event.parent_author_id in authors:
                counterparties.add(event.author_id)  # an inbound replier

    window_start = ordered[0].posted_at
    window_end = ordered[-1].posted_at
    span_days = max((window_end - window_start).total_seconds() / 86400.0, _MIN_WINDOW_DAYS)

    inter_arrival = _inter_arrival_distribution(gaps)
    burstiness = _burstiness(gaps)

    return BehaviorProfile(
        profile_id=profile_id,
        window_start=window_start,
        window_end=window_end,
        event_count=len(ordered),
        hour_of_day=_normalized(hours),
        day_of_week=_normalized(days),
        posting_rate=len(ordered) / span_days,
        burstiness=burstiness,
        inter_arrival_distribution=inter_arrival,
        response_latency_mean=_mean(latencies),
        topic_labels=tuple(sorted(topic_counts)),
        topic_distribution=_normalized([topic_counts[key] for key in sorted(topic_counts)]),
        platform_labels=tuple(sorted(platform_counts)),
        platform_distribution=_normalized(
            [platform_counts[key] for key in sorted(platform_counts)]
        ),
        interaction_degree=float(len(counterparties)),
    )


def _inter_arrival_distribution(gaps: Sequence[float]) -> tuple[float, ...]:
    counts = [0.0] * (len(INTER_ARRIVAL_BIN_EDGES) + 1)
    for gap in gaps:
        for index, edge in enumerate(INTER_ARRIVAL_BIN_EDGES):
            if gap < edge:
                counts[index] += 1.0
                break
        else:
            counts[-1] += 1.0
    return _normalized(counts)


def _burstiness(gaps: Sequence[float]) -> float:
    """CV-based burstiness ``(sigma - mu) / (sigma + mu)`` in ``[-1, 1]``.

    Regular schedules have ``sigma < mu`` (negative), bursty schedules
    have ``sigma > mu`` (positive). Fewer than two gaps yield 0.0
    (undefined, reported as neutral).
    """
    if len(gaps) < 2:
        return 0.0
    mean = _mean(gaps)
    spread = _std(gaps)
    if mean + spread == 0.0:
        return 0.0
    return (spread - mean) / (spread + mean)
