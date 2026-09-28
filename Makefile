.PHONY: install bootstrap test lint typecheck build run infra-up infra-down up down \
	migrate revision data-generate data-validate train-baselines train-graph \
	evaluate benchmark report security-scan schema-check precommit frontend-install \
	frontend-dev frontend-build clean

PY ?= uv run
PYTEST = PYTHONPATH=src $(PY) pytest
SRC = src tests scripts

## ---------------------------------------------------------------- bootstrap

install:
	uv sync --extra dev

bootstrap: install
	$(MAKE) schema-check
	$(MAKE) infra-up
	-$(MAKE) migrate
	$(MAKE) frontend-install
	@echo "AEGIS bootstrap complete."

## ---------------------------------------------------------------- quality gates

test:
	$(PYTEST) -q

test-integration:
	AEGIS_REQUIRE_DB=1 $(PYTEST) -q -m integration

lint:
	uv run ruff check $(SRC)
	uv run ruff format --check $(SRC)

format:
	uv run ruff format $(SRC)
	uv run ruff check --fix $(SRC)

typecheck:
	uv run mypy src

schema-check:
	PYTHONPATH=src $(PY) scripts/validate_schemas.py

security-scan:
	PYTHONPATH=src $(PY) scripts/security_scan.py --deps --secrets
	PYTHONPATH=src $(PY) pytest -q -k "security or injection or traversal"

build:
	@test -f apps/frontend/package.json || (echo "apps/frontend missing — run 'make frontend-install'"; exit 1)
	uv build
	cd apps/frontend && npm run build

precommit:
	uv run pre-commit run --all-files

## ---------------------------------------------------------------- runtime

run:
	PYTHONPATH=src uv run uvicorn aegis.api.app:app --reload --host 127.0.0.1 --port 8000

worker:
	@PYTHONPATH=src $(PY) python -c "import aegis.worker.app" 2>/dev/null || (echo "aegis.worker not implemented yet (planned Phase 26 worker runtime)"; exit 1)
	PYTHONPATH=src $(PY) -m aegis.worker.app

scheduler:
	@PYTHONPATH=src $(PY) python -c "import aegis.scheduler.app" 2>/dev/null || (echo "aegis.scheduler not implemented yet (planned scheduler runtime)"; exit 1)
	PYTHONPATH=src $(PY) -m aegis.scheduler.app

infra-up:
	docker compose up -d

infra-down:
	docker compose down

up: infra-up
	$(MAKE) migrate
	$(MAKE) run

down: infra-down

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "update schema"

## ---------------------------------------------------------------- data & ML

data-generate:
	PYTHONPATH=src $(PY) scripts/generate_dataset.py --actors 100 --posts 1000 --seed 26151

data-validate:
	PYTHONPATH=src $(PY) scripts/validate_dataset.py

train-baselines:
	PYTHONPATH=src $(PY) scripts/train_baselines.py

train-graph:
	PYTHONPATH=src $(PY) scripts/train_graph_models.py

evaluate:
	PYTHONPATH=src $(PY) scripts/evaluate.py

benchmark:
	PYTHONPATH=src $(PY) scripts/run_benchmark.py

report:
	PYTHONPATH=src $(PY) scripts/build_report.py

## ---------------------------------------------------------------- frontend

frontend-install:
	cd apps/frontend && npm install

frontend-dev:
	cd apps/frontend && npm run dev

frontend-build:
	cd apps/frontend && npm run build

## ---------------------------------------------------------------- misc

clean:
	rm -rf dist build reports .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
