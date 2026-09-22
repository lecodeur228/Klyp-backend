"""AI provider protocol and shared types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AIUsageStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AIGenerateResult:
    content: str
    model: str
    provider: str
    usage: AIUsageStats = field(default_factory=AIUsageStats)
    raw: dict[str, Any] | None = None


@dataclass
class AIStructuredResult:
    data: dict[str, Any]
    model: str
    provider: str
    usage: AIUsageStats = field(default_factory=AIUsageStats)


@dataclass
class AIEmbedResult:
    embeddings: list[list[float]]
    model: str
    provider: str
    usage: AIUsageStats = field(default_factory=AIUsageStats)


@dataclass
class AIImageResult:
    content: bytes
    mime_type: str
    model: str
    provider: str
    revised_prompt: str | None = None


class AIProvider(Protocol):
    name: str

    async def generate(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AIGenerateResult: ...

    def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...

    async def generate_structured(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        model: str | None = None,
    ) -> AIStructuredResult: ...

    async def embed(
        self,
        *,
        inputs: list[str],
        model: str | None = None,
    ) -> AIEmbedResult: ...
