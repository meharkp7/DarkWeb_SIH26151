"""Server-side scoring for persona linkage proposals.

This module is an adapter, not a model. Every score it returns is the return
value of a function that already exists in :mod:`aegis.stylometry` or
:mod:`aegis.behavior`:

* ``stylometry`` -> :func:`aegis.stylometry.features.stylometric_similarity`
  over :class:`~aegis.stylometry.features.StylometricFeatures` measured on the
  two supplied text samples.
* ``behavioural`` -> :func:`aegis.behavior.similarity.compare_profiles` over two
  profiles built by :func:`aegis.behavior.profile.build_behavior_profile` from
  the two supplied event samples.

It deliberately does **not** do either of the two things that would turn the
record into a fiction:

1. It defines no similarity of its own. Where a per-feature number is needed to
   split the evidence into aligned / apart / contested, it uses the *same*
   per-feature expression :func:`stylometric_similarity` averages over, so the
   14 terms decompose the real score exactly rather than approximating it
   (``tests/test_api_personas.py`` asserts the mean equals the score).
2. It does not apply
   :class:`aegis.stylometry.verification.VerificationModel`. Training one needs
   labelled (features, same-author?) pairs, which the platform does not hold at
   request time. The record therefore carries that model's *inputs*
   (:func:`~aegis.stylometry.verification.PairFeatureExtractor`) with an
   explicit note, rather than a probability that no model produced.

The three-way split
-------------------
A feature is **aligned** only when it was measured on both sides and the two
values agree closely; **apart** only when they disagree clearly. Everything
else is **contested**, which covers three situations that must not be counted as
agreement:

* a feature that is zero on one side (a digit rate in prose with no digits) —
  the similarity function scores two zeros as perfect agreement, and that is
  absence of evidence rather than evidence of sameness;
* a feature measured inside the noise band between "agrees" and "disagrees",
  where claiming either side would overstate the comparison;
* a raw document-length count, which two texts of the same size agree on
  without sharing any writing habit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from aegis.behavior.profile import BehaviorProfile, PostingEvent, build_behavior_profile
from aegis.behavior.similarity import compare_profiles
from aegis.stylometry.features import FEATURE_NAMES as STYLOMETRIC_FEATURE_NAMES
from aegis.stylometry.features import StylometricFeatures, stylometric_similarity
from aegis.stylometry.ngrams import tokenize_words
from aegis.stylometry.verification import FEATURE_NAMES as VERIFIER_FEATURE_NAMES
from aegis.stylometry.verification import PairFeatureExtractor

#: At or above this agreement a feature is counted as agreeing; at or below
#: :data:`_APART_AT` it is counted as disagreeing. The band between the two is
#: contested, because naming a feature "aligned" on a 0.75 agreement would be a
#: claim the measurement does not support.
_ALIGNED_AT = 0.90
_APART_AT = 0.60

#: The column CHECK allows five methods; only these two can be scored from a
#: supplied sample by the functions this module is allowed to call.
SCORABLE_METHODS: tuple[str, ...] = ("stylometry", "behavioural")

#: Methods that exist on the row but cannot be scored here. Refused with a
#: message saying why, rather than scored with a substitute.
UNSCORABLE_METHODS: tuple[str, ...] = ("infrastructure", "attribution", "manual")

#: Minimum words per side for a stylometry proposal. Function-word density and
#: punctuation ratios are unstable on a handful of words, and the features
#: module is happy to return zeros for an empty string — which would score a
#: perfect 1.0 against another empty string. Refusing is the only honest answer.
MIN_STYLOMETRY_WORDS = 120

#: Minimum events per side for a behavioural proposal, and the minimum number of
#: distinct days they must span: an hour-of-day histogram built from three posts
#: in one hour is three bars, not a rhythm.
MIN_BEHAVIOUR_EVENTS = 8
MIN_BEHAVIOUR_DAYS = 3

#: Raw counts of characters, words and sentences. Real measurements, but two
#: texts of the same length agree on them without sharing a writing habit, so
#: they are never reported as aligned.
_LENGTH_FEATURES: frozenset[str] = frozenset({"char_count", "word_count", "sentence_count"})

STYLOMETRY_SCORER = "aegis.stylometry.features.stylometric_similarity"
BEHAVIOUR_SCORER = "aegis.behavior.similarity.compare_profiles"


class SampleTooShort(ValueError):
    """A supplied sample is too small for the requested analysis.

    Raised rather than scored: a number computed from a dozen words would sit in
    a column an analyst later reads as the model's output.
    """


class MethodNotScorable(ValueError):
    """The method cannot be computed from a text or behaviour sample."""


@dataclass(frozen=True)
class ScoreResult:
    """What the scorer computed, and what it could not see.

    ``score`` and the three feature lists travel together into the row: the
    lists are why the number is believable, and the limitations are why it is
    not sufficient on its own.
    """

    method: str
    score: float
    aligned: tuple[str, ...]
    apart: tuple[str, ...]
    contested: tuple[str, ...]
    limitations: tuple[str, ...]
    scorer: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _feature_agreement(left: float, right: float) -> float:
    """The per-feature term that :func:`stylometric_similarity` averages.

    Written out rather than borrowed, so the 14 terms below *are* the score's
    decomposition. The real function is a plain mean of exactly these terms, so
    ``mean(terms) == stylometric_similarity(left, right)``; the test suite pins
    that identity, which is what makes this a decomposition of the platform's
    scorer rather than a second scorer.
    """
    if left == 0.0 and right == 0.0:
        return 1.0
    return 1.0 - abs(left - right) / (abs(left) + right)


def _classify(
    agreements: Mapping[str, float],
    measured: Mapping[str, tuple[float, float]],
    *,
    always_contested: Iterable[str] = (),
) -> tuple[list[str], list[str], list[str]]:
    """Split named features into aligned / apart / contested.

    A feature lands in ``aligned`` only when it was measured on both sides and
    the two values agree; only in ``apart`` when they clearly do not. Anything
    unmeasured, degenerate or ambiguous stays contested, so the count of
    "aligned" features can never be inflated by a feature nobody measured.
    """
    forced = frozenset(always_contested)
    aligned: list[str] = []
    apart: list[str] = []
    contested: list[str] = []
    for name, agreement in agreements.items():
        left, right = measured.get(name, (0.0, 0.0))
        if name in forced or left == 0.0 or right == 0.0:
            contested.append(name)
        elif agreement >= _ALIGNED_AT:
            aligned.append(name)
        elif agreement <= _APART_AT:
            apart.append(name)
        else:
            contested.append(name)
    return aligned, apart, contested


def _word_count(text: str) -> int:
    return len(tokenize_words(text))


def _stylometry_limitations(actor_words: int, candidate_words: int) -> list[str]:
    notes = [
        "Stylometry reads only the text each side chose to publish: edits made "
        "after posting, deleted drafts, and anything said in a channel that was "
        "never collected leave no trace in these features.",
        "A translation, a paraphrase, or a deliberate change of register between "
        "the two samples moves these features with no change of author, and this "
        "score cannot tell that apart from a genuine match.",
        f"Both sides are judged on short samples ({actor_words} and {candidate_words} "
        f"words). Function-word density, hapax ratio and word entropy need several "
        f"hundred words before they are stable; below roughly {MIN_STYLOMETRY_WORDS} words "
        "the ratio features are unstable and are reported as contested rather than as "
        "agreement.",
        "Features that are zero on both sides — a digit rate in prose with no "
        "digits, for instance — are counted as perfect agreement by the similarity "
        "function. They are listed under contested here rather than under aligned.",
        "Raw document length, word count and sentence count are never reported as "
        "aligned: two texts of the same size agree on them without sharing any "
        "writing habit.",
        "The eight n-gram, embedding and shingle similarities in this record's "
        "metadata are the inputs a pairwise verifier would take, not its output: no "
        "verifier trained on labelled identity pairs is applied here, so the score "
        "above is the classical stylometric similarity alone. Those inputs are fitted "
        "on the two supplied documents only, which makes two of them degenerate: with "
        "exactly two documents the corpus mean sits halfway between them, so "
        "centered_tfidf_cosine is -1 by construction, and every token is 'distinctive', "
        "so distinctive_token_jaccard is just token_jaccard. Read neither as evidence.",
    ]
    if min(actor_words, candidate_words) < 400:
        notes.append(
            f"The shorter sample is {min(actor_words, candidate_words)} words, under the 400 "
            "words where punctuation and capitalisation habits settle. A high score here "
            "is a prompt to collect more text, not a finding."
        )
    return notes


def score_stylometry(actor_sample: str, candidate_sample: str) -> ScoreResult:
    """Score two text samples with the platform's stylometric similarity.

    Raises:
        SampleTooShort: If either side has fewer than :data:`MIN_STYLOMETRY_WORDS`
            words.
    """
    actor_words = _word_count(actor_sample)
    candidate_words = _word_count(candidate_sample)
    for label, words in (("actor", actor_words), ("candidate", candidate_words)):
        if words < MIN_STYLOMETRY_WORDS:
            raise SampleTooShort(
                f"The {label} text sample has {words} words. Stylometric analysis needs at "
                f"least {MIN_STYLOMETRY_WORDS} words per side before function-word, "
                "punctuation and entropy features are stable, so no score was computed. "
                "Collect more text from this handle and try again."
            )

    left = StylometricFeatures.from_text(actor_sample)
    right = StylometricFeatures.from_text(candidate_sample)
    score = stylometric_similarity(left, right)

    measured = {
        name: (left_value, right_value)
        for name, left_value, right_value in zip(
            STYLOMETRIC_FEATURE_NAMES, left.as_vector(), right.as_vector(), strict=True
        )
    }
    agreements = {name: _feature_agreement(*values) for name, values in measured.items()}
    aligned, apart, contested = _classify(agreements, measured, always_contested=_LENGTH_FEATURES)

    # Real PairFeatureExtractor output, kept as the verifier's input vector and
    # labelled as such. See the module docstring for why no verifier is applied.
    extractor = PairFeatureExtractor()
    extractor.fit([actor_sample, candidate_sample])
    pair_features = dict(
        zip(
            VERIFIER_FEATURE_NAMES,
            extractor.features(actor_sample, candidate_sample).values,
            strict=True,
        )
    )

    return ScoreResult(
        method="stylometry",
        score=round(score, 6),
        aligned=tuple(aligned),
        apart=tuple(apart),
        contested=tuple(contested),
        limitations=tuple(_stylometry_limitations(actor_words, candidate_words)),
        scorer=STYLOMETRY_SCORER,
        metadata={
            "scorer": STYLOMETRY_SCORER,
            "feature_agreement": {name: round(value, 6) for name, value in agreements.items()},
            "actor_words": actor_words,
            "candidate_words": candidate_words,
            "pair_features": {
                "note": (
                    "Inputs to aegis.stylometry.verification.VerificationModel. No trained "
                    "verifier is applied at request time, so these are not the score."
                ),
                "fitted_on_documents": 2,
                "values": {name: round(value, 6) for name, value in pair_features.items()},
            },
        },
    )


def _to_posting_events(events: Sequence[Any], side: str) -> tuple[PostingEvent, ...]:
    """Adapt request events onto :class:`PostingEvent`, checking the clock.

    ``build_behavior_profile`` raises on naive timestamps, which would surface
    as a 500; the check here turns it into a message naming the offending event.
    Every event on one side belongs to that side's identity, so ``author_id``
    is the side label rather than anything parsed out of the event id.
    """
    adapted: list[PostingEvent] = []
    for event in events:
        if event.posted_at.tzinfo is None:
            raise SampleTooShort(
                f"Event '{event.event_id}' has a timestamp without a timezone offset. "
                "Behavioural profiles are built from absolute times, so a naive timestamp "
                "cannot be placed on an hour-of-day histogram."
            )
        adapted.append(
            PostingEvent(
                event_id=event.event_id,
                author_id=side,
                posted_at=event.posted_at,
                platform=event.platform,
                text=event.text,
                parent_author_id=event.parent_author_id,
                parent_posted_at=event.parent_posted_at,
            )
        )
    return tuple(adapted)


def _peak(distribution: Sequence[float]) -> float:
    """Largest bin of a normalised histogram.

    A stand-in for "this distribution was actually observed": cosine on two flat
    histograms is 0.0 and on two identical ones is 1.0, but a side that was
    never observed is all zeros, and that must not reach the aligned list.
    """
    return max(distribution) if distribution else 0.0


def _behaviour_limitations(
    actor_events: int, candidate_events: int, actor_days: int, candidate_days: int
) -> list[str]:
    return [
        "A behavioural profile summarises *when* and *how often* someone posts, not "
        "who they are: two people sharing a schedule, a time zone and a posting tool "
        "are indistinguishable to this analysis.",
        "Inter-arrival gaps are binned to second-scale buckets, so any two regular "
        "posting rhythms land in the same bins. Burstiness and inter-arrival similarity "
        "are weak evidence alone and belong beside the hour-of-day and day-of-week "
        "distributions.",
        "Response latency is measured only where a reply's parent post was supplied. An "
        "unpaired post contributes no latency observation, and two sides with no paired "
        "replies agree perfectly on a feature neither was measured on — which is why it "
        "is reported as contested.",
        f"The profiles were built from {actor_events} and {candidate_events} events "
        f"spanning {actor_days} and {candidate_days} days. Hour-of-day and day-of-week "
        "distributions from a short window are dominated by which hours happened to be "
        "collected.",
        "Platform and topic distributions move with the collection window and the "
        "platforms covered, so two actors who genuinely share a rhythm can look "
        "different when the same sweep covered only one of them.",
    ]


def score_behaviour(actor_events: Sequence[Any], candidate_events: Sequence[Any]) -> ScoreResult:
    """Score two event samples with the platform's profile comparator.

    Raises:
        SampleTooShort: If either side is under :data:`MIN_BEHAVIOUR_EVENTS`
            events, spans fewer than :data:`MIN_BEHAVIOUR_DAYS` distinct days, or
            carries a timestamp without a timezone.
    """
    left_events = _to_posting_events(actor_events, "actor")
    right_events = _to_posting_events(candidate_events, "candidate")

    for label, events in (("actor", left_events), ("candidate", right_events)):
        if len(events) < MIN_BEHAVIOUR_EVENTS:
            raise SampleTooShort(
                f"The {label} behaviour sample has {len(events)} events. Behavioural "
                f"profiling needs at least {MIN_BEHAVIOUR_EVENTS} events per side before "
                "an hour-of-day histogram means anything, so no score was computed."
            )
        days = {event.posted_at.date() for event in events}
        if len(days) < MIN_BEHAVIOUR_DAYS:
            raise SampleTooShort(
                f"The {label} behaviour sample spans {len(days)} distinct "
                f"{'day' if len(days) == 1 else 'days'}. Behavioural profiling needs at "
                f"least {MIN_BEHAVIOUR_DAYS} distinct days per side, so no score was "
                "computed. Collect more activity for this handle and try again."
            )

    left: BehaviorProfile = build_behavior_profile(left_events, profile_id="actor")
    right: BehaviorProfile = build_behavior_profile(right_events, profile_id="candidate")
    similarity = compare_profiles(left, right)
    components = similarity.components()

    # Only the features whose *measurement* can be absent are checked for
    # degeneracy. The distribution features cannot be empty — a profile built
    # from events always has an hour and a day histogram — so their peak is
    # only a guard against a flat all-zero distribution.
    measured: dict[str, tuple[float, float]] = {
        "hour": (_peak(left.hour_of_day), _peak(right.hour_of_day)),
        "day": (_peak(left.day_of_week), _peak(right.day_of_week)),
        "inter_arrival": (
            _peak(left.inter_arrival_distribution),
            _peak(right.inter_arrival_distribution),
        ),
        "topic": (_peak(left.topic_distribution), _peak(right.topic_distribution)),
        "platform": (
            _peak(left.platform_distribution),
            _peak(right.platform_distribution),
        ),
        "posting_rate": (left.posting_rate, right.posting_rate),
        "burstiness": (left.burstiness, right.burstiness),
        "interaction": (left.interaction_degree, right.interaction_degree),
        "response_latency": (
            left.response_latency_mean,
            right.response_latency_mean,
        ),
    }
    aligned, apart, contested = _classify(components, measured)

    return ScoreResult(
        method="behavioural",
        score=similarity.overall,
        aligned=tuple(aligned),
        apart=tuple(apart),
        contested=tuple(contested),
        limitations=tuple(
            _behaviour_limitations(
                len(left_events),
                len(right_events),
                len({event.posted_at.date() for event in left_events}),
                len({event.posted_at.date() for event in right_events}),
            )
        ),
        scorer=BEHAVIOUR_SCORER,
        metadata={
            "scorer": BEHAVIOUR_SCORER,
            "feature_agreement": dict(components),
            "actor_events": len(left_events),
            "candidate_events": len(right_events),
            "actor_window_days": round(left.window_days, 4),
            "candidate_window_days": round(right.window_days, 4),
            "actor_response_latency_mean": left.response_latency_mean,
            "candidate_response_latency_mean": right.response_latency_mean,
        },
    )


def score_sample(
    method: str,
    *,
    actor_sample: str = "",
    candidate_sample: str = "",
    actor_events: Sequence[Any] = (),
    candidate_events: Sequence[Any] = (),
) -> ScoreResult:
    """Dispatch to the scorer for *method*.

    Raises:
        MethodNotScorable: For a method no function this platform may call can
            compute, with a message naming the reason.
    """
    if method == "stylometry":
        return score_stylometry(actor_sample, candidate_sample)
    if method == "behavioural":
        return score_behaviour(actor_events, candidate_events)
    raise MethodNotScorable(
        f"'{method}' is a valid method on a linkage row, but this endpoint cannot score "
        f"it. Only {', '.join(SCORABLE_METHODS)} can be computed from a supplied sample, "
        "because those are the only methods backed by a function this platform can call "
        f"({STYLOMETRY_SCORER}, {BEHAVIOUR_SCORER}). Producing a number for the other "
        "methods here would mean inventing a score and storing it under the platform's "
        f"name, so the request is refused. Propose a linkage with {SCORABLE_METHODS[0]} or "
        f"{SCORABLE_METHODS[1]} samples instead."
    )
