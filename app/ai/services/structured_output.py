"""Structured output orchestration."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import AIProvider, AIStructuredResult
from app.ai.usage.tracker import track_usage

GENERIC_SCHEMA: dict[str, Any] = {
    "title": "generic_object",
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
    },
}


async def generate_structured(
    provider: AIProvider,
    session: AsyncSession,
    *,
    user_id: str,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    schema: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AIStructuredResult:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    result = await provider.generate_structured(
        messages=messages,
        schema=schema or GENERIC_SCHEMA,
        model=model,
    )
    await track_usage(
        session,
        user_id=user_id,
        provider=result.provider,
        model=result.model,
        operation="structured",
        usage=result.usage,
        request_id=request_id,
    )
    return result
