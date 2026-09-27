.PHONY: install test lint typecheck run infra-up infra-down

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

run:
	uv run uvicorn aegis.api.app:app --reload --host 127.0.0.1 --port 8000

infra-up:
	docker compose up -d postgres

infra-down:
	docker compose down

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "update schema"
