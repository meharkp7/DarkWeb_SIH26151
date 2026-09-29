"""Schemas for actor-to-actor links — the trust graph.

The problem statement's second capability asks for "a single relationship
graph of handles, PGP keys, wallets and **trust links**". Identifiers and
marketplaces are attributes of an actor; the relations *between* actors are
the graph, and they had nowhere to live.

Two fields carry most of the meaning here:

* `basis` is free text because the basis is frequently a sentence a human
  wrote. A trust edge with no stated reason is an assertion, and forcing the
  reason into an enum would mean either losing the detail or refusing to
  record the link at all.
* `analyst_recorded` is separate from `confidence`, because a model
  proposing a link and a human confirming it are different facts. Only the
  second one may be presented as a finding.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: The link vocabulary. Constrained in the database too, so a new kind is a
#: migration rather than a silent new value in a graph nobody can filter.
ActorLinkKind = Literal[
    "trusts",
    "works_with",
    "sells_to",
    "mentions",
    "disputes",
    "shares_identifier",
]

#: Kinds meaningful in one direction only. A vendor vouches for a buyer far
#: more often than the reverse, and a symmetric edge would erase the
#: asymmetry that makes the relation worth recording.
DIRECTED_KINDS: frozenset[str] = frozenset({"trusts", "sells_to"})


class ActorLink(BaseModel):
    """One directed edge between two registry actors, both ends named.

    An edge showing two opaque ids is not a relationship. Naming both
    handles and both categories is most of what makes it readable without
    a second lookup.
    """

    model_config = ConfigDict(frozen=True)

    link_id: UUID
    kind: str
    subject_actor_id: UUID
    subject_handle: str
    subject_category: str
    object_actor_id: UUID
    object_handle: str
    object_category: str
    basis: str | None
    limitations: list[str]
    confidence: float | None
    first_seen: datetime | None
    last_seen: datetime | None
    source_id: UUID | None
    source_name: str | None
    case_id: UUID | None
    evidence_ids: list[UUID]
    analyst_recorded: bool
    recorded_by: UUID | None
    recorded_at: datetime | None


class ActorLinkCreate(BaseModel):
    """Propose a link.

    `extra="forbid"` so a caller-supplied `analyst_recorded` is a 422 rather
    than a silently-ignored key — otherwise a client could believe it had
    recorded a finding when it had only filed a proposal.
    """

    model_config = ConfigDict(extra="forbid")

    subject_actor_id: UUID
    object_actor_id: UUID
    kind: ActorLinkKind
    basis: str | None = Field(default=None, max_length=2000)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    source_id: UUID | None = None
    case_id: UUID | None = None
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ActorLinkDecision(BaseModel):
    """An analyst ruling on a proposed link.

    `basis` is required. A decision with no stated reason is
    indistinguishable from a model output, which is the exact distinction
    the `analyst_recorded` flag exists to draw.
    """

    model_config = ConfigDict(extra="forbid")

    basis: str = Field(min_length=1, max_length=2000)
    actor_id: UUID
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class ActorGraphNode(BaseModel):
    """One registry actor as a graph node, with its aggregates resolved."""

    model_config = ConfigDict(frozen=True)

    actor_id: UUID
    handle: str
    category: str
    status: str
    confidence: float | None
    #: How many links touch this node. Centrality is the question the graph
    #: exists to answer, so it is computed here rather than in the browser.
    degree: int
    identifier_kinds: list[str]
    platforms: int
    last_seen: datetime | None


class ActorGraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    link_id: UUID
    kind: str
    directed: bool
    subject_actor_id: UUID
    object_actor_id: UUID
    subject_handle: str
    object_handle: str
    confidence: float | None
    basis: str | None
    analyst_recorded: bool


class ActorGraphResponse(BaseModel):
    """The whole registry graph in one frame.

    `dropped_nodes` is the count of actors excluded by the node limit.
    Reporting it is the difference between a graph the analyst can trust
    and one where a truncated result is indistinguishable from a complete
    one.
    """

    model_config = ConfigDict(frozen=True)

    nodes: list[ActorGraphNode]
    edges: list[ActorGraphEdge]
    dropped_nodes: int
    #: Edge count by kind, for the legend-as-filter control.
    kinds: dict[str, int]
    #: How many distinct independence groups the underlying identifiers span.
    #: A registry that looks like forty sources but is really six outlets is
    #: not forty sources.
    independence_groups: int
