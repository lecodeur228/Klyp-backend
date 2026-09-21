"""Streaming orchestration (no usage persist mid-stream)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.ai.providers.base import AIProvider


async def stream_text(
    provider: AIProvider,
    *,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    async for chunk in provider.stream(messages=messages, model=model):
        yield chunk
