# FastAPI AI Starter — Agent Instructions

Generic **AI-first API** starter. Do not add product-specific business domains unless asked.

## Architecture

```text
Router → Service / Use case → Repository / Provider → Infrastructure
```

AI lives under `app/ai/` (providers, prompts, services, usage). Never put RodiumAI HTTP calls in routers.

## API contract

- Base: `/api/v1`
- Success: `{ success, message, data }`
- Error: `{ success: false, message, code, errors? }`
- Pagination meta: snake_case (`current_page`, …)

## AI rules

- Depend on `AIProvider`, not `RodiumAIProvider`
- Use `FakeAIProvider` in tests/CI
- Track usage for generate/structured/embed
- Long work → Celery job + `202 Accepted`
- Never log API keys, passwords, or full prompts in production

## Auth

- JWT access + refresh; API keys hashed
- Check permissions before AI calls

## Workflow

1. Read these instructions + `.cursor/rules`
2. Change the correct layer
3. Add tests
4. Update docs if contract/env changes
5. Run `uv run ruff check . && uv run mypy app && uv run pytest`
