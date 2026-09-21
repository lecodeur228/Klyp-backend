"""Embeddings orchestration."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import AIEmbedResult, AIProvider
from app.ai.usage.tracker import track_usage


async def embed_texts(
    provider: AIProvider,
    session: AsyncSession,
    *,
    user_id: str,
    inputs: list[str],
    model: str | None = None,
    request_id: str | None = None,
) -> AIEmbedResult:
    result = await provider.embed(inputs=inputs, model=model)
    await track_usage(
        session,
        user_id=user_id,
        provider=result.provider,
        model=result.model,
        operation="embed",
        usage=result.usage,
        request_id=request_id,
    )
    return result
