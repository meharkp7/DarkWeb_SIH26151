"""Regression guard: search rankings must stay identical across optimizations.

The golden payload below was captured from ``InProcessSearchEngine`` *before*
the query-level hoisting / heap top-k optimization of ``engine.py`` was
applied (deterministic corpus, seed 26151). Any change to the engine that
alters ranking output -- scores, ordering, tie-breaks, matched fields/terms,
or candidate totals -- fails these tests.

The corpus builder and query battery are intentionally duplicated here (not
imported from a helper) so the fixture stays pinned to this file.
"""

from __future__ import annotations

import json
import pathlib
import random
from datetime import UTC, datetime, timedelta

from aegis.search import (
    IndexedDocument,
    IndexName,
    InProcessSearchEngine,
    MatchMode,
    RetrievalMode,
    SearchQuery,
)

#: Captured pre-optimization output: query-key -> {total, hits}.
GOLDEN_PATH = pathlib.Path(__file__).parent / "data" / "search_ranking_golden.json"
#: Captured pre-optimization output, parsed at import time.
GOLDEN_JSON = GOLDEN_PATH.read_text(encoding="utf-8")

_VOCAB = [
    "ghostbroker",
    "escrow",
    "wallet",
    "market",
    "forum",
    "onion",
    "pgp",
    "fees",
    "rotation",
    "asap",
    "update",
    "terms",
    "vendor",
    "buyer",
    "thread",
]
_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _build_documents() -> list[IndexedDocument]:
    """Deterministic 120-document corpus (seed 26151)."""
    rng = random.Random(26151)
    documents = []
    for index in range(120):
        body = " ".join(rng.choice(_VOCAB) for _ in range(rng.randint(3, 12)))
        documents.append(
            IndexedDocument.from_text(
                IndexName.POSTS,
                doc_id=f"doc-{index:04d}",
                body=body,
                title=rng.choice(_VOCAB),
                timestamp=_BASE + timedelta(days=rng.randint(0, 300)),
                source=f"src-{rng.randint(1, 3)}",
                entity_ids=(f"ent-{rng.randint(1, 5)}",),
            )
        )
    return documents


def _queries() -> list[SearchQuery]:
    """Query battery covering every match/retrieval mode plus filters."""
    return [
        SearchQuery(text="ghostbroker", index=IndexName.POSTS, limit=6),
        SearchQuery(text="ghostbroker wallet fees", index=IndexName.POSTS, limit=6),
        SearchQuery(
            text="ghostbroker wallet fees",
            index=IndexName.POSTS,
            match_mode=MatchMode.EXACT,
            limit=6,
        ),
        SearchQuery(
            text="ghostbroker wallet",
            index=IndexName.POSTS,
            match_mode=MatchMode.PHRASE,
            limit=6,
        ),
        SearchQuery(
            text="ghostbroker escrow",
            index=IndexName.POSTS,
            retrieval_mode=RetrievalMode.HYBRID,
            limit=6,
        ),
        SearchQuery(
            text="vendor rotation",
            index=IndexName.POSTS,
            retrieval_mode=RetrievalMode.HYBRID,
            match_mode=MatchMode.EXACT,
            limit=6,
        ),
        SearchQuery(
            text="wallet",
            index=IndexName.POSTS,
            since=_BASE + timedelta(days=60),
            until=_BASE + timedelta(days=240),
            sources=("src-1", "src-3"),
            entity_ids=("ent-2", "ent-4"),
            limit=6,
        ),
        SearchQuery(text="", index=IndexName.POSTS, sources=("src-2",), limit=6),
        SearchQuery(text="asap update", index=IndexName.POSTS, limit=1),
        SearchQuery(
            text="fees rotation",
            index=IndexName.POSTS,
            retrieval_mode=RetrievalMode.HYBRID,
            limit=3,
        ),
        SearchQuery(text="nonexistenttoken", index=IndexName.POSTS, limit=6),
    ]


def _query_key(query: SearchQuery) -> str:
    """Stable JSON key identifying one query in the golden payload."""
    return json.dumps(
        {
            "text": query.text,
            "match_mode": query.match_mode.value,
            "retrieval_mode": query.retrieval_mode.value,
            "since": query.since.isoformat() if query.since else None,
            "until": query.until.isoformat() if query.until else None,
            "sources": list(query.sources),
            "entity_ids": list(query.entity_ids),
            "limit": query.limit,
        },
        sort_keys=True,
    )


def _actual_payload(engine: InProcessSearchEngine) -> dict[str, object]:
    """Run every query and shape results to match :data:`GOLDEN_JSON`."""
    payload: dict[str, object] = {}
    for query in _queries():
        result = engine.search(query)
        payload[_query_key(query)] = {
            "total": result.total,
            "hits": [
                {
                    "doc_id": hit.doc_id,
                    "score": hit.score,
                    "lexical": hit.breakdown.lexical,
                    "semantic": hit.breakdown.semantic,
                    "matched_fields": list(hit.matched_fields),
                    "matched_terms": list(hit.matched_terms),
                }
                for hit in result.hits
            ],
        }
    return payload


def test_rankings_match_pre_optimization_fixture() -> None:
    """Live rankings must equal the captured golden output exactly."""
    engine = InProcessSearchEngine()
    engine.index_many(_build_documents())
    expected = json.loads(GOLDEN_JSON)
    assert _actual_payload(engine) == expected


def test_rankings_are_deterministic_across_runs() -> None:
    """Two engines over the same corpus must produce identical rankings."""
    first = InProcessSearchEngine()
    first.index_many(_build_documents())
    second = InProcessSearchEngine()
    second.index_many(_build_documents())
    assert _actual_payload(first) == _actual_payload(second)


def test_golden_covers_all_match_and_retrieval_modes() -> None:
    """The fixture must exercise TERMS/EXACT/PHRASE x LEXICAL/HYBRID."""
    modes = {(q.match_mode, q.retrieval_mode) for q in _queries()}
    assert MatchMode.TERMS in {m for m, _ in modes}
    assert MatchMode.EXACT in {m for m, _ in modes}
    assert MatchMode.PHRASE in {m for m, _ in modes}
    assert RetrievalMode.LEXICAL in {r for _, r in modes}
    assert RetrievalMode.HYBRID in {r for _, r in modes}
    assert len(_queries()) == len(json.loads(GOLDEN_JSON))
