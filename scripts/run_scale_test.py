"""Controlled scale profile for 10K/100K/1M synthetic records."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter


@dataclass(frozen=True)
class ScaleResult:
    records: int
    build_ms: float
    serialize_ms: float
    estimated_memory_mb: float


def run(count: int) -> ScaleResult:
    if count < 1:
        raise ValueError("count must be positive")
    started = perf_counter()
    rows = [
        {"id": i, "case_id": i % 100, "source": "synthetic", "sha256": f"{i:064x}"}
        for i in range(count)
    ]
    build_ms = (perf_counter() - started) * 1000
    started = perf_counter()
    blob = json.dumps(rows, separators=(",", ":"))
    serialize_ms = (perf_counter() - started) * 1000
    return ScaleResult(
        count,
        round(build_ms, 3),
        round(serialize_ms, 3),
        round(len(blob) / 1_048_576, 3),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", nargs="+", type=int, default=[10_000, 100_000, 1_000_000])
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/benchmarks/scale-profile.json")
    )
    args = parser.parse_args()
    results = [run(count) for count in args.counts]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps([asdict(x) for x in results], indent=2) + "\n")
    print(json.dumps([asdict(x) for x in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
