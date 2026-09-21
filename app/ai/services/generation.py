"""Text generation orchestration."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.registry import render_prompt
from app.ai.providers.base import AIGenerateResult, AIProvider
from app.ai.usage.tracker import track_usage


async def generate_text(
    provider: AIProvider,
    session: AsyncSession,
    *,
    user_id: str,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    prompt_name: str | None = None,
    request_id: str | None = None,
) -> AIGenerateResult:
    messages: list[dict[str, str]] = []
    if prompt_name:
        sys, user, _version = render_prompt(prompt_name, content=prompt)
        messages.append({"role": "system", "content": sys})
        messages.append({"role": "user", "content": user})
    else:
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

    result = await provider.generate(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    await track_usage(
        session,
        user_id=user_id,
        provider=result.provider,
        model=result.model,
        operation="generate",
        usage=result.usage,
        request_id=request_id,
    )
    return result
