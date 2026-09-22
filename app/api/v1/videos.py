"""Videos API routes."""

from fastapi import APIRouter, File, UploadFile

from app.api.dependencies import AppSettings, CurrentUser, DbSession, LocaleDep
from app.core.responses import accepted_response, success_response
from app.i18n.messages import translate
from app.schemas.captions import CaptionsGenerateRequest, CaptionsPatchRequest
from app.schemas.editplan import (
    AiEditRequest,
    CreativePlanOverlayAddRequest,
    CreativePlanStartRequest,
    CreativePlanValidateRequest,
)
from app.services.analysis import service as analysis_service
from app.services.captions import service as captions_service
from app.services.creative import service as creative_service
from app.services.editplan import service as editplan_service
from app.services.videos import service as videos_service

router = APIRouter(tags=["videos"])


@router.post("/projects/{project_id}/videos", status_code=201)
async def upload_project_video(
    project_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
    file: UploadFile = File(...),
):
    content = await file.read()
    video, asset, post_process_job_id = await videos_service.upload_video(
        session,
        user_id=user.id,
        project_id=project_id,
        filename=file.filename or "upload.mp4",
        content=content,
        content_type=file.content_type or "video/mp4",
        settings=settings,
    )
    return success_response(
        videos_service.to_public(
            video, asset, post_process_job_id=post_process_job_id
        ).model_dump(mode="json"),
        translate("video_uploaded", locale),
        status_code=201,
    )


@router.get("/videos/{video_id}")
async def get_video(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await videos_service.get_video_public(
        session, user_id=user.id, video_id=video_id
    )
    return success_response(payload.model_dump(mode="json"), translate("ok", locale))


@router.delete("/videos/{video_id}")
async def delete_video(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
):
    await videos_service.delete_video(
        session, user_id=user.id, video_id=video_id, settings=settings
    )
    return success_response(None, translate("video_deleted", locale))


@router.post("/videos/{video_id}/analyze", status_code=202)
async def analyze_video(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
):
    started = await analysis_service.start_analysis(
        session, user_id=user.id, video_id=video_id, settings=settings
    )
    return accepted_response(
        started.model_dump(mode="json"),
        translate("analysis_started", locale),
    )


@router.get("/videos/{video_id}/analysis")
async def get_video_analysis(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await analysis_service.get_analysis(
        session, user_id=user.id, video_id=video_id
    )
    return success_response(payload.model_dump(mode="json"), translate("ok", locale))


@router.post("/videos/{video_id}/ai-edit", status_code=202)
async def ai_edit_video(
    video_id: str,
    body: AiEditRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
):
    started = await editplan_service.start_ai_edit(
        session,
        user_id=user.id,
        video_id=video_id,
        prompt=body.prompt,
        settings=settings,
    )
    return accepted_response(
        started.model_dump(mode="json"),
        translate("ai_edit_started", locale),
    )


@router.post("/videos/{video_id}/captions", status_code=202)
async def generate_video_captions(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
    body: CaptionsGenerateRequest = CaptionsGenerateRequest(),
):
    started = await captions_service.start_captions(
        session,
        user_id=user.id,
        video_id=video_id,
        style=body.style,
        settings=settings,
    )
    return accepted_response(
        started.model_dump(mode="json"),
        translate("captions_started", locale),
    )


@router.get("/videos/{video_id}/captions")
async def get_video_captions(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await captions_service.get_captions(
        session, user_id=user.id, video_id=video_id
    )
    return success_response(payload.model_dump(mode="json"), translate("ok", locale))


@router.patch("/videos/{video_id}/captions")
async def patch_video_captions(
    video_id: str,
    body: CaptionsPatchRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await captions_service.patch_captions(
        session, user_id=user.id, video_id=video_id, patch=body
    )
    return success_response(
        payload.model_dump(mode="json"),
        translate("captions_updated", locale),
    )


@router.get("/videos/{video_id}/creative-plan")
async def get_creative_plan(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await creative_service.get_creative_plan(
        session, user_id=user.id, video_id=video_id
    )
    return success_response(payload.model_dump(mode="json"), translate("ok", locale))


@router.post("/videos/{video_id}/creative-plan")
async def start_creative_plan(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
    body: CreativePlanStartRequest = CreativePlanStartRequest(),
):
    await videos_service.get_owned_video(session, user_id=user.id, video_id=video_id)
    await creative_service.run_creative_plan_for_video(
        session,
        video_id=video_id,
        settings=settings,
        user_prompt=body.prompt,
    )
    payload = await creative_service.get_creative_plan(
        session, user_id=user.id, video_id=video_id
    )
    return success_response(
        payload.model_dump(mode="json"),
        translate("creative_plan_ready", locale),
    )


@router.post("/videos/{video_id}/creative-plan/validate")
async def validate_creative_plan(
    video_id: str,
    body: CreativePlanValidateRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
):
    payload = await creative_service.validate_creative_plan(
        session,
        user_id=user.id,
        video_id=video_id,
        body=body,
        settings=settings,
    )
    return success_response(
        payload.model_dump(mode="json"),
        translate("creative_plan_validated", locale),
    )


@router.post("/videos/{video_id}/creative-plan/overlays", status_code=201)
async def add_creative_overlay(
    video_id: str,
    body: CreativePlanOverlayAddRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
):
    payload = await creative_service.add_creative_overlay(
        session,
        user_id=user.id,
        video_id=video_id,
        body=body,
        settings=settings,
    )
    return success_response(
        payload.model_dump(mode="json"),
        translate("ok", locale),
        status_code=201,
    )


@router.post("/videos/{video_id}/media", status_code=201)
async def upload_video_media(
    video_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
    file: UploadFile = File(...),
):
    content = await file.read()
    payload = await creative_service.upload_project_media(
        session,
        user_id=user.id,
        video_id=video_id,
        filename=file.filename or "media.bin",
        content=content,
        content_type=file.content_type or "application/octet-stream",
        settings=settings,
    )
    return success_response(
        payload.model_dump(mode="json"),
        translate("file_uploaded", locale),
        status_code=201,
    )
