"""Tests for Phase 12 behavioral profiling (``aegis.behavior``).

Covers handcrafted :class:`~aegis.behavior.profile.BehaviorProfile`
features, corpus adapters, statistical similarity measures (cosine,
Jensen-Shannon, chi-square, scalar agreement), weighted
:func:`~aegis.behavior.similarity.compare_profiles`, input validation,
and the documented decision to defer sequence models to future work.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from aegis.behavior import (
    DEFAULT_TOPIC_VOCABULARY,
    DEFAULT_WEIGHTS,
    INTER_ARRIVAL_BIN_EDGES,
    INTER_ARRIVAL_BIN_LABELS,
    BehaviorProfile,
    PostingEvent,
    assign_topic,
    build_behavior_profile,
    chi_square_distance,
    compare_profiles,
    cosine_similarity,
    events_from_corpus,
    jensen_shannon,
    scalar_similarity,
)
from aegis.collection.corpus import build_default_corpus

#: Monday 2026-01-05, so weekday() offsets are predictable (0 = Monday).
BASE_DAY = datetime(2026, 1, 5, tzinfo=UTC)


def _at(hour: int, day_offset: int = 0, minute: int = 0) -> datetime:
    return BASE_DAY + timedelta(days=day_offset, hours=hour, minutes=minute)


def _event(
    event_id: str,
    *,
    author: str = "alias-a",
    posted_at: datetime | None = None,
    platform: str = "forum_alpha",
    text: str = "fees update",
    parent_author: str | None = None,
    parent_posted_at: datetime | None = None,
) -> PostingEvent:
    return PostingEvent(
        event_id=event_id,
        author_id=author,
        posted_at=posted_at if posted_at is not None else _at(10),
        platform=platform,
        text=text,
        parent_author_id=parent_author,
        parent_posted_at=parent_posted_at,
    )


def _spread_events(hours: list[int]) -> list[PostingEvent]:
    """One event per listed hour on successive days (evenly spaced 24h)."""
    return [_event(f"e{index}", posted_at=_at(hour, index)) for index, hour in enumerate(hours)]


# --------------------------------------------------------------------------- #
# BehaviorProfile features
# --------------------------------------------------------------------------- #
class TestBehaviorProfile:
    def test_hour_of_day_distribution_is_normalized(self) -> None:
        profile = build_behavior_profile(_spread_events([1, 1, 3, 23]), profile_id="alice")
        assert len(profile.hour_of_day) == 24
        assert profile.hour_of_day[1] == pytest.approx(0.5)
        assert profile.hour_of_day[3] == pytest.approx(0.25)
        assert profile.hour_of_day[23] == pytest.approx(0.25)
        assert sum(profile.hour_of_day) == pytest.approx(1.0)

    def test_day_of_week_distribution(self) -> None:
        # Day offsets 0, 1, 2 from Monday -> Mon, Tue, Wed.
        profile = build_behavior_profile(_spread_events([10, 11, 12]), profile_id="alice")
        assert len(profile.day_of_week) == 7
        assert profile.day_of_week[0] == pytest.approx(1 / 3)  # Monday
        assert profile.day_of_week[1] == pytest.approx(1 / 3)  # Tuesday
        assert profile.day_of_week[2] == pytest.approx(1 / 3)  # Wednesday
        assert sum(profile.day_of_week) == pytest.approx(1.0)

    def test_posting_rate_over_multi_day_span(self) -> None:
        # Three days at the same hour -> span is exactly 2 days.
        profile = build_behavior_profile(_spread_events([1, 1, 1]), profile_id="alice")
        assert profile.event_count == 3
        # Span = 2 days -> 3 events / 2 days.
        assert profile.posting_rate == pytest.approx(1.5)
        assert profile.window_days == pytest.approx(2.0)

    def test_posting_rate_floors_window_at_one_day(self) -> None:
        profile = build_behavior_profile(_spread_events([4]), profile_id="solo")
        assert profile.window_days == pytest.approx(1.0)
        assert profile.posting_rate == pytest.approx(1.0)

    def test_regular_schedule_is_strictly_regular(self) -> None:
        profile = build_behavior_profile(_spread_events([9, 9, 9, 9]), profile_id="steady")
        # Exactly 24h gaps -> zero variance -> CV burstiness of -1.0.
        assert profile.burstiness == pytest.approx(-1.0)

    def test_bursty_schedule_scores_higher_than_regular(self) -> None:
        # Gaps of 1s, 1s, 100s -> sigma > mu -> positive burstiness.
        stamp = datetime(2026, 1, 5, tzinfo=UTC)
        bursty = build_behavior_profile(
            [
                _event("b0", posted_at=stamp),
                _event("b1", posted_at=stamp + timedelta(seconds=1)),
                _event("b2", posted_at=stamp + timedelta(seconds=2)),
                _event("b3", posted_at=stamp + timedelta(seconds=102)),
            ],
            profile_id="bursty",
        )
        assert bursty.burstiness > 0.0
        assert -1.0 <= bursty.burstiness <= 1.0

    def test_single_event_neutral_burstiness_and_no_gaps(self) -> None:
        profile = build_behavior_profile(_spread_events([4]), profile_id="solo")
        assert profile.burstiness == 0.0
        assert sum(profile.inter_arrival_distribution) == pytest.approx(0.0)

    def test_inter_arrival_distribution_bins(self) -> None:
        assert len(INTER_ARRIVAL_BIN_EDGES) + 1 == len(INTER_ARRIVAL_BIN_LABELS)
        # 24h gaps land in the 1-3d bin (index 5).
        daily = build_behavior_profile(_spread_events([1, 2, 3]), profile_id="daily")
        assert daily.inter_arrival_distribution[5] == pytest.approx(1.0)
        # 2-minute gap lands in the <5m bin (index 0).
        stamp = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
        quick = build_behavior_profile(
            [
                _event("q0", posted_at=stamp),
                _event("q1", posted_at=stamp + timedelta(minutes=2)),
            ],
            profile_id="quick",
        )
        assert quick.inter_arrival_distribution[0] == pytest.approx(1.0)
        assert sum(quick.inter_arrival_distribution) == pytest.approx(1.0)

    def test_response_latency_is_mean_of_valid_replies(self) -> None:
        events = [
            _event("p0", posted_at=_at(10)),
            _event(
                "p1",
                posted_at=_at(12),
                parent_author="other",
                parent_posted_at=_at(10),
            ),
            _event(
                "p2",
                posted_at=_at(18),
                parent_author="other",
                parent_posted_at=_at(10),
            ),
            # Negative latency (reply predates parent) must be ignored.
            _event(
                "p3",
                posted_at=_at(9),
                parent_author="other",
                parent_posted_at=_at(10),
            ),
        ]
        profile = build_behavior_profile(events, profile_id="replier")
        # (7200s + 28800s) / 2 = 18000s; the -3600s pair is dropped.
        assert profile.response_latency_mean == pytest.approx(18000.0)

    def test_response_latency_without_parents_is_zero(self) -> None:
        profile = build_behavior_profile(_spread_events([1, 2, 3]), profile_id="lurker")
        assert profile.response_latency_mean == pytest.approx(0.0)

    def test_topic_distribution_and_labels(self) -> None:
        events = [
            _event("t0", text="escrow fees update"),
            _event("t1", text="escrow mirror update"),
            _event("t2", text="nothing relevant here"),
        ]
        profile = build_behavior_profile(events, profile_id="topics")
        assert profile.topic_labels == tuple(sorted(profile.topic_labels))
        topic_map = dict(zip(profile.topic_labels, profile.topic_distribution, strict=True))
        assert topic_map["escrow"] == pytest.approx(2 / 3)
        assert topic_map["general"] == pytest.approx(1 / 3)
        assert sum(profile.topic_distribution) == pytest.approx(1.0)

    def test_platform_distribution(self) -> None:
        events = [
            _event("m0", platform="forum_alpha"),
            _event("m1", platform="forum_alpha"),
            _event("m2", platform="market_beta"),
        ]
        profile = build_behavior_profile(events, profile_id="platforms")
        platform_map = dict(
            zip(profile.platform_labels, profile.platform_distribution, strict=True)
        )
        assert platform_map == pytest.approx({"forum_alpha": 2 / 3, "market_beta": 1 / 3})

    def test_interaction_degree_counts_distinct_outbound_counterparties(
        self,
    ) -> None:
        events = [
            _event("o0", parent_author="bob", parent_posted_at=_at(9)),
            _event("o1", parent_author="carol", parent_posted_at=_at(9)),
            _event("o2", parent_author="bob", parent_posted_at=_at(9)),
        ]
        profile = build_behavior_profile(events, profile_id="outbound")
        assert profile.interaction_degree == pytest.approx(2.0)

    def test_interaction_degree_counts_distinct_inbound_repliers(
        self,
    ) -> None:
        events = [_event("n0"), _event("n1")]
        inbound = [
            _event("r0", author="bob", parent_author="alias-a"),
            _event("r1", author="carol", parent_author="alias-a"),
            # Repeat from bob: same counterparty, not a new one.
            _event("r2", author="bob", parent_author="alias-a"),
            # Our own post in the context stream must not count as a partner.
            _event("r3", author="alias-a", parent_author="alias-a"),
        ]
        profile = build_behavior_profile(events, profile_id="inbound", context_events=inbound)
        assert profile.interaction_degree == pytest.approx(2.0)

    def test_interaction_degree_without_context_sees_only_outbound(
        self,
    ) -> None:
        profile = build_behavior_profile(_spread_events([1, 2]), profile_id="isolated")
        assert profile.interaction_degree == pytest.approx(0.0)

    def test_profile_is_frozen(self) -> None:
        profile = build_behavior_profile(_spread_events([1]), profile_id="p")
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.event_count = 0  # type: ignore[misc]

    def test_empty_events_rejected(self) -> None:
        with pytest.raises(ValueError, match="zero events"):
            build_behavior_profile([], profile_id="nobody")

    def test_naive_timestamps_rejected(self) -> None:
        naive = PostingEvent(
            event_id="e",
            author_id="a",
            posted_at=datetime(2026, 1, 5, 10),
            platform="forum_alpha",
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            build_behavior_profile([naive], profile_id="naive")

    def test_module_docstring_lists_all_nine_plan_features(self) -> None:
        import aegis.behavior.profile as profile_module

        doc = profile_module.__doc__ or ""
        for feature in (
            "hour-of-day",
            "day-of-week",
            "posting rate",
            "burstiness",
            "inter-arrival",
            "response latency",
            "topic distribution",
            "platform distribution",
            "interaction degree",
        ):
            assert feature in doc, f"missing plan feature: {feature}"


# --------------------------------------------------------------------------- #
# Topic assignment
# --------------------------------------------------------------------------- #
class TestAssignTopic:
    def test_first_matching_vocabulary_term_wins(self) -> None:
        assert assign_topic("escrow wallet fees", DEFAULT_TOPIC_VOCABULARY) == "escrow"
        assert assign_topic("A WALLET ESCROW", DEFAULT_TOPIC_VOCABULARY) == "escrow"

    def test_unmatched_text_is_general(self) -> None:
        assert assign_topic("no relevant keywords", DEFAULT_TOPIC_VOCABULARY) == ("general")

    def test_custom_vocabulary(self) -> None:
        assert assign_topic("quantum posting", ("quantum",)) == "quantum"


# --------------------------------------------------------------------------- #
# Corpus adapters
# --------------------------------------------------------------------------- #
class TestCorpusAdapters:
    @pytest.fixture(scope="class")
    def corpus_events(
        self,
    ) -> tuple[object, ...]:
        corpus = build_default_corpus(seed=26151)
        return (corpus, *events_from_corpus(corpus))

    def test_event_count_matches_post_count(self, corpus_events: tuple) -> None:
        corpus, *events = corpus_events
        assert len(events) == len(corpus.posts)  # type: ignore[attr-defined]

    def test_events_sorted_and_timezone_aware(self, corpus_events: tuple) -> None:
        _, *events = corpus_events
        stamps = [event.posted_at for event in events]
        assert all(stamp.tzinfo is not None for stamp in stamps)
        assert stamps == sorted(stamps)

    def test_actor_filter_returns_subset(self) -> None:
        corpus = build_default_corpus(seed=26151)
        everything = events_from_corpus(corpus)
        only_first = events_from_corpus(corpus, actor_id=corpus.actors[0].actor_id)
        assert 0 < len(only_first) < len(everything)
        alias_actor = {alias.alias_id: alias.actor_id for alias in corpus.aliases}
        assert all(
            alias_actor[event.author_id] == corpus.actors[0].actor_id for event in only_first
        )

    def test_profiles_from_corpus_are_deterministic_and_complete(self) -> None:
        corpus = build_default_corpus(seed=26151)
        events = events_from_corpus(corpus)
        alias_actor = {alias.alias_id: alias.actor_id for alias in corpus.aliases}

        def build() -> dict[str, BehaviorProfile]:
            grouped: dict[str, list[PostingEvent]] = {}
            for event in events:
                grouped.setdefault(alias_actor[event.author_id], []).append(event)
            return {
                actor_id: build_behavior_profile(group, profile_id=actor_id)
                for actor_id, group in grouped.items()
            }

        first = build()
        second = build()
        assert first == second  # frozen dataclass equality
        assert set(first) == {actor.actor_id for actor in corpus.actors}
        assert sum(profile.event_count for profile in first.values()) == len(events)
        for profile in first.values():
            assert sum(profile.hour_of_day) == pytest.approx(1.0)
            assert sum(profile.day_of_week) == pytest.approx(1.0)
            assert profile.window_days >= 1.0


# --------------------------------------------------------------------------- #
# Statistical similarity measures
# --------------------------------------------------------------------------- #
class TestSimilarityMeasures:
    def test_cosine_similarity(self) -> None:
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
        assert cosine_similarity([], []) == pytest.approx(0.0)
        assert cosine_similarity([1.0, 0.0], [1.0]) == pytest.approx(0.0)

    def test_jensen_shannon(self) -> None:
        p = (0.5, 0.5)
        assert jensen_shannon(p, p) == pytest.approx(0.0)
        assert jensen_shannon(p, ()) == pytest.approx(1.0)
        assert jensen_shannon((), ()) == pytest.approx(0.0)
        divergence = jensen_shannon(p, (1.0, 0.0))
        assert 0.0 < divergence <= 1.0

    def test_chi_square_distance(self) -> None:
        assert chi_square_distance((0.4, 0.6), (0.4, 0.6)) == pytest.approx(0.0)
        assert chi_square_distance((1.0, 0.0), (0.0, 1.0)) == pytest.approx(1.0)
        assert chi_square_distance((), ()) == pytest.approx(0.0)

    def test_scalar_similarity(self) -> None:
        assert scalar_similarity(0.0, 0.0) == pytest.approx(1.0)
        assert scalar_similarity(5.0, 5.0) == pytest.approx(1.0)
        assert scalar_similarity(0.0, 10.0) == pytest.approx(0.0)
        # 1 - |5-10| / (5+10) = 2/3.
        assert scalar_similarity(5.0, 10.0) == pytest.approx(2 / 3)
        # Opposite-sign equal magnitudes disagree completely.
        assert scalar_similarity(-1.0, 1.0) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# compare_profiles
# --------------------------------------------------------------------------- #
class TestCompareProfiles:
    @pytest.fixture(scope="class")
    def corpus_profiles(self) -> dict[str, BehaviorProfile]:
        corpus = build_default_corpus(seed=26151)
        events = events_from_corpus(corpus)
        alias_actor = {alias.alias_id: alias.actor_id for alias in corpus.aliases}
        grouped: dict[str, list[PostingEvent]] = {}
        for event in events:
            grouped.setdefault(alias_actor[event.author_id], []).append(event)
        return {
            actor_id: build_behavior_profile(group, profile_id=actor_id)
            for actor_id, group in grouped.items()
        }

    def test_identity_is_perfect(self) -> None:
        profile = build_behavior_profile(_spread_events([1, 2, 3]), profile_id="a")
        comparison = compare_profiles(profile, profile)
        assert comparison.overall == pytest.approx(1.0)
        assert all(value == pytest.approx(1.0) for value in comparison.components().values())

    def test_identity_holds_on_corpus_profiles(
        self, corpus_profiles: dict[str, BehaviorProfile]
    ) -> None:
        profile = next(iter(corpus_profiles.values()))
        assert compare_profiles(profile, profile).overall == pytest.approx(1.0)

    def test_is_deterministic(self) -> None:
        left = build_behavior_profile(_spread_events([1, 2, 3]), profile_id="a")
        right = build_behavior_profile(_spread_events([4, 5, 6]), profile_id="b")
        first = compare_profiles(left, right)
        second = compare_profiles(left, right)
        assert first == second

    def test_reverse_order_is_symmetric(self, corpus_profiles: dict[str, BehaviorProfile]) -> None:
        profiles = sorted(corpus_profiles, key=str)
        left, right = (
            corpus_profiles[profiles[0]],
            corpus_profiles[profiles[1]],
        )
        assert compare_profiles(left, right).overall == pytest.approx(
            compare_profiles(right, left).overall
        )

    def test_distinct_actors_score_below_one(
        self, corpus_profiles: dict[str, BehaviorProfile]
    ) -> None:
        profiles = list(corpus_profiles.values())
        scores = [
            compare_profiles(profiles[i], profiles[j]).overall
            for i in range(10)
            for j in range(i + 1, 10)
        ]
        assert all(0.0 <= score <= 1.0 for score in scores)
        assert max(scores) < 1.0

    def test_weight_overlay_replaces_selected_components(self) -> None:
        left = build_behavior_profile(_spread_events([1, 2, 3]), profile_id="a")
        right = build_behavior_profile(_spread_events([4, 5, 6]), profile_id="b")
        full = compare_profiles(left, right)
        hours_only = compare_profiles(
            left,
            right,
            weights={name: 0.0 for name in DEFAULT_WEIGHTS if name != "hour"},
        )
        assert hours_only.overall == pytest.approx(full.hour, abs=1e-5)
        assert hours_only.overall != pytest.approx(full.overall)

    def test_unknown_weight_key_rejected(self) -> None:
        left = build_behavior_profile(_spread_events([1]), profile_id="a")
        right = build_behavior_profile(_spread_events([2]), profile_id="b")
        with pytest.raises(ValueError, match="unknown components"):
            compare_profiles(left, right, weights={"nonsense": 1.0})

    def test_non_positive_weight_sum_rejected(self) -> None:
        left = build_behavior_profile(_spread_events([1]), profile_id="a")
        right = build_behavior_profile(_spread_events([2]), profile_id="b")
        with pytest.raises(ValueError, match="positive"):
            compare_profiles(left, right, weights={name: -1.0 for name in DEFAULT_WEIGHTS})

    def test_default_weights_shape(self) -> None:
        components = {
            "hour",
            "day",
            "inter_arrival",
            "topic",
            "platform",
            "response_latency",
            "posting_rate",
            "burstiness",
            "interaction",
        }
        assert set(DEFAULT_WEIGHTS) == components
        assert DEFAULT_WEIGHTS["hour"] == 1.5
        assert all(weight >= 0.0 for weight in DEFAULT_WEIGHTS.values())

    def test_components_covers_all_weights(
        self, corpus_profiles: dict[str, BehaviorProfile]
    ) -> None:
        profiles = sorted(corpus_profiles.values(), key=lambda p: p.profile_id)
        breakdown = compare_profiles(profiles[0], profiles[1]).components()
        assert set(breakdown) == set(DEFAULT_WEIGHTS)
        assert all(0.0 <= value <= 1.0 for value in breakdown.values())


# --------------------------------------------------------------------------- #
# Deferred sequence models (plan section 13)
# --------------------------------------------------------------------------- #
class TestDeferredSequenceModels:
    def test_sequence_models_documented_as_future_work(self) -> None:
        """Plan: add sequence models only after baseline is understood."""
        import aegis.behavior.similarity as similarity_module

        doc = similarity_module.__doc__ or ""
        assert "future work" in doc.lower()
        assert "sequence models" in doc.lower()
        assert "planned future work" in doc.lower()
        assert "baseline" in doc.lower()

    def test_compare_profiles_documents_the_deferral(self) -> None:
        from aegis.behavior.similarity import compare_profiles as comparator

        doc = comparator.__doc__ or ""
        assert "future work" in doc.lower()
        assert "deferred" in doc.lower()
