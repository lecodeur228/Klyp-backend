"""AI request/response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    system: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    prompt_name: str | None = None


class GenerateResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)


class StructuredGenerateRequest(GenerateRequest):
    schema_name: str = Field(default="generic_object")


class StructuredGenerateResponse(BaseModel):
    data: dict[str, Any]
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str | None = None


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    provider: str


class CreateAiJobRequest(BaseModel):
    type: str = Field(default="generate", max_length=100)
    prompt: str = Field(min_length=1, max_length=20_000)
    model: str | None = None
    prompt_name: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class AiJobResponse(BaseModel):
    id: str
    type: str
    status: str
    provider: str
    model: str | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
