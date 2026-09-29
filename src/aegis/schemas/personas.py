"""Request/response schemas for the persona linkage surface.

The separation this file exists to protect: ``score`` is the model's output and
``status`` is an analyst's decision. They are different columns in
``persona_linkages`` and they are different fields here, so no consumer can
collapse a hypothesis into a finding by reading one instead of the other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: `proposed` / `confirmed` / `rejected` — the `ck_persona_linkage_status`
#: CHECK constraint, restated so an OpenAPI client sees the same three values.
PersonaLinkageStatus = Literal["proposed", "confirmed", "rejected"]

#: Only the two methods this endpoint can score from a supplied sample. The
#: other three methods in the column CHECK (`infrastructure`, `attribution`,
#: `manual`) exist on the row because other pipelines write them; this endpoint
#: will not invent a score for them.
PersonaScoringMethod = Literal["stylometry", "behavioural"]

#: Every method the column accepts, for the response side and the filter.
PERSONA_LINKAGE_METHODS: tuple[str, ...] = (
    "stylometry",
    "behavioural",
    "infrastructure",
    "attribution",
    "manual",
)

PERSONA_LINKAGE_STATUSES: tuple[str, ...] = ("proposed", "confirmed", "rejected")


class BehaviourEventIn(BaseModel):
    """One posting event supplied as a behaviour sample.

    A field-for-field adapter over :class:`aegis.behavior.profile.PostingEvent`
    so the platform's own profile builder is the thing that reads it.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    posted_at: datetime
    platform: str = Field(min_length=1, max_length=64)
    text: str = ""
    parent_author_id: str | None = None
    parent_posted_at: datetime | None = None


class PersonaLinkageProposal(BaseModel):
    """A request to *propose* a linkage. Never a request to record one.

    ``extra="forbid"`` is load-bearing rather than pedantic: a body carrying
    ``score`` must be refused, not silently ignored, because a caller who
    supplies a score is asking the platform to store their number under the
    platform's name. The score on a proposal is computed here, from the
    samples, by :mod:`aegis.api.persona_scoring`.
    """

    model_config = ConfigDict(extra="forbid")

    actor_id: UUID
    candidate_handle: str = Field(min_length=1, max_length=128)
    method: PersonaScoringMethod
    case_id: UUID | None = None
    #: Text attributed to the known actor. Required for `stylometry`.
    actor_sample: str = ""
    #: Text attributed to the candidate handle. Required for `stylometry`.
    candidate_sample: str = ""
    #: Events attributed to the known actor. Required for `behavioural`.
    actor_events: list[BehaviourEventIn] = Field(default_factory=list)
    #: Events attributed to the candidate handle. Required for `behavioural`.
    candidate_events: list[BehaviourEventIn] = Field(default_factory=list)


class AdjudicationRequest(BaseModel):
    """An analyst ruling on a proposed linkage.

    ``analyst_id`` is required rather than optional. The ``ck_persona_linkage_
    adjudicated`` CHECK constraint would reject the write anyway; requiring it
    here means the refusal names the missing field instead of surfacing as a
    database error.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["confirmed", "rejected"]
    analyst_id: UUID
    #: A decision with no stated reason is indistinguishable from a model
    #: output, which is exactly the distinction the ``status`` column exists to
    #: keep. The CHECK constraint enforces who and when; this enforces why.
    rationale: str = Field(min_length=1, max_length=2000)


class PersonaLinkage(BaseModel):
    """One row of the linkage register, with the analyst decision resolved."""

    model_config = ConfigDict(frozen=True)

    linkage_id: UUID
    actor_id: UUID
    actor_handle: str
    candidate_handle: str
    method: str
    #: The model's output for this pair. Never changed by an adjudication.
    score: float
    status: str
    aligned_features: list[str]
    apart_features: list[str]
    contested_features: list[str]
    limitations: list[str]
    case_id: UUID | None
    case_name: str | None
    adjudicated_by: UUID | None
    adjudicated_by_name: str | None
    adjudicated_at: datetime | None
    rationale: str | None
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    #: True only once an analyst has ruled. The register stops calling a score
    #: a finding exactly when this flips, so a `proposed` row cannot be
    #: rendered as a conclusion by accident.
    analyst_recorded: bool


class PersonaLinkageDetail(PersonaLinkage):
    """One linkage, with the per-feature values behind the three-way split."""

    #: Feature name -> the scale-free agreement the scorer computed for it.
    feature_agreement: dict[str, float] = Field(default_factory=dict)
    #: Human-readable label of the function that produced ``score``.
    scorer: str | None = None


class AdjudicationResponse(BaseModel):
    """The server's answer to an adjudication, as stored.

    Returned from the server rather than applied in the browser, so the row an
    analyst is looking at shows the adjudicator and the timestamp the database
    holds — not the ones the client hoped for.
    """

    model_config = ConfigDict(frozen=True)

    linkage: PersonaLinkage
    #: The ruling this one replaced, or ``None`` for a first adjudication.
    previous_status: str | None
    previous_rationale: str | None
    previous_adjudicator: str | None
    audit_seq: int


class PersonaLinkageSummary(BaseModel):
    """Counts across the register, and the one pair of numbers worth reading.

    ``confirmed_low_score`` and ``rejected_high_score`` are the model's
    false-positive and false-negative rates *as analysts have actually observed
    them*: proposals the scorer ranked high that a human threw out, and
    proposals it ranked low that a human accepted. Nothing self-reported by the
    scorer appears here, because the point of the figure is that it is derived
    from decisions rather than asserted by the thing being measured.
    """

    model_config = ConfigDict(frozen=True)

    total: int
    by_status: dict[str, int]
    by_method: dict[str, int]
    #: Unadjudicated — hypotheses nobody has ruled on yet.
    proposed: int
    confirmed: int
    rejected: int
    adjudicated: int
    #: Denominators for the pair below, returned so no ratio is printed
    #: against an implied one.
    confirmed_total: int
    rejected_total: int
    confirmed_low_score: int
    rejected_high_score: int
    #: The line the pair is measured against, returned so the UI can label it
    #: instead of implying one.
    score_threshold: float
    #: Set when there is nothing adjudicated to measure, and says so rather
    #: than reporting a clean 0% error rate over an empty denominator.
    gap: str | None = None


class PersonaExport(BaseModel):
    """The export payload: the rows behind the filters, plus the summary.

    The summary travels with the data because a register exported without the
    observed error rate invites the reader to assume the model was right.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    filters: dict[str, Any]
    summary: PersonaLinkageSummary
    linkages: list[PersonaLinkage]
