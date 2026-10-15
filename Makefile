.PHONY: install lint format typecheck test cov check up down logs reconcile loadtest

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

cov:
	uv run pytest --cov --cov-report=term-missing

check: lint typecheck test

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api worker mock-provider

reconcile:
	docker compose exec worker payflow reconcile

loadtest:
	docker compose --profile loadtest up locust
