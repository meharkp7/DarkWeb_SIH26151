# AEGIS — Attribution & Evidence Graph Intelligence System

Evidence-centric foundation for lawful defensive threat-intelligence research, controlled synthetic experiments, and authorized investigations.

## Current implementation

- FastAPI service
- PostgreSQL + Alembic migrations
- Evidence and source records
- Content-addressed local artifact store
- SHA-256 integrity verification
- Evidence provenance/derivation model
- REST endpoints for sources, evidence, and provenance
- Environment configuration through `.env`

## Setup

```bash
cp .env.example .env
uv sync --extra dev
make infra-up
uv run alembic upgrade head
uv run uvicorn aegis.api.app:app --reload --host 127.0.0.1 --port 8000
```

If `uv` is not installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then restart the terminal and run the setup commands above.

## Checks

```bash
PYTHONPATH=src uv run pytest -q
PYTHONPATH=src uv run ruff check src tests
PYTHONPATH=src uv run mypy src
```

## API

- `GET /health`
- `GET /health/db`
- `POST /api/v1/sources`
- `POST /api/v1/evidence`
- `GET /api/v1/evidence/{evidence_id}`
- `GET /api/v1/evidence/{evidence_id}/provenance`

Swagger UI: `http://127.0.0.1:8000/docs`
