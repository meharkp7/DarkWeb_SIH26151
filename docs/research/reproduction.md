# Reproducing the synthetic AEGIS runs

Use Python 3.12 or 3.13, install the project and development dependencies, and
run commands from the repository root. The Make targets use a workspace-local
uv cache by default.

```sh
make install
make train-graph
make benchmark
make rehearsal
```

Default generated artifacts (ignored by Git):

- `artifacts/training/phase19-comparison.json`
- `artifacts/benchmarks/synthetic-load.json`
- `artifacts/rehearsal/phase28.json`

To vary the benchmark size or seed directly:

```sh
PYTHONPATH=src uv run python scripts/train_graph_models.py --seed 26151 --groups 30 --epochs 400
PYTHONPATH=src uv run python scripts/run_benchmark.py --actors 100 --seeds 26151 26152
PYTHONPATH=src uv run python scripts/run_rehearsal.py --seed 26151 --actors 12
```

Record the Git commit, command-line arguments, Python/package versions, output
hashes, and split assignments with any result shared outside the team. The
current benchmark does not include real-world data, multi-process service
load, production database measurements, or end-to-end GNN weight learning.
