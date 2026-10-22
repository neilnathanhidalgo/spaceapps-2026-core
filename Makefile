.PHONY: help setup run dev test test-unit test-integration lint fmt check-connections docker-build docker-up docker-down clean

help:
	@echo "Available targets:"
	@echo "  setup              Create venv and install dev dependencies with uv"
	@echo "  run                Run the API with uvicorn"
	@echo "  dev                Run the API with auto-reload"
	@echo "  test               Run unit tests"
	@echo "  test-unit          Run unit tests only (no network)"
	@echo "  test-integration   Run integration tests (hits real APIs, needs creds)"
	@echo "  lint               Run ruff lint"
	@echo "  fmt                Run ruff format"
	@echo "  check-connections  Probe all data sources and print status table"
	@echo "  docker-build       Build Docker image"
	@echo "  docker-up          Start containers"
	@echo "  docker-down        Stop containers"
	@echo "  clean              Remove caches and build artifacts"

setup:
	uv venv
	uv pip install -e ".[dev]"

run:
	uv run uvicorn spaceapps_core.main:app --host 0.0.0.0 --port 8000

dev:
	uv run uvicorn spaceapps_core.main:app --reload --host 0.0.0.0 --port 8000

test: test-unit

test-unit:
	uv run pytest tests/unit

test-integration:
	uv run pytest tests/integration -m integration

lint:
	uv run ruff check src tests scripts

fmt:
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

check-connections:
	uv run python scripts/check_connections.py

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache .cache cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
