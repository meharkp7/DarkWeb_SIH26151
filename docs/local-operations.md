# Local operations

AEGIS is synthetic-first. Run every command from the repository root.

## Bring up the vertical slice

```bash
uv sync --extra dev
make infra-up
make migrate
PYTHONPATH=src uv run uvicorn aegis.api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd apps/frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite proxy connects the UI to the local API.

For separately hosted frontend and API deployments, set the explicit trusted-origin list:

```bash
export AEGIS_CORS_ORIGINS="https://console.example.com"
```

## Local training and evaluation

```bash
make train-baselines
make train-graph
make adversarial-evaluate
make benchmark
make rehearsal
```

`make train-graph` is a deterministic synthetic comparison. It is not an operational
trained model: use authorized labelled data, actor/temporal/platform-disjoint evaluation,
calibration assessment, and a reviewed model registry before any deployment decision.

## Required release gates

```bash
make lint
make typecheck
make schema-check
make test
make security-scan
make build
```

Production deployment still requires organization-specific identity/RBAC integration,
shared rate limiting, secret management, TLS termination, S3/OpenSearch/Neo4j provisioning,
centralized tracing and alerting, backups, retention controls, and a completed DAST/container
scan. These controls cannot be safely configured from this repository without the target
environment and credentials.
