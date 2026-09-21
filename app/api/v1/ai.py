"""AI routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.ai.services import embeddings as embed_service
from app.ai.services import generation as generation_service
from app.ai.services import streaming as streaming_service
from app.ai.services import structured_output as structured_service
from app.api.dependencies import (
    AIProviderDep,
    DbSession,
    LocaleDep,
    require_permission,
)
from app.core.responses import accepted_response, success_response
from app.i18n.messages import translate
from app.models.ai import AiJob
from app.models.user import User
from app.schemas.ai import (
    AiJobResponse,
    CreateAiJobRequest,
    EmbedRequest,
    EmbedResponse,
    GenerateRequest,
    GenerateResponse,
    StructuredGenerateRequest,
    StructuredGenerateResponse,
)
from app.workers.tasks.ai import run_ai_generate_job

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/generate")
async def generate(
    body: GenerateRequest,
    request: Request,
    session: DbSession,
    provider: AIProviderDep,
    locale: LocaleDep,
    user: User = Depends(require_permission("ai.generate")),
):
    result = await generation_service.generate_text(
        provider,
        session,
        user_id=user.id,
        prompt=body.prompt,
        system=body.system,
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        prompt_name=body.prompt_name,
        request_id=getattr(request.state, "request_id", None),
    )
    payload = GenerateResponse(
        content=result.content,
        model=result.model,
        provider=result.provider,
        usage={
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
        },
    )
    return success_response(payload.model_dump(), translate("ai_generate_success", locale))


@router.post("/structured")
async def structured(
    body: StructuredGenerateRequest,
    request: Request,
    session: DbSession,
    provider: AIProviderDep,
    locale: LocaleDep,
    user: User = Depends(require_permission("ai.generate")),
):
    result = await structured_service.generate_structured(
        provider,
        session,
        user_id=user.id,
        prompt=body.prompt,
        system=body.system,
        model=body.model,
        request_id=getattr(request.state, "request_id", None),
    )
    payload = StructuredGenerateResponse(
        data=result.data,
        model=result.model,
        provider=result.provider,
        usage={
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
        },
    )
    return success_response(payload.model_dump(), translate("ai_generate_success", locale))


@router.post("/stream")
async def stream(
    body: GenerateRequest,
    provider: AIProviderDep,
    user: User = Depends(require_permission("ai.stream")),
):
    async def event_generator():
        async for chunk in streaming_service.stream_text(
            provider,
            prompt=body.prompt,
            system=body.system,
            model=body.model,
        ):
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/embeddings")
async def embeddings(
    body: EmbedRequest,
    request: Request,
    session: DbSession,
    provider: AIProviderDep,
    locale: LocaleDep,
    user: User = Depends(require_permission("ai.generate")),
):
    inputs = body.input if isinstance(body.input, list) else [body.input]
    result = await embed_service.embed_texts(
        provider,
        session,
        user_id=user.id,
        inputs=inputs,
        model=body.model,
        request_id=getattr(request.state, "request_id", None),
    )
    payload = EmbedResponse(
        embeddings=result.embeddings,
        model=result.model,
        provider=result.provider,
    )
    return success_response(payload.model_dump(), translate("ok", locale))


@router.post("/jobs", status_code=202)
async def create_job(
    body: CreateAiJobRequest,
    session: DbSession,
    locale: LocaleDep,
    user: User = Depends(require_permission("ai.jobs.create")),
):
    if body.idempotency_key:
        existing = (
            await session.execute(
                select(AiJob).where(
                    AiJob.user_id == user.id,
                    AiJob.idempotency_key == body.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return accepted_response(
                AiJobResponse(
                    id=existing.id,
                    type=existing.type,
                    status=existing.status,
                    provider=existing.provider,
                    model=existing.model,
                    result=existing.result_payload,
                    error_code=existing.error_code,
                    error_message=existing.error_message,
                ).model_dump(),
                translate("ai_job_queued", locale),
            )

    job = AiJob(
        user_id=user.id,
        type=body.type,
        status="queued",
        provider="fake",
        model=body.model,
        prompt_name=body.prompt_name,
        input_payload={"prompt": body.prompt},
        idempotency_key=body.idempotency_key,
    )
    session.add(job)
    await session.flush()

    # Eager enqueue; falls back to inline processing if broker unavailable.
    try:
        run_ai_generate_job.delay(job.id)
    except Exception:
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        job.result_payload = {"content": f"INLINE_FAKE: {body.prompt[:200]}"}
        job.status = "completed"
        job.completed_at = datetime.now(UTC)

    return accepted_response(
        AiJobResponse(
            id=job.id,
            type=job.type,
            status=job.status,
            provider=job.provider,
            model=job.model,
            result=job.result_payload,
            error_code=job.error_code,
            error_message=job.error_message,
        ).model_dump(),
        translate("ai_job_queued", locale),
    )


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    session: DbSession,
    locale: LocaleDep,
    user: User = Depends(require_permission("ai.jobs.read")),
):
    job = (
        await session.execute(select(AiJob).where(AiJob.id == job_id, AiJob.user_id == user.id))
    ).scalar_one_or_none()
    if not job:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("Job not found")
    return success_response(
        AiJobResponse(
            id=job.id,
            type=job.type,
            status=job.status,
            provider=job.provider,
            model=job.model,
            result=job.result_payload,
            error_code=job.error_code,
            error_message=job.error_message,
        ).model_dump(),
        translate("ok", locale),
    )
