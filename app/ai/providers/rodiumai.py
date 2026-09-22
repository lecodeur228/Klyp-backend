"""RodiumAI HTTP provider (OpenAI-compatible)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.ai.providers.base import (
    AIEmbedResult,
    AIGenerateResult,
    AIImageResult,
    AIStructuredResult,
    AIUsageStats,
)
from app.core.config import Settings
from app.core.constants import ErrorCode
from app.core.exceptions import AIProviderException, AIRateLimitException, AITimeoutException


class RodiumAIProvider:
    name = "rodiumai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.rodiumai_base_url.rstrip("/"),
            timeout=settings.rodiumai_timeout,
            headers={
                "Authorization": f"Bearer {settings.rodiumai_api_key}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        retries = self.settings.rodiumai_max_retries
        attempt = 0
        while True:
            try:
                response = await self._client.request(method, path, json=json_body)
            except httpx.TimeoutException as exc:
                raise AITimeoutException() from exc
            except httpx.HTTPError as exc:
                raise AIProviderException(
                    "AI provider unavailable",
                    code=ErrorCode.AI_PROVIDER_UNAVAILABLE,
                ) from exc

            if response.status_code == 429:
                if attempt < retries:
                    await asyncio.sleep(2**attempt)
                    attempt += 1
                    continue
                raise AIRateLimitException()
            if response.status_code >= 500:
                if attempt < retries:
                    await asyncio.sleep(2**attempt)
                    attempt += 1
                    continue
                raise AIProviderException(
                    "AI provider unavailable",
                    code=ErrorCode.AI_PROVIDER_UNAVAILABLE,
                    status_code=502,
                )
            if response.status_code >= 400:
                raise AIProviderException(
                    response.text[:300] or "AI provider error",
                    code=ErrorCode.AI_INVALID_RESPONSE,
                    status_code=502,
                )
            return response

    def _usage(self, payload: dict[str, Any]) -> AIUsageStats:
        usage = payload.get("usage") or {}
        return AIUsageStats(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )

    async def generate(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AIGenerateResult:
        body: dict[str, Any] = {
            "model": model or self.settings.rodiumai_default_model,
            "messages": messages,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        response = await self._request("POST", "/chat/completions", json_body=body)
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderException(
                "Invalid AI response",
                code=ErrorCode.AI_INVALID_RESPONSE,
            ) from exc
        return AIGenerateResult(
            content=content,
            model=payload.get("model") or body["model"],
            provider=self.name,
            usage=self._usage(payload),
            raw=payload,
        )

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        body: dict[str, Any] = {
            "model": model or self.settings.rodiumai_default_model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        try:
            async with self._client.stream("POST", "/chat/completions", json=body) as response:
                if response.status_code >= 400:
                    text = (await response.aread()).decode("utf-8", errors="ignore")
                    raise AIProviderException(text[:300] or "AI stream error")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue
        except httpx.TimeoutException as exc:
            raise AITimeoutException() from exc

    async def generate_structured(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        model: str | None = None,
    ) -> AIStructuredResult:
        instruction = (
            "Respond with a single JSON object matching this schema: "
            + json.dumps(schema)
            + ". No markdown."
        )
        enriched = [*messages, {"role": "system", "content": instruction}]
        result = await self.generate(messages=enriched, model=model)
        try:
            data = json.loads(result.content)
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (json.JSONDecodeError, ValueError) as exc:
            raise AIProviderException(
                "AI returned invalid structured output",
                code=ErrorCode.AI_INVALID_RESPONSE,
            ) from exc
        return AIStructuredResult(
            data=data,
            model=result.model,
            provider=self.name,
            usage=result.usage,
        )

    async def embed(
        self,
        *,
        inputs: list[str],
        model: str | None = None,
    ) -> AIEmbedResult:
        body = {
            "model": model or self.settings.rodiumai_embedding_model,
            "input": inputs if len(inputs) > 1 else inputs[0],
        }
        response = await self._request("POST", "/embeddings", json_body=body)
        payload = response.json()
        try:
            vectors = [item["embedding"] for item in payload["data"]]
        except (KeyError, TypeError) as exc:
            raise AIProviderException(
                "Invalid embeddings response",
                code=ErrorCode.AI_INVALID_RESPONSE,
            ) from exc
        raw_model = body["model"]
        if isinstance(raw_model, str):
            model_name = raw_model
        else:
            model_name = self.settings.rodiumai_embedding_model
        return AIEmbedResult(
            embeddings=vectors,
            model=str(payload.get("model") or model_name),
            provider=self.name,
            usage=self._usage(payload),
        )

    async def generate_image(
        self,
        *,
        prompt: str,
        model: str | None = None,
        size: str = "1024x1024",
    ) -> AIImageResult:
        import base64

        body = {
            "model": model or self.settings.image_model,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }
        timeout = max(self.settings.image_timeout, self.settings.rodiumai_timeout)
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.rodiumai_base_url.rstrip("/"),
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.settings.rodiumai_api_key}",
                    "Content-Type": "application/json",
                },
            ) as client:
                response = await client.post("/images/generations", json=body)
        except httpx.TimeoutException as exc:
            raise AITimeoutException() from exc
        except httpx.HTTPError as exc:
            raise AIProviderException(
                "AI image provider unavailable",
                code=ErrorCode.AI_PROVIDER_UNAVAILABLE,
            ) from exc

        if response.status_code >= 400:
            raise AIProviderException(
                response.text[:300] or "Image generation failed",
                code=ErrorCode.AI_INVALID_RESPONSE,
                status_code=502,
            )

        payload = response.json()
        try:
            item = payload["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderException(
                "Invalid image response",
                code=ErrorCode.AI_INVALID_RESPONSE,
            ) from exc

        revised = item.get("revised_prompt")
        if item.get("b64_json"):
            content = base64.b64decode(item["b64_json"])
            return AIImageResult(
                content=content,
                mime_type="image/png",
                model=str(body["model"]),
                provider=self.name,
                revised_prompt=revised,
            )

        url = item.get("url")
        if not url:
            raise AIProviderException(
                "Image response missing url/b64",
                code=ErrorCode.AI_INVALID_RESPONSE,
            )
        try:
            img_resp = await self._client.get(url)
            img_resp.raise_for_status()
        except httpx.HTTPError as exc:
            # Absolute URL may not use base_url client
            async with httpx.AsyncClient(timeout=timeout) as dl:
                img_resp = await dl.get(url)
                if img_resp.status_code >= 400:
                    raise AIProviderException(
                        "Failed to download generated image",
                        code=ErrorCode.AI_PROVIDER_UNAVAILABLE,
                    ) from exc
        return AIImageResult(
            content=img_resp.content,
            mime_type=img_resp.headers.get("content-type", "image/png"),
            model=str(body["model"]),
            provider=self.name,
            revised_prompt=revised,
        )
