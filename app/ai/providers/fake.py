"""Deterministic fake AI provider for tests and CI."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.ai.providers.base import (
    AIEmbedResult,
    AIGenerateResult,
    AIImageResult,
    AIStructuredResult,
    AIUsageStats,
)


class FakeAIProvider:
    name = "fake"

    async def generate(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AIGenerateResult:
        raw = messages[-1].get("content") if messages else ""
        if isinstance(raw, list):
            last = " ".join(
                str(p.get("text") or "") for p in raw if isinstance(p, dict)
            )
        else:
            last = str(raw or "")
        # Vision placement probe
        if "caption placement" in last.lower() or "position" in last.lower():
            content = json.dumps(
                {"position": "lower", "scale": "md", "reason": "talking head safe default"}
            )
        else:
            content = f"FAKE_RESPONSE: {last[:500]}"
        return AIGenerateResult(
            content=content,
            model=model or "fake-model",
            provider=self.name,
            usage=AIUsageStats(
                prompt_tokens=max(len(last.split()), 1),
                completion_tokens=len(content.split()),
                total_tokens=max(len(last.split()), 1) + len(content.split()),
            ),
        )

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],
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
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        model: str | None = None,
    ) -> AIStructuredResult:
        raw = messages[-1].get("content") if messages else ""
        if isinstance(raw, list):
            last = " ".join(
                str(p.get("text") or "") for p in raw if isinstance(p, dict)
            )
        else:
            last = str(raw or "")
        title = schema.get("title", "object")
        if title == "CaptionPlacement":
            data = {"position": "lower", "scale": "md", "reason": "fake"}
        else:
            data = {"summary": last[:200], "schema": title}
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

    async def generate_image(
        self,
        *,
        prompt: str,
        model: str | None = None,
        size: str = "1024x1024",
    ) -> AIImageResult:
        # 1x1 PNG
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        _ = size
        return AIImageResult(
            content=png,
            mime_type="image/png",
            model=model or "fake-image",
            provider=self.name,
            revised_prompt=prompt[:200],
        )

    def dumps_example(self) -> str:
        return json.dumps({"ok": True})
