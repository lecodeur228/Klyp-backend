# Klyp Backend — Agent Instructions

**Product:** [Vibe Editing Agent](https://github.com/lecodeur228/Klyp-docs/blob/main/docs/01-product/vibe-editing-agent.md) (see `Klyp-docs`).

Klyp-backend is the FastAPI heart of Klyp: analysis, EditPlan, creative/vibe-edit, render, credits.

## Architecture

```text
Router → Service / Use case → Repository / Provider → Infrastructure
```

AI lives under `app/ai/` (providers, prompts, services, usage). Never put RodiumAI HTTP calls in routers.

Target domain (do not big-bang rewrite): `app/` modules for vibe agent (intent, planner, tools) composing existing editplan / creative / render.

## Product rules (Vibe Agent)

1. Prefer **FFmpeg** when the operation is deterministic (cut, silence, crop, zoom, concat).
2. Use **RodiumAI** (`AIProvider`) for intent / structured EditPlan / prompts.
3. Use **Higgsfield** only behind a future `VideoAIProvider` for generative video ops.
4. Never execute AI-authored raw FFmpeg shell strings.
5. Never destroy the original asset; version EditPlans.
6. Estimate credits before costly generative jobs.

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

1. Read these instructions + `.cursor/rules` + Klyp-docs vibe-editing-agent
2. Change the correct layer
3. Add tests
4. Update docs if contract/env changes
5. Run `uv run ruff check . && uv run mypy app && uv run pytest`
