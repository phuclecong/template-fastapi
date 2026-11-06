# Template Dashboard API

A contract-first FastAPI backend for the authenticated dashboard template. The OpenAPI
contract in [docs/openapi.yaml](docs/openapi.yaml) is the single source of truth for API
consumers; the app generates its schema from code under `/api/v1` and is diffed against
that contract in CI to catch drift.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

The API is served under `/api/v1` (health check at `GET /api/v1/health`). Interactive docs
are at `/docs`.

## Migrations

```bash
uv run alembic upgrade head        # apply migrations
uv run alembic revision --autogenerate -m "..."   # create a new migration
```

## Test, lint, type-check

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```
