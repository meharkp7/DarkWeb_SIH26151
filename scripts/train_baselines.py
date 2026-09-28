"""Freeze the Phase 09 entity-resolution baseline metrics.

Runs all five plan baselines (exact handle, edit distance, TF-IDF
cosine, logistic regression, XGBoost) under the actor-grouped,
leak-free protocol in :mod:`aegis.resolution.evaluate` and writes the
frozen reference report to ``artifacts/baselines/``.

Run by ``make train-baselines``:
    PYTHONPATH=src uv run python scripts/train_baselines.py

Per plan section 35 the artifact doubles as the experiment registry
entry (experiment id, seeds, hyperparameters, metrics, git commit,
artifact path).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from aegis.resolution.baselines import RANDOM_SEED
from aegis.resolution.evaluate import evaluate_baselines, format_report

DEFAULT_OUTPUT_DIR = Path("artifacts/baselines")
REPORT_FILENAME = "resolution_baselines.json"


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory for the frozen report (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--exclude-handle-features",
        action="store_true",
        help="ablation: zero handle-similarity features to measure non-handle reliance",
    )
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="ablation: drop feature 8 (graph neighborhood similarity)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="override the split seed (default: the frozen RANDOM_SEED)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    seed = RANDOM_SEED if args.seed is None else args.seed
    report = evaluate_baselines(
        seed=seed,
        use_graph=not args.no_graph,
        exclude_handle_features=args.exclude_handle_features,
    )
    print(format_report(report))

    payload = {
        "experiment_id": "phase09-resolution-baselines",
        "dataset_version": f"synthetic-corpus-seed-{report.corpus_seed}",
        "feature_version": "resolution-features-v1",
        "model_version": "baselines-v1",
        "seed": report.split_seed,
        "hyperparameters": {
            "train_fraction": report.train_fraction,
            "negatives_per_positive": report.negatives_per_positive,
            "k": report.k,
            "use_graph": report.use_graph,
            "exclude_handle_features": report.exclude_handle_features,
        },
        "metrics": {baseline.name: baseline.as_dict() for baseline in report.baselines},
        "git_commit": _git_commit(),
        "created_at": datetime.now(UTC).isoformat(),
        "report": report.as_dict(),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / REPORT_FILENAME
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nfrozen report written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
