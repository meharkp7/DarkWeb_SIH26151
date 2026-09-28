"""Run a reproducible synthetic scale profile and write JSON results.

Example: PYTHONPATH=src uv run python scripts/run_benchmark.py --actors 100 --seeds 26151 26152
This measures synthetic evidence generation and candidate-link scoring; it
does not claim to benchmark PostgreSQL, Neo4j, or OpenSearch throughput.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from aegis.evaluation.runner import SyntheticBenchmarkRunner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actors", type=int, default=100)
    parser.add_argument("--seeds", type=int, nargs="+", default=[26151])
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/benchmarks/synthetic-load.json")
    )
    args = parser.parse_args()
    if args.actors < 4:
        parser.error("--actors must be at least 4")
    results = SyntheticBenchmarkRunner().run(args.seeds, actor_count=args.actors)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            [asdict(result) for result in results], default=lambda value: value.__dict__, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(results)} run(s) to {args.output}")
    for result in results:
        print(
            f"seed={result.seed} actors={result.actor_count} evidence={result.evidence_count} "
            f"candidates={result.candidate_count} generation_ms={result.generation_ms} "
            f"candidate_generation_ms={result.candidate_generation_ms} f1={result.metrics.f1}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
