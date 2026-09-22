# AI architecture

## Providers

| Protocol | Implementations | Role |
|----------|------------------|------|
| `AIProvider` | `RodiumAIProvider`, `FakeAIProvider` | LLM / structured / images / embeddings |
| `VideoAIProvider` (planned) | Higgsfield, … | Generative video edit / B-roll / transform |

Services today: generation, structured, streaming, embeddings. Prompts in registry.

## Vibe Agent rules

1. Structured **EditPlan** output — validate / repair before execute.
2. Prefer deterministic FFmpeg ops over generative video when possible.
3. Track usage + credits; estimate before costly generative calls.
4. Fake providers in tests/CI.

Product context: Klyp-docs → `docs/01-product/vibe-editing-agent.md`.
