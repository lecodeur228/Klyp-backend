"""AI usage tracker."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import AIUsageStats
from app.models.ai import AiUsage


async def track_usage(
    session: AsyncSession,
    *,
    user_id: str,
    provider: str,
    model: str,
    operation: str,
    usage: AIUsageStats,
    job_id: str | None = None,
    request_id: str | None = None,
) -> AiUsage:
    row = AiUsage(
        user_id=user_id,
        provider=provider,
        model=model,
        operation=operation,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens or (usage.prompt_tokens + usage.completion_tokens),
        estimated_cost_usd=None,
        job_id=job_id,
        request_id=request_id,
    )
    session.add(row)
    await session.flush()
    return row
