"""Channel signals and declared weights for the Phase 16 attribution baseline.

The plan freezes a transparent formula for the baseline attribution score:

.. math::

    S = \\sigma(w_h S_h + w_p S_p + w_w S_w + w_t S_t + w_b S_b + w_i S_i)

Each :class:`ChannelSignals` field is one ``S_x`` term and each
:class:`ChannelWeights` field is its ``w_x``.  Keeping the six terms as
typed, validated dataclasses (rather than a bare ``dict`` or a positional
tuple) means a caller cannot swap two channels without a test noticing,
and it gives the analyst-facing ``signals`` mapping
(``{"S_h": ..., "S_p": ...}``) a single source of truth.

Design rules that the rest of the package relies on:

* every signal is a finite float in ``[0, 1]`` — *rejected*, not clamped,
  when out of range, because a silently-clamped signal hides a broken
  feature extractor;
* weights are declared, non-negative and **normalized to sum to 1**, so
  the logit scale of the formula is fixed and comparable across runs
  (sharpening is calibration's job — Phase 18 — not a weight tweak's);
* nothing reads the wall clock or ambient randomness: scoring is a pure
  function of its inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class Channel(StrEnum):
    """The six attribution channels named by the plan formula.

    Each channel maps to one ``S_x`` term; see :data:`CHANNEL_SYMBOLS`
    (h = handle, p = PGP, w = wallet, t = temporal, b = behavior,
    i = infrastructure).
    """

    HANDLE = "handle"
    PGP = "pgp"
    WALLET = "wallet"
    TEMPORAL = "temporal"
    BEHAVIOR = "behavior"
    INFRASTRUCTURE = "infrastructure"


#: Formula symbol for each channel — the keys of the analyst-facing
#: ``signals`` mapping documented on
#: :class:`aegis.schemas.hypothesis.AttributionAssessment`.
CHANNEL_SYMBOLS: dict[Channel, str] = {
    Channel.HANDLE: "S_h",
    Channel.PGP: "S_p",
    Channel.WALLET: "S_w",
    Channel.TEMPORAL: "S_t",
    Channel.BEHAVIOR: "S_b",
    Channel.INFRASTRUCTURE: "S_i",
}

#: Field order shared by :class:`ChannelSignals` and :class:`ChannelWeights`,
#: and therefore by every feature vector fed to the learned baselines.
CHANNEL_FIELD_ORDER: tuple[str, ...] = (
    "handle",
    "pgp",
    "wallet",
    "temporal",
    "behavior",
    "infrastructure",
)

#: Tolerance for "sums to 1" checks on declared weights.
WEIGHT_SUM_TOLERANCE = 1e-9


def _require_unit_interval(value: float, field_name: str) -> float:
    """Return ``value`` if it is a finite float in ``[0, 1]``."""
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be finite and within [0.0, 1.0], got {value!r}")
    return value


def _require_normalized(weights: dict[str, float]) -> None:
    """Reject negative or unnormalized declared weights loudly.

    The project rule is that weights are declared and validated — a
    caller who renormalizes by hand, forgets a term, or passes a
    negative gets a ``ValueError`` instead of a plausible-looking score
    whose logit scale silently drifted.
    """
    for name, value in weights.items():
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"weight {name} must be finite and non-negative, got {value!r}")
    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"channel weights must be normalized to sum to 1.0, got {total!r} (weights={weights!r})"
        )


def sigmoid(value: float) -> float:
    """Numerically stable logistic function mapping a logit to ``(0, 1)``."""
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


@dataclass(frozen=True)
class ChannelSignals:
    """The six ``S_x`` channel terms for one candidate pair, each in ``[0, 1]``.

    A channel that was not observed must be supplied as ``0.0`` — the
    documented "no signal" value — rather than a neutral ``0.5``, so an
    unobserved channel can never inflate an attribution score.
    """

    handle: float
    pgp: float
    wallet: float
    temporal: float
    behavior: float
    infrastructure: float

    def __post_init__(self) -> None:
        for name in CHANNEL_FIELD_ORDER:
            _require_unit_interval(getattr(self, name), f"signal {name!r}")

    @classmethod
    def zeros(cls) -> ChannelSignals:
        """The all-unobserved signal vector (every channel contributes nothing)."""
        return cls(
            handle=0.0,
            pgp=0.0,
            wallet=0.0,
            temporal=0.0,
            behavior=0.0,
            infrastructure=0.0,
        )

    @classmethod
    def from_mapping(cls, values: dict[Channel, float]) -> ChannelSignals:
        """Build signals from a ``Channel -> value`` mapping (missing channel = 0.0).

        Raises:
            ValueError: If a key is not a :class:`Channel` or a value is
                outside ``[0, 1]``.
        """
        unknown = [key for key in values if not isinstance(key, Channel)]
        if unknown:
            raise ValueError(f"unknown channels: {unknown!r}; expected Channel members")
        return cls(
            handle=values.get(Channel.HANDLE, 0.0),
            pgp=values.get(Channel.PGP, 0.0),
            wallet=values.get(Channel.WALLET, 0.0),
            temporal=values.get(Channel.TEMPORAL, 0.0),
            behavior=values.get(Channel.BEHAVIOR, 0.0),
            infrastructure=values.get(Channel.INFRASTRUCTURE, 0.0),
        )

    def as_vector(self) -> tuple[float, ...]:
        """Feature vector in :data:`CHANNEL_FIELD_ORDER` order (what models consume)."""
        return tuple(getattr(self, name) for name in CHANNEL_FIELD_ORDER)

    def as_dict(self) -> dict[str, float]:
        """Plan notation mapping (``{"S_h": ..., ...}``) for reports and the API."""
        return {
            CHANNEL_SYMBOLS[channel]: getattr(self, CHANNEL_FIELD_ORDER[index])
            for index, channel in enumerate(Channel)
        }


@dataclass(frozen=True)
class ChannelWeights:
    """Declared weights ``w_h, w_p, w_w, w_t, w_b, w_i`` of the plan formula.

    Validated on construction: every weight must be finite, non-negative
    and the six must sum to 1.0 (within :data:`WEIGHT_SUM_TOLERANCE`).
    """

    handle: float
    pgp: float
    wallet: float
    temporal: float
    behavior: float
    infrastructure: float

    def __post_init__(self) -> None:
        _require_normalized({name: getattr(self, name) for name in CHANNEL_FIELD_ORDER})

    def as_vector(self) -> tuple[float, ...]:
        """Weight vector in :data:`CHANNEL_FIELD_ORDER` order."""
        return tuple(getattr(self, name) for name in CHANNEL_FIELD_ORDER)


#: Frozen default of the Phase 16 formula.
#:
#: The three hard-identifier channels (handle, PGP, wallet) carry 65 % of
#: the mass because they are shared secrets an adversary must reuse;
#: temporal consistency is medium-strength corroboration; behavior and
#: infrastructure are the easiest channels to spoof, so they get the
#: smallest declared share.
DEFAULT_CHANNEL_WEIGHTS = ChannelWeights(
    handle=0.25,
    pgp=0.20,
    wallet=0.20,
    temporal=0.15,
    behavior=0.10,
    infrastructure=0.10,
)


def weighted_logit(signals: ChannelSignals, weights: ChannelWeights) -> float:
    """The plan's linear term ``w_h S_h + ... + w_i S_i`` before the sigmoid."""
    return sum(
        weight * signal
        for weight, signal in zip(weights.as_vector(), signals.as_vector(), strict=True)
    )
