"""Numeric change-point algorithms (Phase 15).

Plan: *"Start with CUSUM, distribution distance, ruptures/change-point
algorithms."*  All three families are implemented here in pure,
dependency-free Python — the project takes no new runtime
dependencies, so ``ruptures``-style recursive binary segmentation is
reimplemented (mean-shift cost) rather than imported.  The
segmentation walk runs on an explicit work stack instead of Python
recursion, so arbitrarily long series cannot exhaust the call stack.

Every function is deterministic and pure: same input, same output,
on any machine.  All raise ``ValueError`` on invalid parameters or
non-finite inputs so a poisoned series fails loudly instead of
silently producing change points.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence


def _validate_values(values: Sequence[float], *, name: str, minimum: int) -> None:
    if len(values) < minimum:
        raise ValueError(f"{name} needs at least {minimum} values, got {len(values)}")
    for value in values:
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a non-finite value: {value!r}")


def cusum(
    values: Sequence[float],
    *,
    drift: float,
    threshold: float,
    reference: float | None = None,
) -> tuple[tuple[int, float], ...]:
    """Two-sided CUSUM alarms over ``values``.

    ``reference`` is the baseline level the accumulators measure
    against.  ``None`` (the default) uses the series mean — the classic
    mean-referenced CUSUM, byte-identical to previous behaviour.  Pass
    an explicit finite level when the analyst knows the baseline a
    priori (e.g. a documented normal cadence): alarms then reflect
    deviation from that known level rather than from the sample mean.

    Returns ``(index, signed_score)`` tuples: positive scores mean an
    upward shift (cumulative excess above ``reference + drift`` crossed
    ``threshold``), negative scores a downward shift.  Both accumulators
    reset after each alarm so one long regime shift yields one alarm.
    Indices are the alarm points — the shift itself happened somewhere
    in the run leading up to them.
    """
    _validate_values(values, name="cusum values", minimum=2)
    if not math.isfinite(drift) or drift <= 0.0:
        raise ValueError("drift must be finite and > 0")
    if not math.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("threshold must be finite and > 0")
    if reference is not None and not math.isfinite(reference):
        raise ValueError("reference must be finite")

    baseline = sum(values) / len(values) if reference is None else reference
    above = 0.0
    below = 0.0
    alarms: list[tuple[int, float]] = []
    for index, value in enumerate(values):
        above = max(0.0, above + (value - baseline - drift))
        below = max(0.0, below + (baseline - value - drift))
        if above > threshold:
            alarms.append((index, above))
            above = 0.0
            below = 0.0
        elif below > threshold:
            alarms.append((index, -below))
            above = 0.0
            below = 0.0
    return tuple(alarms)


def ks_distance(left: Sequence[float], right: Sequence[float]) -> float:
    """Exact two-sample Kolmogorov–Smirnov statistic in ``[0, 1]``.

    ``sup_t |F_left(t) - F_right(t)|`` over the empirical CDFs; ties
    advance both pointers together so the statistic is exact (never
    an overestimate from partial tie jumps).
    """
    _validate_values(left, name="left sample", minimum=1)
    _validate_values(right, name="right sample", minimum=1)
    first = sorted(left)
    second = sorted(right)
    i = j = 0
    distance = 0.0
    while i < len(first) and j < len(second):
        if first[i] < second[j]:
            i += 1
        elif second[j] < first[i]:
            j += 1
        else:
            tie = first[i]
            while i < len(first) and first[i] == tie:
                i += 1
            while j < len(second) and second[j] == tie:
                j += 1
        distance = max(distance, abs(i / len(first) - j / len(second)))
    return distance


#: Gain function for mean-shift segmentation: between-segment L2 gain
#: of the split (the cost reduction a binary segmentation step buys).
def mean_shift_gain(left: Sequence[float], right: Sequence[float]) -> float:
    """Between-segment variance gain of splitting ``left | right``."""
    if not left or not right:
        return 0.0
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    count_left = len(left)
    count_right = len(right)
    return (count_left * count_right / (count_left + count_right)) * (mean_left - mean_right) ** 2


#: Gain function using the KS distribution distance of the split.
def ks_gain(left: Sequence[float], right: Sequence[float]) -> float:
    """Distribution-distance gain of splitting ``left | right`` (KS)."""
    return ks_distance(left, right)


def segment(
    values: Sequence[float],
    *,
    gain: Callable[[Sequence[float], Sequence[float]], float],
    min_size: int,
    min_gain: float,
) -> tuple[tuple[int, float], ...]:
    """Binary segmentation (``ruptures``-style) by gain, iteratively.

    Greedy two-pass: the best split of a segment is the cut maximizing
    ``gain`` (subject to ``min_size`` on both sides); the segment is
    split there whenever the gain exceeds ``min_gain``, then each half
    is considered in turn.  The recursion is expressed as an explicit
    stack of index-ranges so long series cannot hit Python's recursion
    depth limit (each work item is one segment ``(start, stop)`` range
    pushed and popped, never a call frame).  Returns ``(index, gain)``
    with ``index`` = first position of the right segment, sorted by
    index.  Deterministic: strict improvement required, first cut wins
    ties — and byte-identical to the earlier recursive form, since the
    splits found depend only on the segments themselves and the result
    is sorted.
    """
    _validate_values(values, name="segment values", minimum=2)
    if min_size < 1:
        raise ValueError("min_size must be >= 1")
    if not math.isfinite(min_gain) or min_gain < 0.0:
        raise ValueError("min_gain must be finite and >= 0")

    splits: list[tuple[int, float]] = []
    stack: list[list[int]] = [list(range(len(values)))]
    while stack:
        indices = stack.pop()
        if len(indices) < 2 * min_size:
            continue
        best_cut: int | None = None
        best_gain = min_gain
        for cut in range(min_size, len(indices) - min_size + 1):
            left = [values[global_index] for global_index in indices[:cut]]
            right = [values[global_index] for global_index in indices[cut:]]
            candidate_gain = gain(left, right)
            if candidate_gain > best_gain:
                best_gain = candidate_gain
                best_cut = cut
        if best_cut is None:
            continue
        splits.append((indices[best_cut], best_gain))
        stack.append(indices[:best_cut])
        stack.append(indices[best_cut:])
    return tuple(sorted(splits))
