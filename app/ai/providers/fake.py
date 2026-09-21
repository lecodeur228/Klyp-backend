"""Deterministic fake AI provider for tests and CI."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.ai.providers.base import (
    AIEmbedResult,
    AIGenerateResult,
    AIStructuredResult,
    AIUsageStats,
)


class FakeAIProvider:
    name = "fake"

    async def generate(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AIGenerateResult:
        last = messages[-1]["content"] if messages else ""
        content = f"FAKE_RESPONSE: {last[:500]}"
        return AIGenerateResult(
            content=content,
            model=model or "fake-model",
            provider=self.name,
            usage=AIUsageStats(
                prompt_tokens=len(last.split()),
                completion_tokens=len(content.split()),
                total_tokens=len(last.split()) + len(content.split()),
            ),
        )

    async def stream(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        result = await self.generate(messages=messages, model=model)
        for word in result.content.split(" "):
            yield word + " "

    async def generate_structured(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        model: str | None = None,
    ) -> AIStructuredResult:
        last = messages[-1]["content"] if messages else ""
        data = {"summary": last[:200], "schema": schema.get("title", "object")}
        return AIStructuredResult(
            data=data,
            model=model or "fake-model",
            provider=self.name,
            usage=AIUsageStats(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    async def embed(
        self,
        *,
        inputs: list[str],
        model: str | None = None,
    ) -> AIEmbedResult:
        vectors = [[float(len(text) % 17), float(len(text.split())), 0.1] for text in inputs]
        return AIEmbedResult(
            embeddings=vectors,
            model=model or "fake-embed",
            provider=self.name,
            usage=AIUsageStats(prompt_tokens=sum(len(i.split()) for i in inputs), total_tokens=0),
        )

    def dumps_example(self) -> str:
        return json.dumps({"ok": True})
