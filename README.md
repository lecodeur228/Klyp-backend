# FastAPI — Klyp Backend

Cœur API de **Klyp** (Vibe Editing Agent) : analysis, EditPlan, vibe-edit, render, crédits.

North star produit : `Klyp-docs/docs/01-product/vibe-editing-agent.md`

## Stack

- Python ≥ 3.12, FastAPI, Pydantic Settings
- SQLAlchemy 2 (async) + Alembic + PostgreSQL
- Redis + Celery
- RodiumAI provider (OpenAI-compatible) + FakeAIProvider for tests/CI
- FFmpeg render pipeline
- uv, Ruff, MyPy, Pytest
- Docker Compose

## Quick start

```bash
uv sync
cp .env.example .env
# start postgres + redis (docker compose up -d postgres redis)
uv run alembic upgrade head
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

Worker:

```bash
uv run celery -A app.workers.celery_app.celery_app worker -Q ai,files,default -l info
```

## Compatible clients

Point your frontend (`NEXT_PUBLIC_API_URL`) at `/api/v1`. Contract: [`docs/api.md`](docs/api.md).

## Auth

- JWT access + refresh rotation
- API keys via `X-API-KEY`
- RBAC permissions (`ai.generate`, `ai.jobs.*`, …)

## AI

Set `AI_PROVIDER=rodiumai` and `RODIUMAI_API_KEY=rd_sk_...` for live calls. Default `fake` for local/CI.

Routes:

- `POST /api/v1/ai/generate`
- `POST /api/v1/ai/structured`
- `POST /api/v1/ai/stream`
- `POST /api/v1/ai/embeddings`
- `POST /api/v1/ai/jobs` → `202 Accepted`

## Commands

```bash
uv run ruff check .
uv run ruff format .
uv run mypy app
uv run pytest
docker compose build
```

## Docs

See [`docs/`](docs/) and [`AGENTS.md`](AGENTS.md).

## GitHub Template

Use as a GitHub Template Repository — configure `.env`, RodiumAI, migrate, start API + worker.
