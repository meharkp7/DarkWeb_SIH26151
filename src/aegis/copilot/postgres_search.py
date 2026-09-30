"""A PostgreSQL-backed :class:`~aegis.search.types.SearchEngine` for the copilot.

OpenSearch is an *optional* adapter. It is absent unless someone ran
``docker compose up``, and the platform is designed to work without it — the
console renders, the case workspace loads, every register lists real rows.

The copilot did not. Its default route is ``search_evidence``, so with
OpenSearch down *every question an analyst types* — the default route is what
a plain question takes — returned:

    Findings:
    No evidence-backed findings were retrieved.

which is indistinguishable from a case with no evidence, while the case held
six hundred of it. The console's own first suggestion, "What changed in this
investigation?", was unanswerable in the default deployment.

So this is a fallback engine, not a second source of truth. It reads the same
``evidence`` table the indexer writes from, builds the same
:class:`~aegis.search.types.IndexedDocument`, and serves it through the
existing :class:`~aegis.search.engine.InProcessSearchEngine` — the same
protocol, the same scoring, the same filters. Nothing about the copilot's
tool code changes; only which engine it holds.

The scope is deliberately narrow: one case, capped, and built per request.
That is cheap for the case sizes a copilot question is asked about and it
avoids a second indexing pipeline that could drift from OpenSearch's. The
trade is stated plainly in the response, because "searched 40 of 4,340
records" is a different claim from "searched the evidence".
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aegis.db.models import EvidenceRecord
from aegis.evidence.search_index import evidence_from_record
from aegis.search.engine import InProcessSearchEngine
from aegis.search.types import IndexedDocument, IndexName, SearchError, SearchQuery, SearchResult

logger = logging.getLogger(__name__)

#: How many records one copilot question may consider.
#:
#: The cap is a *scope statement*, not a performance limit: a case can hold
#: thousands of records, and silently searching 200 of 4,340 and reporting
#: "the top 10" is a claim about the corpus the analyst never made. The
#: response says how many were considered so the number on screen can be read
#: as what it is.
MAX_FALLBACK_DOCUMENTS = 400


class PostgresEvidenceSearch:
    """Search over ``evidence`` rows, backed by PostgreSQL.

    Implements the parts of :class:`~aegis.search.types.SearchEngine` a
    *reader* needs. ``index`` and ``remove`` raise rather than pretending:
    this engine is for the copilot's retrieval, and silently accepting a write
    and losing it would be worse than refusing.
    """

    def __init__(self, db: Session, *, case_id: UUID | None = None) -> None:
        self._db = db
        self._case_id = case_id
        self._engine: InProcessSearchEngine | None = None
        self.considered = 0

    # -- writer side: refused on purpose ---------------------------------

    def index(self, document: IndexedDocument) -> None:
        raise SearchError("PostgresEvidenceSearch is read-only; index into the real engine")

    def remove(self, index: IndexName, doc_id: str) -> bool:
        raise SearchError("PostgresEvidenceSearch is read-only; index into the real engine")

    def index_document(self, document: IndexedDocument) -> None:
        raise SearchError("PostgresEvidenceSearch is read-only; index into the real engine")

    # -- reader side ------------------------------------------------------

    def _build(self) -> InProcessSearchEngine:
        if self._engine is not None:
            return self._engine

        statement = select(EvidenceRecord)
        if self._case_id is not None:
            statement = statement.where(EvidenceRecord.case_id == self._case_id)
        # Newest first: for a "what changed" question the recent records are
        # the answer, and a stable secondary key keeps the *set* identical
        # across two runs so the same question is not answered from a
        # different sample.
        statement = statement.order_by(
            EvidenceRecord.collected_at.desc(), EvidenceRecord.evidence_id
        ).limit(MAX_FALLBACK_DOCUMENTS)
        records = self._db.scalars(statement).all()
        self.considered = len(records)

        engine = InProcessSearchEngine()
        for record in records:
            try:
                evidence = evidence_from_record(record)
                engine.index(IndexedDocument.from_evidence(evidence))
            except Exception as error:  # noqa: BLE001 - one bad row must not lose the rest
                logger.debug(
                    "Skipping evidence %s in the copilot fallback: %s", record.evidence_id, error
                )
        self._engine = engine
        return engine

    def search(self, query: SearchQuery) -> SearchResult:
        return self._build().search(query)

    def health(self) -> dict[str, Any]:
        total = self._db.scalar(
            select(func.count()).select_from(EvidenceRecord).where(
                EvidenceRecord.case_id == self._case_id
            )
            if self._case_id is not None
            else select(func.count()).select_from(EvidenceRecord)
        )
        return {
            "backend": "postgresql",
            "case_id": str(self._case_id) if self._case_id else None,
            "considered": self.considered,
            "total": int(total or 0),
        }
