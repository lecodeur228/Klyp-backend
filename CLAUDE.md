# CLAUDE.md — FastAPI AI Starter

Same principles as `AGENTS.md`.

## Non-negotiables

1. API-only — no HTML/Jinja/frontend
2. Routers stay thin
3. AI via `AIProvider` abstraction
4. Fake provider in CI — no live RodiumAI quota
5. Docs + tests for shared behavior changes

## Verify

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```
