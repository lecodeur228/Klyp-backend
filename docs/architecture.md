# Architecture

Klyp backend — modular monolith for the **Vibe Editing Agent**.

```text
Router → Service → Repository / Provider → Infrastructure
```

## Domains (current)

Auth, projects, videos, analysis, creative, editplan, captions, render, credits, jobs, pipeline (effects, timeline, sound), AI (`app/ai/`).

## Vibe direction

Product north star lives in `Klyp-docs` (`vibe-editing-agent.md`, ADR-0007).

- **EditPlan** = structured contract (never raw FFmpeg from the LLM)
- **RodiumAI** via `AIProvider` = intelligence / planning
- **FFmpeg** = deterministic editing & final render
- **Higgsfield** (planned) via `VideoAIProvider` = generative video when required
- Jobs via Celery + Redis for long work

Prefer extending existing editplan / creative / workers over a greenfield rewrite.
