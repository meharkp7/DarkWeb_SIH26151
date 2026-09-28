"""Parity tests for the canonical metrics shared by resolution and stylometry.

Review finding B1: ``aegis.resolution.metrics`` and
``aegis.stylometry.evaluation`` used to carry two divergent
implementations of ``average_precision`` / ``best_f1_threshold`` with
*swapped* argument orders and disagreeing tie-breaks.  Stylometry now
delegates to the canonical resolution implementation, so these tests
pin the properties that make that single source of truth real:

* identical results through both public entry points (exact equality),
* the unified highest-threshold tie-break on a fixture where the old
  stylometry rule ("closest to 0.5") would have chosen differently,
* argument-order / domain guards (a swapped call must raise, not
  silently compute garbage),
* the 3-decimal rounding in stylometry's ``ClassificationMetrics`` is
  presentation-only and still agrees with the canonical unrounded AP.
"""

from __future__ import annotations

import math

import pytest

from aegis.resolution.metrics import (
    average_precision as resolution_average_precision,
)
from aegis.resolution.metrics import (
    best_f1_threshold as resolution_best_f1_threshold,
)
from aegis.stylometry.evaluation import (
    ClassificationMetrics,
)
from aegis.stylometry.evaluation import (
    average_precision as stylometry_average_precision,
)
from aegis.stylometry.evaluation import (
    best_f1_threshold as stylometry_best_f1_threshold,
)

# Shared fixtures: plain, tie-heavy, and degenerate inputs used against
# both entry points.
PLAIN_SCORES = [0.9, 0.6, 0.4, 0.2]
PLAIN_LABELS = [1, 1, 0, 0]
TIED_SCORES = [0.5, 0.5, 0.4, 0.4, 0.3, 0.2]
TIED_LABELS = [1, 0, 1, 0, 1, 0]
NO_POSITIVE_SCORES = [0.7, 0.7, 0.1]
NO_POSITIVE_LABELS = [0, 0, 0]

#: F1 = 2/3 both at threshold 0.9 (TP=1, FP=0, FN=1) and at 0.6
#: (TP=2, FP=2, FN=0); 0.7 and 0.8 score lower.  The canonical tie-break
#: must keep the highest tied threshold (0.9); the old stylometry rule
#: ("closest to 0.5") would have picked 0.6, so this fixture proves the
#: unification is in force on *both* entry points.
TIE_BREAK_SCORES = [0.9, 0.8, 0.7, 0.6]
TIE_BREAK_LABELS = [1, 0, 0, 1]


def test_average_precision_identical_on_both_entry_points() -> None:
    for scores, labels in (
        (PLAIN_SCORES, PLAIN_LABELS),
        (TIED_SCORES, TIED_LABELS),
        (NO_POSITIVE_SCORES, NO_POSITIVE_LABELS),
        ([0.5], [1]),
    ):
        canonical = resolution_average_precision(scores, labels)
        delegated = stylometry_average_precision(scores, labels)
        assert delegated == canonical  # exact, zero tolerance


def test_best_f1_threshold_identical_on_both_entry_points() -> None:
    for scores, labels in (
        (PLAIN_SCORES, PLAIN_LABELS),
        (TIED_SCORES, TIED_LABELS),
        (NO_POSITIVE_SCORES, NO_POSITIVE_LABELS),
        ([0.5], [1]),
    ):
        canonical = resolution_best_f1_threshold(scores, labels)
        delegated = stylometry_best_f1_threshold(scores, labels)
        assert delegated == canonical  # exact same cutoff


def test_ties_resolve_to_highest_threshold_on_both_entry_points() -> None:
    assert resolution_best_f1_threshold(TIE_BREAK_SCORES, TIE_BREAK_LABELS) == 0.9
    assert stylometry_best_f1_threshold(TIE_BREAK_SCORES, TIE_BREAK_LABELS) == 0.9
    # the tied loser under "closest to 0.5" is explicitly *not* chosen
    assert resolution_best_f1_threshold(TIE_BREAK_SCORES, TIE_BREAK_LABELS) != 0.6


def test_no_positives_returns_highest_score() -> None:
    assert resolution_best_f1_threshold(NO_POSITIVE_SCORES, NO_POSITIVE_LABELS) == 0.7
    assert stylometry_best_f1_threshold(NO_POSITIVE_SCORES, NO_POSITIVE_LABELS) == 0.7
    assert resolution_average_precision(NO_POSITIVE_SCORES, NO_POSITIVE_LABELS) == 0.0
    assert stylometry_average_precision(NO_POSITIVE_SCORES, NO_POSITIVE_LABELS) == 0.0


# ---------------------------------------------------------------------------
# guards: a swapped (labels, scores) call must raise, not compute garbage
# ---------------------------------------------------------------------------


def test_swapped_arguments_raise_value_error() -> None:
    # float scores land in the labels slot -> label-domain guard fires
    with pytest.raises(ValueError, match="labels must be 0 or 1"):
        resolution_average_precision([1, 1, 0, 0], [0.9, 0.6, 0.55, 0.1])
    with pytest.raises(ValueError, match="labels must be 0 or 1"):
        stylometry_average_precision([1, 1, 0, 0], [0.9, 0.6, 0.55, 0.1])
    with pytest.raises(ValueError, match="labels must be 0 or 1"):
        resolution_best_f1_threshold([1, 1, 0, 0], [0.9, 0.6, 0.55, 0.1])
    with pytest.raises(ValueError, match="labels must be 0 or 1"):
        stylometry_best_f1_threshold([1, 1, 0, 0], [0.9, 0.6, 0.55, 0.1])


def test_non_finite_scores_raise_value_error() -> None:
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="finite"):
            resolution_average_precision([bad, 0.5], [1, 0])
        with pytest.raises(ValueError, match="finite"):
            stylometry_best_f1_threshold([bad, 0.5], [1, 0])


def test_out_of_range_score_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"within \[0.0, 1.0\]"):
        resolution_average_precision([1.5, 0.5], [1, 0])
    with pytest.raises(ValueError, match=r"within \[0.0, 1.0\]"):
        stylometry_best_f1_threshold([-0.1, 0.5], [1, 0])


def test_out_of_domain_label_raises_value_error() -> None:
    with pytest.raises(ValueError, match="labels must be 0 or 1"):
        resolution_best_f1_threshold([0.5, 0.4], [2, 0])
    with pytest.raises(ValueError, match="labels must be 0 or 1"):
        stylometry_average_precision([0.5, 0.4], [2, 0])


def test_misaligned_inputs_raise_align_error() -> None:
    with pytest.raises(ValueError, match="align"):
        resolution_average_precision([0.5], [1, 0])
    with pytest.raises(ValueError, match="align"):
        stylometry_average_precision([0.5], [1, 0])


# ---------------------------------------------------------------------------
# rounding parity: stylometry's 3dp rounding is presentation-only
# ---------------------------------------------------------------------------


def test_stylometry_pr_auc_equals_rounded_canonical_ap() -> None:
    for scores, labels in (
        (PLAIN_SCORES, PLAIN_LABELS),
        (TIED_SCORES, TIED_LABELS),
        ([0.9, 0.2, 0.4, 0.8], [1, 0, 1, 0]),
    ):
        stylometry = ClassificationMetrics.from_scores(labels, scores, threshold=0.5)
        canonical = resolution_average_precision(scores, labels)
        assert stylometry.pr_auc == round(canonical, 3)
