"""Controlled dependency-failure matrix for AEGIS service adapters."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class FailureCase:
    dependency: str
    expected: str
    implemented: str


CASES = (
    FailureCase(
        "postgres",
        "request fails loudly; transaction rolls back",
        "SQLAlchemy exception boundary",
    ),
    FailureCase(
        "opensearch",
        "DB remains authoritative; indexing failure is surfaced/logged",
        "post-commit indexing boundary",
    ),
    FailureCase(
        "neo4j",
        "in-process graph fallback remains usable",
        "adapter isolation",
    ),
    FailureCase(
        "collector",
        "job records failure; no partial evidence commit",
        "collector orchestration transaction boundary",
    ),
    FailureCase(
        "object_storage",
        "evidence transaction rolls back when artifact write is required",
        "EvidenceService transaction boundary",
    ),
    FailureCase(
        "llm",
        "copilot remains deterministic/evidence-grounded",
        "rule-based synthesis; no mandatory LLM dependency",
    ),
)


def main() -> int:
    output = Path("artifacts/failure-matrix.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([asdict(case) for case in CASES], indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
